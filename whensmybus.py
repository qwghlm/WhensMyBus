#!/usr/bin/env python
#pylint disable=W0142
"""

When's My Bus?

A Twitter bot that takes requests for a bus timetable and @ replies on Twitter

e.g.

    @whensmybus 135
...will check the Tweet for its geocoded tag and work out the next bus

    @whensmybus 135 from 53452
...will check the Tweet for the SMS code (usually printed on a sign at the stop) and work out the next bus

    @whensmybus 135 from Canary Wharf
...will check the Tweet for the departure point name and work out the next bus

My thanks go to Adrian Short for inspiring me to write this
http://adrianshort.co.uk/2011/09/08/open-data-for-everyday-life/

and Chris Veness for his geographic co-ordinate translation scripts
http://www.movable-type.co.uk/scripts/latlong-gridref.html

(c) 2011 Chris Applegate (chris AT qwghlm DOT co DOT uk)
Released under the MIT License

TODO
 - Support for DMs
 - If a stop is the last one on a particular route & run, it should be excluded from our two big SELECT queries
 - Better bugfix for when a person send a non-blank message that is not geotagged
"""
# Standard libraries of Python 2.6
import ConfigParser
import json
import logging
import logging.handlers
import math
import os
import re
import sqlite3
import string
import sys
import time
import urllib2
from pprint import pprint # For debugging

# Tweepy is available https://github.com/tweepy/tweepy
import tweepy

# Functions from our file geotools.py
from geotools import LatLongToOSGrid, convertWGS84toOSGB36, gridrefNumToLet
from geocoders import YahooGeocoder

# Some constants we use
VERSION_NUMBER = 0.40
TFL_API_URL = "http://countdown.tfl.gov.uk/stopBoard/%s"
WHENSMYBUS_HOME = os.path.dirname(os.path.abspath(__file__))

class WhensMyBusException(Exception):
    """
    Exception we use to signal send an error to the user
    """
    # Possible id => message pairings, so we can use a shortcode to summon a much more explanatory message
    # Why do we not just send the full string as a parameter to the Exception? Mainly so we can unit test (see testing.py)
    # but also as it saves duplicating string for similar errors (e.g. when TfL service is down)
    #
    # Error message should be no longer than 115 chars so we can put a username and the word Sorry and still be under 140
    exception_values = {
        'blank_tweet'     : "I need to have a bus number in order to find the times for it",
        'nonexistent_bus' : "I couldn't recognise the number you gave me (%s) as a London bus",
        'placeinfo_only'  : "The Place info on your Tweet isn't precise enough. Please make sure you have GPS enabled, or say '%s from <place>'",
        'no_geotag'       : "Your Tweet wasn't geotagged. Please make sure you have GPS enabled on your Tweet, or say '%s from <place>'",
        'bad_stop_id'     : "I couldn't recognise the number you gave me (%s) as a valid bus stop ID",
        'stop_id_mismatch': "That bus (%s) does not appear to stop at that stop (%s)",
        'stop_not_found'  : "I couldn't find any bus stops on your route by that name (%s)",
        'not_in_uk'       : "You do not appear to be located in the United Kingdom",
        'not_in_london'   : "You do not appear to be located in the London Buses area",
        'no_stops_nearby' : "I could not find any stops near you",
        'tfl_server_down' : "I can't access TfL's servers right now - they appear to be down :(",
        'no_arrival_data' : "There is no arrival data on the TfL website for your stop - most likely no buses are due",
    }

    def __init__(self, msgid, *string_params):
        """
        Fetch a message with the ID from the dictionary above
        String formatting params optional, only needed if there is C string formatting in the error message
        e.g. WhensMyBusException('nonexistent_bus', '214')
        """
        value = WhensMyBusException.exception_values.get(msgid, '') % string_params
        super(WhensMyBusException, self).__init__(value)
        logging.debug("Application exception encountered: %s", value)
        self.value = value[:115]
        
    def __str__(self):
        return repr(self.value)

