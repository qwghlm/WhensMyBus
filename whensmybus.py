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
 - Better code for text matches in database
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
import pickle
from pprint import pprint # For debugging

# Tweepy is available https://github.com/tweepy/tweepy
import tweepy

# From other modules in this package
from geotools import LatLongToOSGrid, convertWGS84toOSGB36, gridrefNumToLet, YahooGeocoder, heading_to_direction
from exception_handling import WhensMyTransportException

# Some constants we use
VERSION_NUMBER = 0.40
TFL_API_URL = "http://countdown.tfl.gov.uk/stopBoard/%s"
HOME_DIR = os.path.dirname(os.path.abspath(__file__))

class WhensMyTransport:
    """
    Parent class for all WhensMy* bots, with common functions shared by all
    """
    def __init__(self, instance_name, testing=None, silent=False):
        """
        Read config and set up logging, URL opener, settings database, geocoding and Twitter OAuth       
        """
        self.instance_name = instance_name

        try:
            # Try opening the file first just to see if it exists, exception caught below
            open(HOME_DIR + '/whensmytransport.cfg')
            config = ConfigParser.SafeConfigParser({ 'test_mode' : False,
                                                     'debug_level' : 'INFO',
                                                     'yahoo_app_id' : None})
            config.read(HOME_DIR + '/whensmytransport.cfg')
            
        except (ConfigParser.Error, IOError):
            print "Fatal error: can't find a valid config file. Please make sure there is a whensmytransport.cfg file in this directory"
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
            console.setLevel(logging.__dict__[config.get(self.instance_name, 'debug_level')])
            console.setFormatter(logging.Formatter('%(message)s'))

            # Set up some proper logging to file that catches debugs
            logfile = os.path.abspath('%s/logs/%s.log' % (HOME_DIR, self.instance_name))
            rotator = logging.handlers.RotatingFileHandler(logfile, maxBytes=256*1024, backupCount=99)
            rotator.setLevel(logging.DEBUG)
            rotator.setFormatter(logging.Formatter('%(asctime)s %(levelname)-8s %(message)s'))
            logging.getLogger('').addHandler(console)
            logging.getLogger('').addHandler(rotator)
            logging.debug("Initializing...")

        if testing != None:
            self.testing = testing
        else:
            self.testing = config.get(self.instance_name, 'test_mode')
        
        if self.testing:
            logging.info("In TEST MODE - No Tweets will be made!")


        # Load up the databases for geodata & settings
        (_notused, self.geodata) = load_database('%s.geodata.db' % self.instance_name)
        (self.settingsdb, self.settings) = load_database('%s.settings.db' % self.instance_name)
        self.settings.execute("create table if not exists %s_settings (setting_name unique, setting_value)" % self.instance_name)
        self.settingsdb.commit()

        # That which fetches the JSON
        self.opener = urllib2.build_opener()
        self.opener.addheaders = [('User-agent', 'When\'s My Transport? v. %s' % VERSION_NUMBER),
                                  ('Accept','text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8')]
        
        # API keys
        yahoo_app_id = config.get(self.instance_name, 'yahoo_app_id')
        self.geocoder = yahoo_app_id and YahooGeocoder(yahoo_app_id)
        
        # OAuth on Twitter
        self.username = config.get(self.instance_name,'username')
        logging.debug("Authenticating with Twitter")
        consumer_key = config.get(self.instance_name, 'consumer_key')
        consumer_secret = config.get(self.instance_name, 'consumer_secret')
        key = config.get(self.instance_name, 'key')
        secret = config.get(self.instance_name, 'secret')
        auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
        auth.set_access_token(key, secret)        
        self.api = tweepy.API(auth)

        # This used to verify credentials, but it used up a valuable API call, so it's now disabled
        # if not self.api.verify_credentials():
            # logging.error("Error: OAuth connection to Twitter failed, probably due to an invalid token")
            # sys.exit(1)    

    def get_setting(self, setting_name):
        """
        Fetch value of setting from settings database
        """
        self.settings.execute("select setting_value from %s_settings where setting_name = ?" % self.instance_name, (setting_name,))
        row = self.settings.fetchone()
        setting_value = row and row[0]
        if setting_value is not None:
            try:
                setting_value = pickle.loads(setting_value.encode('utf-8'))
            except Exception:    
                pass
        return setting_value


    def update_setting(self, setting_name, setting_value):
        """
        Set value of named setting in settings database
        """
        setting_value = pickle.dumps(setting_value)
        self.settings.execute("insert or replace into %s_settings (setting_name, setting_value) values (?, ?)" % self.instance_name,
                              (setting_name, setting_value))
        self.settingsdb.commit()
        
    def check_followers(self):
        """
        Check my followers. If any of them are not following me, follow them back
        """
        # Don't bother if we have checked in the last ten minutes
        last_follower_check = self.get_setting("last_follower_check") or 0
        if time.time() - last_follower_check < 3600:
            return
    
        logging.info("Checking to see if I have any new followers...")
        self.update_setting("last_follower_check", time.time())

        followers_ids = self.api.followers_ids()[0]
        friends_ids = self.api.friends_ids()[0]
        # Some users are protected and we need not continually ping them
        protected_users_to_ignore = self.get_setting("protected_users_to_ignore") or []
        
        ids_to_follow = [f for f in followers_ids if f not in friends_ids and f not in protected_users_to_ignore][-20:]        
        for id in ids_to_follow[::-1]:
            try:
                person = self.api.create_friendship(id)
                logging.info("Following user %s" % person.screen_name )
            except tweepy.error.TweepError:
                protected_users_to_ignore.append(id)
                logging.info("Error following user %s, most likely the account is protected" % id)
                continue

        self.update_setting("protected_users_to_ignore", protected_users_to_ignore)
        self.report_twitter_limit_status()
    
    def check_tweets(self):
        """
        Check Tweets that are replies to us
        """
        # Check For @ reply Tweets
        last_answered_tweet = self.get_setting('last_answered_tweet')
        last_answered_direct_message = self.get_setting('last_answered_direct_message')

        try:
            tweets = tweepy.Cursor(self.api.mentions, since_id=last_answered_tweet).items()
            direct_messages = tweepy.Cursor(self.api.direct_messages, since_id=last_answered_direct_message).items()
                
        # This is most likely to fail if OAuth is not correctly set up
        except tweepy.error.TweepError:
            logging.error("Error: OAuth connection to Twitter failed, probably due to an invalid token")
            sys.exit(1)
        
        # Convert iterator to array so we can reverse it
        tweets = [tweet for tweet in tweets][::-1]
        direct_messages = [dm for dm in direct_messages][::-1]

        # No need to bother if no replies
        if not tweets and not direct_messages:
            logging.info("No new Tweets, exiting...")
        else:
            logging.info("%s replies received!" , len(tweets))
            logging.info("%s direct messages received!" , len(direct_messages))

            
        # First deal with Direct Messages
        for dm in direct_messages:
            try:
                reply = self.process_tweet(dm)
            except WhensMyTransportException as exc:
                logging.debug("Exception encountered: %s" , exc.value)
                reply = "Sorry! %s" % exc.value
                
            if reply:
                self.send_reply_back(reply, dm.sender.screen_name, is_direct_message=True)
                self.update_setting('last_answered_direct_message', dm.id)

        # And then with @ replies
        for tweet in tweets:
        
            if not self.validate_tweet(tweet):
                continue
        
            try:
                reply = self.process_tweet(tweet)
            # Handler for any of the many possible reasons that this could go wrong
            except WhensMyTransportException as exc:
                logging.debug("Exception encountered: %s" , exc.value)
                reply = "Sorry! %s" % exc.value

            if reply:
                self.send_reply_back(reply, tweet.user.screen_name, in_reply_to_status_id=tweet.id)
                self.update_setting('last_answered_tweet', tweet.id)

        # Keep an eye on our rate limit, for science
        self.report_twitter_limit_status()        
    
    def validate_tweet(self, tweet):
        username = tweet.user.screen_name
        message = tweet.text
        logging.info("Have a message from %s: %s", username, message)

        # Don't start talking to yourself
        if username == self.username:
            logging.debug("Not talking to myself, that way madness lies")
            return False

        # Ignore mentions that are not direct replies
        if not message.lower().startswith('@%s' % self.username.lower()):
            logging.debug("Not a proper @ reply, skipping")
            return False

        else:
            return True
    
    def send_reply_back(self, reply, username, is_direct_message=False, in_reply_to_status_id=None):
    
        # Do not Tweet if testing
        if self.testing:
            return
        
        if len(username) + len(reply) > 137:
            replies = reply.split("; ", 2)
            replies[0] = "%s..." % replies[0]
            replies[1] = "...%s" % replies[1]
        else:
            replies = (reply,)

        for reply in replies:

            try:
                if is_direct_message:
                    logging.info("Sending direct message to %s: '%s'" % (username, reply))
                    self.api.send_direct_message(user=username, text=reply)
                else:
                    status = "@%s %s" % (username, reply)
                    logging.info("Making status update: '%s'" % status)
                    self.api.update_status(status=status    , in_reply_to_status_id=in_reply_to_status_id)

            # This catches any errors, most typically if we send multiple Tweets to the same person with the same error
            # In which case, not much we can do
            except tweepy.error.TweepError:
                continue

    def process_tweet(self, tweet):
        """
        Placeholder function. This must be overridden by a child class
        """
        return None

    def report_twitter_limit_status(self):
        """
        Helper function to tell us what our Twitter API hit count & limit is
        """
        limit_status = self.api.rate_limit_status()
        logging.info("I have %s out of %s hits remaining this hour", limit_status['remaining_hits'], limit_status['hourly_limit'])
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
            raise WhensMyTransportException(exception_code)
        except Exception, exc:
            logging.error("%s (%s) encountered for %s, aborting", exc.__class__.__name__, exc, url)
            raise WhensMyTransportException(exception_code)
    
        # Try to parse this as JSON
        if json_data:
            try:
                obj = json.loads(json_data)
                return obj
            # If the JSON parser is choking, probably a 503 Error message in HTML so raise a ValueError
            except ValueError, exc:
                logging.error("%s encountered when parsing %s - likely not JSON!", exc, url)
                raise WhensMyTransportException(exception_code)  