class WhensMyBus:
    """
    Main class devoted to checking for Tweets and replying to them. Instantiate with no variables
    (all config is done in the file whensmybus.cfg) and then call check_tweets()
    """
    def __init__(self, testing=None, silent=False):

        try:
            open(WHENSMYBUS_HOME + '/whensmybus.cfg')
            config = ConfigParser.SafeConfigParser({ 'test_mode' : False,
                                                     'debug_level' : 'INFO',
                                                     'yahoo_app_id' : None})
            config.read(WHENSMYBUS_HOME + '/whensmybus.cfg')
        except (ConfigParser.Error, IOError):
            print "Fatal error: can't find a valid config file. Please make sure there is a whensmybus.cfg file in this directory"
            sys.exit(1)

        # Set up some logging
        if len(logging.getLogger('').handlers) == 0:
            logging.basicConfig(level=logging.DEBUG, filename=os.devnull)

            # Set up some basic logging to stdout that shows info or debug level depending on user config
            if silent:
                console_output = open(os.devnull, 'w')
            else:
                console_output = sys.stdout
            
            console = logging.StreamHandler(console_output)
            console.setLevel(logging.__dict__[config.get('whensmybus', 'debug_level')])
            console.setFormatter(logging.Formatter('%(message)s'))

            # Set up some proper logging to file that catches debugs
            logfile = os.path.abspath(WHENSMYBUS_HOME + '/logs/whensmybus.log')
            rotator = logging.handlers.RotatingFileHandler(logfile, maxBytes=256*1024, backupCount=99)
            rotator.setLevel(logging.DEBUG)
            rotator.setFormatter(logging.Formatter('%(asctime)s %(levelname)-8s %(message)s'))
            logging.getLogger('').addHandler(console)
            logging.getLogger('').addHandler(rotator)
            logging.debug("Initializing...")

        if testing != None:
            self.testing = testing
        else:
            self.testing = config.get('whensmybus', 'test_mode')
        
        if self.testing:
            logging.info("In TEST MODE - No Tweets will be made!")

        # Load up the databases - one for the geodata, and one used a generic settings
        (_notused, self.geodata) = load_database('whensmybus.geodata.db')
        (self.settingsdb, self.settings) = load_database('whensmybus.settings.db')
        self.settings.execute("create table if not exists whensmybus_settings (setting_name unique, setting_value)")
        self.settingsdb.commit()

        # That which fetches the JSON
        self.opener = urllib2.build_opener()
        self.opener.addheaders = [('User-agent', 'When\'s My Bus? v. %s' % VERSION_NUMBER),
                                  ('Accept','text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8')]
        
        # API keys
        yahoo_app_id = config.get('whensmybus', 'yahoo_app_id')
        self.geocoder = yahoo_app_id and YahooGeocoder(yahoo_app_id)
        
        # OAuth on Twitter
        self.username = config.get('whensmybus','username')
        logging.debug("Authenticating with Twitter")
        consumer_key = config.get('whensmybus', 'consumer_key')
        consumer_secret = config.get('whensmybus', 'consumer_secret')
        key = config.get('whensmybus', 'key')
        secret = config.get('whensmybus', 'secret')
        auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
        auth.set_access_token(key, secret)        
        self.api = tweepy.API(auth)

        # This used to verify credentials, but it used up a valuable API call, so it's now disabled
        # if not self.api.verify_credentials():
            # logging.error("Error: OAuth connection to Twitter failed, probably due to an invalid token")
            # sys.exit(1)

    
    def get_setting(self, setting_name):
        """
        Simple wrapper to fetch value of setting from settings database
        """
        self.settings.execute("select setting_value from whensmybus_settings where setting_name = ?" , (setting_name,))
        row = self.settings.fetchone()
        return row and row[0]

    def update_setting(self, setting_name, setting_value):
        """
        Simple wrapper to set value of named setting in settings database
        """
        self.settings.execute("insert or replace into whensmybus_settings (setting_name, setting_value) values (?, ?)", (setting_name, setting_value))
        self.settingsdb.commit()
        
    def check_tweets(self):
        """
        Check Tweets that are replies to us
        """
        # Check For @ reply Tweets
        last_answered_tweet = self.get_setting('last_answered_tweet')
        try:
            # Rotates through pages if lots of replies
            if self.testing:
                tweets = self.api.mentions(since_id=last_answered_tweet, count=5)
            else:
                tweets = tweepy.Cursor(self.api.mentions, since_id=last_answered_tweet).items()
                
        # This is most likely to fail if OAuth is not correctly set up
        except tweepy.error.TweepError:
            logging.error("Error: OAuth connection to Twitter failed, probably due to an invalid token")
            sys.exit(1)
        
        # Convert iterator to array so we can reverse it
        tweets = [tweet for tweet in tweets][::-1]
        # No need to bother if no replies
        if not tweets:
            logging.info("No new Tweets, exiting...")
        else:
            logging.info("%s replies received!" , len(tweets))
            
        # Alright! Let's get going
        for tweet in tweets:
            try:
                replies = self.process_tweet(tweet)
            # Handler for any of the many possible reasons that this could go wrong
            except WhensMyBusException as exc:
                logging.debug("Exception encountered: %s" , exc.value)
                replies = ("@%s Sorry! %s" % (tweet.user.screen_name, exc.value),)

            # Reply back to the user, if not in testing mode
            for reply in replies:
                logging.info("Replying back to user with: %s", reply)
                if not self.testing:
                    try:
                        self.api.update_status(status=reply, in_reply_to_status_id=tweet.id)
                        self.update_setting('last_answered_tweet', tweet.id)

                    # This catches any errors, most typically if we send multiple Tweets to the same person with the same error
                    # In which case, not much we can do
                    except tweepy.error.TweepError:
                        continue

        # Keep an eye on our rate limit, for science
        self.report_twitter_limit_status()        
        
        
    def process_tweet(self, tweet):
        """
        Processes a single Tweet object and returns a list of replies to be sent back to that user        
        """
        username = tweet.user.screen_name
        message = tweet.text
        logging.info("Have a message from %s: %s", username, message)

        # Don't start talking to yourself
        if username == self.username:
            logging.debug("Not talking to myself, that way madness lies")
            return ()
            
        # Get route number, from and to from the message
        (route_number, origin, destination) = self.parse_message(message)
        # If no number found at all, just skip
        if route_number == None:
            return ()
            
        # Not all valid-looking bus numbers are real bus numbers (e.g. 214, RV11) so we check database to make sure
        self.geodata.execute("SELECT * FROM routes WHERE Route=?", (route_number,))
        if not len(self.geodata.fetchall()):
            raise WhensMyBusException('nonexistent_bus', route_number)

        # If no origin specified, let's see if we have co-ordinates on the Tweet
        if origin == None:
            if tweet.coordinates:
                logging.debug("Detect geolocation on Tweet, locating stops")
                # Twitter gives latitude then longitude, so need to reverse this
                position = tweet.coordinates['coordinates'][::-1]
                relevant_stops = self.get_stops_by_geolocation(route_number, position)
                
            # Some people (especially Tweetdeck users) add a Place on the Tweet, but not an accurate enough long & lat
            elif tweet.place:
                raise WhensMyBusException('placeinfo_only', route_number)
            
            # If there's no geoinformation at all then say so
            else:
                raise WhensMyBusException('no_geotag', route_number)
        
        else:
            # Try to see if origin is a bus stop ID
            match = re.match('^[0-9]{5}$', origin)
            if match:
                relevant_stops = self.get_stops_by_stop_number(route_number, origin)
            else:
                relevant_stops = self.get_stops_by_origin_name(route_number, origin)
        
        # If the above has found stops on this route
        if relevant_stops:
        
            # In due course, we would filter the stops by the destination specified :)
            
            time_info = self.get_departure_data(relevant_stops, route_number)
            if not time_info:
                raise WhensMyBusException('no_arrival_data')

            reply = "@%s %s %s" % (username, route_number, "; ".join(time_info))
        else:
            raise WhensMyBusException('stop_not_found', origin)
        
        # Max lead to a Tweet is 22 chars max (@ + 15 letter usename + space + 4-digit bus + space)
        # Longest stop name is HANWORTH AIR PARK LEISURE CENTRE & LIBRARY = 42 
        #
        # Longest stop name (42) + " to " + Longest terminus name (15) + space + 4-digit time + semi-colon = 67 
        #
        # So at the moment highest possible length of a single route is 67 and so longest possible Tweet is:
        # 22 + 67 + 66 = 155 characters
    
        if len(reply) > 140:
            replies = reply.split("; ", 2)
            replies[0] = "%s..." % replies[0]
            replies[1] = "@%s ...%s" % (username, replies[1])
        else:
            replies = (reply,)
            
        return tuple(replies)

    def parse_message(self, message):
        """
        Parse a message, but do not attempt to attain semantic meaning behind data   
        
        Message is of format: "@whensmybus route_number [from origin] [to destination]"
        """
        # Ignore mentions that are not direct replies
        if not message.lower().startswith('@%s' % self.username.lower()):
            logging.debug("Not a proper @ reply, skipping")
            return (None, None, None)
        
        # Remove hashtags and @username
        message = re.sub(' +#\w+ ?', '', message)
        message = message[len('@%s ' % self.username):].lstrip()
        if not message:
            raise WhensMyBusException('blank_tweet')

        # Extract a route number out of the first word by using the regexp for a London bus (0-2 letters then 1-3 numbers)
        match = re.match('^([A-Z]{0,2}[0-9]{1,3})(.*)$', message, re.I)
        # If we can't find a number, it's most likely the person was saying "Thank you" so just skip replying entirely 
        if not match:
            logging.debug("@ reply didn't contain a valid-looking bus number, skipping")
            return (None, None, None)
        
        # In case the user has used lowercase letters, fix that (e.g. d3)
        route_number = match.group(1).upper()

        # Work backwards from end of remainder to get destination, then origin
        origin, destination = None, None
        remainder = match.group(2)
        match = re.search('( +to +(.*)$)', remainder, re.I)
        destination = match and match.group(2)
        if match:
            remainder = remainder[:-1 * len(match.group(1))]

        match = re.search('( +from +(.*)$)', remainder, re.I)
        origin = match and match.group(2)
            
        return (route_number, origin, destination)
        
    def get_stops_by_geolocation(self, route_number, position):
        """
        Takes a route number and lat/lng and works out closest bus stops in each direction
        """
        # GPSes use WGS84 model of Globe, but Easting/Northing based on OSGB36, so convert
        logging.debug("Position in WGS84 determined as: %s %s", position[0], position[1])
        position = convertWGS84toOSGB36(*position)
        logging.debug("Converted to OSGB36: %s %s", position[0], position[1])

        # Turn it into an Easting/Northing
        easting, northing = LatLongToOSGrid(position[0], position[1])
        gridref = gridrefNumToLet(easting, northing)
        
        # Grid reference provides us an easy way with checking to see if in the UK - it returns blank string if not in UK bounds
        if not gridref:
            raise WhensMyBusException('not_in_uk')
        # Grids TQ and TL cover London, SU is actually west of the M25 but the 81 travels to Slough
        elif gridref[:2] not in ('TQ', 'TL', 'SU'):
            raise WhensMyBusException('not_in_london')            

        logging.debug("Translated into OS Easting %s, Northing %s", easting, northing)
        logging.debug("Translated into Grid Reference %s", gridref)

        # A route typically has two "runs" (e.g. one eastbound, one west) but some have more than that, so work out the runs
        self.geodata.execute("SELECT MAX(Run) FROM routes WHERE Route=?", (route_number,))
        max_runs = int(self.geodata.fetchone()[0])
        
        relevant_stops = {}
        for run in range(1, max_runs+1):
        
            # Do a funny bit of Pythagoras to work out closest stop. We can't find square root of a number in sqlite
            # but then again, we don't need to, the smallest square will do. Sort by this column in ascending order
            # and find the first row
            #
            # Also note the join from the routes table to locations table on the index Stop_Code_LBSL
            query = """
                    SELECT (locations.Location_Easting - %d)*(locations.Location_Easting - %d) + (locations.Location_Northing - %d)*(locations.Location_Northing - %d) AS dist_squared,
                          routes.Run,
                          locations.Heading,
                          locations.Sms_Code,
                          locations.Stop_Name
                    FROM routes
                    JOIN locations ON routes.Stop_Code_LBSL = locations.Stop_Code_LBSL
                    WHERE Route='%s' AND Run='%s'
                    ORDER BY dist_squared
                    LIMIT 1
                    """ % (easting, easting, northing, northing, route_number, run)
    
            # Note we fetch the Sms_code not the Stop_Code_LBSL value out of this row - this is the ID used
            # in TfL's system
            self.geodata.execute(query)
            row = self.geodata.fetchone()
            # Some Runs are non-existent (e.g. Many routes have a Run 4 but not a Run 3) so if this is the case, skip
            if not row:
                continue
            
            stop = dict([(key, row[key]) for key in ('Stop_Name', 'Sms_Code', 'Heading')])
            stop['Distance'] = round(math.sqrt(row['dist_squared']))
            relevant_stops[run] = stop
        
        if relevant_stops:
            logging.debug("Have found stop numbers: %s", ', '.join([s['Sms_Code'] for s in relevant_stops.values()]))
            return relevant_stops
        else:
            # This may well never be raised - there will always be a nearest stop on a route for someone, even if it is 1000km away
            raise WhensMyBusException('no_stops_nearby')
            
    def get_stops_by_stop_number(self, route_number, stop_number):
        """
        Returns a list of stops (should be length 1) that has SMS ID of stop_number
        """
        # Pull the ID out of the locations database and see if it exists
        logging.debug("Attempting to get an exact match on stop SMS ID %s", stop_number)
        self.geodata.execute("SELECT * FROM locations WHERE Sms_Code=?", (stop_number,))
        location = self.geodata.fetchone()

        if location:
            # Check that the stop with that ID is on the route that we want
            self.geodata.execute("SELECT * FROM routes WHERE Stop_Code_LBSL=? AND Route=?", (location['Stop_Code_LBSL'], route_number))
            route = self.geodata.fetchone()
            # If so then let's get the name, location, run & heading for that route
            if route:
                stop = dict([(key, location[key]) for key in ('Stop_Name', 'Sms_Code', 'Heading')])
                stop['Distance'] = 0
                return { route['Run'] : stop }
            else:
                raise WhensMyBusException('stop_id_mismatch', route_number, stop_number)
        else:
            raise WhensMyBusException('bad_stop_id', stop_number)

    def get_stops_by_origin_name(self, route_number, origin):
        """
        Tries to get relevant stops by the placename of the origin
        """
        # Try to get a match against bus stop names in database, using heuristics - an exact match, a match with a bus station
        # or a match with a rail or tube station
        logging.debug("Attempting to get a match on placename %s", origin)
        heuristics = ((lambda origin, stop: origin == stop,           1.0),
                      (lambda origin, stop: origin+"BUSSTN" == stop,  0.8),
                      (lambda origin, stop: origin+"STN" == stop,     0.7),
                     )
                     
        # We normalise our names to take care of punctuation, capitalisation, abbreviations for road names
        relevant_stops = {}
        normalised_origin = normalise_stop_name(origin)
        
        self.geodata.execute("""
                             SELECT routes.Route,
                                 routes.Run,
                                 locations.Heading,
                                 locations.Sms_Code,
                                 locations.Stop_Name          
                             FROM routes 
                             JOIN locations ON routes.Stop_Code_LBSL = locations.Stop_Code_LBSL
                             WHERE Route=?
                             """, (route_number,))
                             
        rows = self.geodata.fetchall()
        for row in rows:
            normalised_stop = normalise_stop_name(row['Stop_Name'])
            # Use each heuristic in term, and if it works out add it in...
            for (comparator, score) in heuristics:
                if comparator(normalised_origin, normalised_stop):
                    logging.debug("Found stop name %s", row['Stop_Name'])
                    stop = dict([(key, row[key]) for key in ('Stop_Name', 'Sms_Code', 'Heading')])
                    stop['Distance'] = 0
                    stop['Confidence'] = score
                    # ... but only if there is no previous match, or the score for this heuristic is better than it 
                    if not relevant_stops.get(row['Run'], {}) or score > relevant_stops[row['Run']]['Confidence']:
                        relevant_stops[row['Run']] = stop

        # If we can't find a location, use the geocoder to find a location matching that name
        if not relevant_stops and self.geocoder:
            logging.debug("No match found, attempting to get geocode placename %s", origin)
            obj = self.fetch_json(self.geocoder.get_url(origin))
            points = self.geocoder.parse_results(obj)
            if not points:
                raise WhensMyBusException('stop_not_found', origin)
                
            # Get all the corresponding pairs of bus stops for each of the points found, and sort by ascending distance
            stops = [self.get_stops_by_geolocation(route_number, p) for p in points]
            
            # Closest pair of stops wins
            stops.sort(cmp=sort_stops_by_distance)
            relevant_stops = stops[0]
            logging.debug("Have found stop numbers: %s", ', '.join([s['Sms_Code'] for s in relevant_stops.values()]))
            
        return relevant_stops
            
    def get_departure_data(self, relevant_stops, route_number):
        """
        Function that fetches the JSON data from the TfL website, for a list of relevant_stops 
        and a particular route_number, and returns the time(s) of buses on that route serving
        that stop(s)
        """
        time_info = []

        # Values in tuple correspond to what was added in relevant_stops.append() above
        for stop in relevant_stops.values():

            stop_name = stop['Stop_Name']
            stop_number = stop['Sms_Code']
            heading = stop['Heading']
        
            # Get rid of TfL's ASCII symbols for Tube, National Rail, DLR & Tram
            for unwanted in ('<>', '#', '[DLR]', '>T<'):
                stop_name = stop_name.replace(unwanted, '')
            stop_name = string.capwords(stop_name.strip())
        
            tfl_url = TFL_API_URL % stop_number
            bus_data = self.fetch_json(tfl_url)
            arrivals = bus_data.get('arrivals', [])
            
            if not arrivals:
                # Handle TfL's JSON-encoded error message
                if bus_data.get('stopBoardMessage', '') == "noPredictionsDueToSystemError":
                    raise WhensMyBusException('tfl_server_down')
                else:
                    logging.error("No arrival data for this stop right now")

            else:
                # Do the user a favour - check for both number and possible Night Bus version of the bus
                relevant_arrivals = [a for a in arrivals if (a['routeName'] == route_number or a['routeName'] == 'N' + route_number)
                                                            and a['isRealTime']
                                                            and not a['isCancelled']]

                if relevant_arrivals:
                    # Get the first arrival for now
                    arrival = relevant_arrivals[0]
                    # Every character counts! :)
                    scheduled_time =  arrival['scheduledTime'].replace(':', '')
                    # Short hack to get BST working
                    if time.localtime().tm_isdst:
                        hour = (int(scheduled_time[0:2]) + 1) % 24
                        scheduled_time = '%02d%s' % (hour, scheduled_time[2:4])
                        
                    time_info.append("%s to %s %s" % (stop_name, arrival['destination'], scheduled_time))
                else:
                    time_info.append("%s: None shown going %s" % (stop_name, heading_to_direction(heading)))

        # If the number of runs is 3 or 4, get rid of any "None shown"
        if len(time_info) > 2:
            logging.debug("Number of runs is %s, removing any non-existent entries" , len(time_info))
            time_info = [t for t in time_info if t.find("None shown") == -1]

        return time_info

    def report_twitter_limit_status(self):
        """
        Helper function to tell us what our Twitter API hit count & limit is
        """
        limit_status = self.api.rate_limit_status()
        logging.debug("I have %s out of %s hits remaining this hour", limit_status['remaining_hits'], limit_status['hourly_limit'])
        logging.debug("Next reset time is %s", (limit_status['reset_time']))

    def fetch_json(self, url, exception_code='tfl_server_down'):
        """
        Fetches a JSON URL and returns object representation of it
        """
        logging.debug("Fetching URL %s", url)
        try:
            response = self.opener.open(url)
            json_data = response.read()
    
        # Handle browsing error
        except urllib2.HTTPError, exc:
            logging.error("HTTP Error %s reading %s, aborting", exc.code, url)
            raise WhensMyBusException(exception_code)
        except Exception, exc:
            logging.error("%s (%s) encountered for %s, aborting", exc.__class__.__name__, exc, url)
            raise WhensMyBusException(exception_code)
    
        # Try to parse this as JSON
        if json_data:
            try:
                obj = json.loads(json_data)
                return obj
            # If the JSON parser is choking, probably a 503 Error message in HTML so raise a ValueError
            except ValueError, exc:
                logging.error("%s encountered when parsing %s - likely not JSON!", exc, url)
                raise WhensMyBusException(exception_code)  