#
#
# Clear blue water...
#
#

class WhensMyBus(WhensMyTransport):
    """
    Main class devoted to checking for bus-related Tweets and replying to them. Instantiate with no variables
    (all config is done in the file whensmytransport.cfg) and then call check_tweets()
    """
    def __init__(self, testing=None, silent=False):
        WhensMyTransport.__init__(self, 'whensmybus', testing, silent)

    def process_tweet(self, tweet):
        """
        Process a single Tweet object and return a list of replies to be sent back to that user. Each reply is a string
        e.g. '341 Clerkenwell Road to Waterloo 1241; Rosebery Avenue to Angel Road 1247'
        
        Usually the tuple only has one element; but it may be two if it otherwise would be too long over 140 characters
        """
        # Get route number, from and to from the message
        message = tweet.text
        (route_number, origin, destination) = self.parse_message(message)
        
        # If no number found at all, just skip
        if route_number == None:
            return ''
            
        # Not all valid-looking bus numbers are real bus numbers (e.g. 214, RV11) so we check database to make sure
        self.geodata.execute("SELECT * FROM routes WHERE Route=?", (route_number,))
        if not len(self.geodata.fetchall()):
            raise WhensMyTransportException('nonexistent_bus', route_number)

        # If no origin specified, let's see if we have co-ordinates on the Tweet
        if origin == None:
            if hasattr(tweet, 'coordinates') and tweet.coordinates:
                logging.debug("Detect geolocation on Tweet, locating stops")
                # Twitter gives latitude then longitude, so need to reverse this
                position = tweet.coordinates['coordinates'][::-1]
                relevant_stops = self.get_stops_by_geolocation(route_number, position)
                
            # Some people (especially Tweetdeck users) add a Place on the Tweet, but not an accurate enough long & lat
            elif hasattr(tweet, 'place') and tweet.place:
                raise WhensMyTransportException('placeinfo_only', route_number)
            
            # If there's no geoinformation at all then say so
            else:
                if hasattr(tweet, 'coordinates'):
                    raise WhensMyTransportException('no_geotag', route_number)
                else:
                    raise WhensMyTransportException('dms_not_taggable', route_number)

        
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
                raise WhensMyTransportException('no_arrival_data')

            reply = "%s %s" % (route_number, "; ".join(time_info))
        else:
            raise WhensMyTransportException('stop_not_found', origin)
        
        return reply

    def parse_message(self, message):
        """
        Parse a message, but do not attempt to attain semantic meaning behind data
        Message is of format: "@whensmybus route_number [from origin] [to destination]"
        Tuple returns is of format: (route_number, origin, destination)
        """
        # Remove hashtags and @username
        message = re.sub(' +#\w+ ?', '', message)
        
        if message.lower().startswith('@%s' % self.username.lower()):
            message = message[len('@%s ' % self.username):].lstrip()
        else:
            message = message.strip()

        if not message:
            raise WhensMyTransportException('blank_tweet')

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
        Take a route number and a tuple specifying latitude & longitude, and works out closest bus stops in each direction
        
        Returns a dictionary. Keys are numbers of the Run (usually 1 or 2, sometimes 3 or 4). Values are dictionaries
        with keys: 'Stop_Name', 'Bus_Stop_Code', 'Heading', 'Distance'
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
            raise WhensMyTransportException('not_in_uk')
        # Grids TQ and TL cover London, SU is actually west of the M25 but the 81 travels to Slough
        elif gridref[:2] not in ('TQ', 'TL', 'SU'):
            raise WhensMyTransportException('not_in_london')            

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
            query = """
                    SELECT (Location_Easting - %d)*(Location_Easting - %d) + (Location_Northing - %d)*(Location_Northing - %d) AS dist_squared,
                          Run,
                          Heading,
                          Bus_Stop_Code,
                          Stop_Name
                    FROM routes
                    WHERE Route='%s' AND Run='%s'
                    ORDER BY dist_squared
                    LIMIT 1
                    """ % (easting, easting, northing, northing, route_number, run)
    
            # Note we fetch the Bus_Stop_Code not the Stop_Code_LBSL value out of this row - this is the ID used
            # in TfL's system
            self.geodata.execute(query)
            row = self.geodata.fetchone()
            # Some Runs are non-existent (e.g. Many routes have a Run 4 but not a Run 3) so if this is the case, skip
            if not row:
                continue
            
            stop = dict([(key, row[key]) for key in ('Stop_Name', 'Bus_Stop_Code', 'Heading')])
            stop['Distance'] = round(math.sqrt(row['dist_squared']))
            relevant_stops[run] = stop
        
        if relevant_stops:
            logging.debug("Have found stop numbers: %s", ', '.join([s['Bus_Stop_Code'] for s in relevant_stops.values()]))
            return relevant_stops
        else:
            # This may well never be raised - there will always be a nearest stop on a route for someone, even if it is 1000km away
            raise WhensMyTransportException('no_stops_nearby')
            
    def get_stops_by_stop_number(self, route_number, stop_number):
        """
        Return a single dictionary representing a stop that has an ID of stop_number
        """
        # Pull the stop ID out of the routes database and see if it exists
        logging.debug("Attempting to get an exact match on stop SMS ID %s", stop_number)
        self.geodata.execute("SELECT * FROM routes WHERE Bus_Stop_Code=? AND Route=?", (stop_number, route_number))
        route = self.geodata.fetchone()
        if route:
            stop = dict([(key, route[key]) for key in ('Stop_Name', 'Bus_Stop_Code', 'Heading')])
            stop['Distance'] = 0
            return { route['Run'] : stop }
        else:
            # Check to see if bus stop actually exists at all
            self.geodata.execute("SELECT * FROM routes WHERE Bus_Stop_Code=?", (stop_number, ))
            stop = self.geodata.fetchone()
            # If the stop exists, then the bus doesn't stop there
            if stop:
                raise WhensMyTransportException('stop_id_mismatch', route_number, stop_number)
            # Else we've been given a nonsensical number
            else:
                raise WhensMyTransportException('bad_stop_id', stop_number)
    
    def get_stops_by_origin_name(self, route_number, origin):
        """
        Take a route number and name of the origin, and work out closest bus stops in each direction
        
        Returns a dictionary. Keys are numbers of the Run (usually 1 or 2, sometimes 3 and 4). Values are dictionaries
        with keys: 'Stop_Name', 'Bus_Stop_Code', 'Heading', 'Distance'
        """
        # Try to get a match against bus stop names in database, n exact match, a match with a bus station
        # or a match with a rail or tube station
        logging.debug("Attempting to get a match on placename %s", origin)
        match_functions = (lambda origin, stop: stop == origin,
                           lambda origin, stop: origin.find("BUSSTN") > -1 and stop.startswith(origin),
                           lambda origin, stop: origin.find("STN") > -1 and stop.startswith(origin),
                           lambda origin, stop: stop == origin + "BUSSTN",
                           lambda origin, stop: stop.startswith(origin + "BUSSTN"),
                           lambda origin, stop: stop == origin + "STN",
                           lambda origin, stop: stop.startswith(origin + "STN"),
                          )
                     
        # We normalise our names to take care of punctuation, capitalisation, abbreviations for road names
        relevant_stops = {}
        normalised_origin = normalise_stop_name(origin)
        
        self.geodata.execute("""
                             SELECT Route,
                                 Run,
                                 Heading,
                                 Bus_Stop_Code,
                                 Stop_Name          
                             FROM routes 
                             WHERE Route=?
                             """, (route_number,))
                             
        rows = self.geodata.fetchall()
        for row in rows:
            normalised_stop = normalise_stop_name(row['Stop_Name'])
            # Use each heuristic in term, and if it works out add it in...
            for match_function in match_functions:
                if match_function(normalised_origin, normalised_stop):
                    logging.debug("Found stop name %s for Run %s", row['Stop_Name'], row['Run'])
                    stop = dict([(key, row[key]) for key in ('Stop_Name', 'Bus_Stop_Code', 'Heading')])
                    stop['Distance'] = 0
                    # ... but only if there is no previous match, or the score for this heuristic is better than it 
                    if not row['Run'] in relevant_stops:
                        relevant_stops[row['Run']] = stop

        # If we can't find a location for directions 1 & 2, use the geocoder to find a location matching that name
        for run in range(1,3):
            if not run in relevant_stops and self.geocoder:
                logging.debug("No match found for run %s, attempting to get geocode placename %s", run, origin)

                obj = self.fetch_json(self.geocoder.get_url(origin), 'stop_not_found')
                points = self.geocoder.parse_results(obj)
                if not points:
                    logging.debug("Could not find any matching location for %s", origin)
                    continue

                # Get all corresponding bus stop for this direction for each of the points found....
                possible_stops = [self.get_stops_by_geolocation(route_number, p).get(run, None) for p in points]
                possible_stops = [p for p in possible_stops if p]
                possible_stops.sort(cmp=lambda (a,b) : cmp(a['Distance'], b['Distance']))

                if possible_stops:
                    relevant_stops[run] = possible_stops[0]
                    logging.debug("Have found stop named: %s", relevant_stops[run]['Stop_Name'])
                else:
                    logging.debug("Found a location, but could not find a nearby stop for %s", origin)

        if not relevant_stops:
            raise WhensMyTransportException('stop_not_found', origin)
            
        return relevant_stops
            
    def get_departure_data(self, relevant_stops, route_number):
        """
        Fetch the JSON data from the TfL website, for a list of relevant_stops (each a dictionary object)
        and a particular route_number, and returns the time(s) of buses on that route serving
        that stop(s)
        """
        time_info = []

        # Values in tuple correspond to what was added in relevant_stops.append() above
        for stop in relevant_stops.values():

            stop_name = stop['Stop_Name']
            stop_number = stop['Bus_Stop_Code']
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
                    raise WhensMyTransportException('tfl_server_down')
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


# Helper functions

def load_database(dbfilename):
    """
    Helper function to load a database and return links to it and its cursor
    """
    logging.debug("Opening database %s", dbfilename)
    dbs = sqlite3.connect(HOME_DIR + '/db/' + dbfilename)
    dbs.row_factory = sqlite3.Row
    return (dbs, dbs.cursor())
    
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
    WMB.check_followers()