# Helper functions

def load_database(dbfilename):
    """
    Helper function to load a database and return links to it and its cursor
    """
    logging.debug("Opening database %s", dbfilename)
    dbs = sqlite3.connect(WHENSMYBUS_HOME + '/db/' + dbfilename)
    dbs.row_factory = sqlite3.Row
    return (dbs, dbs.cursor())
    
def heading_to_direction(heading):
    """
    Helper function to convert a bus stop's heading (in degrees) to human-readable direction
    """
    dirs = ('North', 'NE', 'East', 'SE', 'South', 'SW', 'West', 'NW')
    # North lies between -22 and +22, NE between 23 and 67, East between 68 and 112, etc 
    i = ((int(heading)+22)%360)/45
    return dirs[i]
        
def sort_stops_by_distance(pair_a, pair_b):
    """
    Comparator for comparing two pairs of bus stops, sorting by combined distance of both from a fixed point
    """
    combined_distance_a = sum([p['Distance'] for p in pair_a.values()])
    combined_distance_b = sum([p['Distance'] for p in pair_b.values()])
    return cmp(combined_distance_a, combined_distance_b)

def normalise_stop_name(name):
    """
    Normalise a bus stop name, sorting out punctuation, capitalisation, abbreviations & symbols
    """
    # Upper-case and abbreviate road names
    normalised_name = name.upper()
    for (word, abbreviation) in (('SQUARE', 'SQ'), ('AVENUE', 'AVE'), ('STREET', 'ST'), ('ROAD', 'RD'), ('STATION', 'STN')):
        normalised_name = re.sub('\\b' + word + '\\b', abbreviation, normalised_name)
        
    # Remove Tfl's ASCII symbols for Tube, rail, DLR & Tram
    for unwanted in ('<>', '#', '[DLR]', '>T<'):
        normalised_name = normalised_name.replace(unwanted, '')
    
    # Remove non-alphanumerics and return
    normalised_name = re.sub('[\W]', '', normalised_name)
    return normalised_name
    
if __name__ == "__main__":
    WMB = WhensMyBus()
    WMB.check_tweets()
