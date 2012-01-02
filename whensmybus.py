#!/usr/bin/env python
#pylint: disable=W0142,R0201
"""

When's My Bus?

A Twitter bot that takes requests for a bus time and replies the real-time data from TfL on Twitter

(c) 2011 Chris Applegate (chris AT qwghlm DOT co DOT uk)
Released under the MIT License

TODO
 - Tube, Train, Tram, DLR & Boat equivalents
"""
# Standard libraries of Python 2.6
import ConfigParser
import logging
import logging.handlers
import math
import os
import pickle
import re
import sys
import time
from pprint import pprint # For debugging

# Tweepy is a Twitter API library available from https://github.com/tweepy/tweepy
import tweepy

# From other modules in this package
from geotools import convertWGS84toOSGrid, YahooGeocoder, heading_to_direction
from exception_handling import WhensMyTransportException
from utils import WMBBrowser, load_database, capwords
from fuzzy_matching import get_best_fuzzy_match, get_bus_stop_name_similarity

# Some constants we use
VERSION_NUMBER = 0.50
TFL_API_URL = "http://countdown.tfl.gov.uk/stopBoard/%s"
HOME_DIR = os.path.dirname(os.path.abspath(__file__))

class WhensMyTransport:
    """
    Parent class for all WhensMy* bots, with common functions shared by all
    """
    def __init__(self, instance_name, testing=None, silent=False):
        """
        Read config and set up logging, settings database, geocoding and Twitter OAuth       
        """
        # Instance name is something like 'whensmybus', 'whensmytube' 
        self.instance_name = instance_name
        try:
            # Try opening the file first just to see if it exists, exception caught below
            config_file = 'whensmytransport.cfg'
            open(HOME_DIR + '/' + config_file)
            config = ConfigParser.SafeConfigParser({ 'test_mode' : False,
                                                     'debug_level' : 'INFO',
                                                     'yahoo_app_id' : None})
            config.read(HOME_DIR + '/whensmytransport.cfg')
            config.get(self.instance_name, 'debug_level')            
        except (ConfigParser.Error, IOError):
            print """Fatal error: can't find a valid config file with options for %s.
                     Please make sure there is a %s file in this directory""" % (self.instance_name, config_file)
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

        if testing is not None:
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
        
        # JSON Browser
        self.browser = WMBBrowser()
        
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

    def get_setting(self, setting_name):
        """
        Fetch value of setting from settings database
        """
        #pylint: disable=W0703
        self.settings.execute("select setting_value from %s_settings where setting_name = ?" % self.instance_name, (setting_name,))
        row = self.settings.fetchone()
        setting_value = row and row[0]
        # Try unpickling, if this doesn't work then return the raw value (to deal with legacy databases)
        if setting_value is not None:
            try:
                setting_value = pickle.loads(setting_value.encode('utf-8'))
            except Exception: # Pickle can throw loads of weird exceptions, gotta catch them all!
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
        Check my followers. If any of them are not following me, try to follow them back
        """
        # Don't bother if we have checked in the last ten minutes
        last_follower_check = self.get_setting("last_follower_check") or 0
        if time.time() - last_follower_check < 600:
            return
        logging.info("Checking to see if I have any new followers...")
        self.update_setting("last_follower_check", time.time())

        # Get IDs of our friends (people we already follow), and our followers
        followers_ids = self.api.followers_ids()[0]
        friends_ids = self.api.friends_ids()[0]
        # Some users are protected and have been requested but not accepted - we need not continually ping them
        protected_users_to_ignore = self.get_setting("protected_users_to_ignore") or []
        
        # Work out the difference between the two, and also ignore protected users we have already requested
        # Twitter gives us these in reverse order, so we pick the final twenty (i.e the earliest to follow)
        # reverse these to give them in normal order, and follow each one back!
        twitter_ids_to_follow = [f for f in followers_ids if f not in friends_ids and f not in protected_users_to_ignore][-20:] 
        for twitter_id in twitter_ids_to_follow[::-1]:
            try:
                person = self.api.create_friendship(twitter_id)
                logging.info("Following user %s", person.screen_name )
            except tweepy.error.TweepError:
                # Protected users throw an error if we try to repeatedly follow them, so keep a track of them
                # so we don't repeatedly waste API calls trying to follow them again and again
                protected_users_to_ignore.append(twitter_id)
                logging.info("Error following user %s, most likely the account is protected", twitter_id)
                continue

        # If there are any protected users we are trying to follow, we log them here for debugging purposes
        if protected_users_to_ignore:
            protected_users_info = self.api.lookup_users(user_ids = protected_users_to_ignore)
            protected_users_names = ', '.join([user.screen_name for user in protected_users_info])
            logging.debug("Following users are 'blocked' from following: %s", protected_users_names)
        self.update_setting("protected_users_to_ignore", protected_users_to_ignore)
        self.report_twitter_limit_status()
    
    def check_tweets(self):
        """
        Check Tweets that are replies to us
        """
        # Get the IDs of the Tweets and Direct Message we last answered
        last_answered_tweet = self.get_setting('last_answered_tweet')
        last_answered_direct_message = self.get_setting('last_answered_direct_message')
        
        # Fetch those Tweets and DMs. This is most likely to fail if OAuth is not correctly set up
        try:
            tweets = tweepy.Cursor(self.api.mentions, since_id=last_answered_tweet).items()
            direct_messages = tweepy.Cursor(self.api.direct_messages, since_id=last_answered_direct_message).items()
        except tweepy.error.TweepError:
            logging.error("Error: OAuth connection to Twitter failed, probably due to an invalid token")
            sys.exit(1)
        
        # Convert iterators to lists & reverse
        tweets = list(tweets)[::-1]
        direct_messages = list(direct_messages)[::-1]
        
        # No need to bother if no replies
        if not tweets and not direct_messages:
            logging.info("No new Tweets, exiting...")
        else:
            logging.info("%s replies and %s direct messages received!" , len(tweets), len(direct_messages))

        for tweet in direct_messages + tweets:

            # If the Tweet is not valid (e.g. not directly addressed, from ourselves) then skip it
            if not self.validate_tweet(tweet):
                continue
                
            # Try processing the Tweet. This may fail for a number of reasons, in which case we catch the
            # exception and process an apology accordingly
            try:
                replies = self.process_tweet(tweet)
            except WhensMyTransportException as exc:
                replies = (self.process_exception(exc),)
                
            # If the reply is blank, probably didn't contain a bus number, so check to see if there was a thank-you
            if not replies:
                replies = self.check_politeness(tweet)
                
            # Send a reply back, if we have one
            for reply in replies:
                # DMs and @ replies have different structures and different handlers
                if isinstance(tweet, tweepy.models.DirectMessage):            
                    self.send_reply_back(reply, tweet.sender.screen_name, is_direct_message=True)
                    self.update_setting('last_answered_direct_message', tweet.id)
                else:
                    self.send_reply_back(reply, tweet.user.screen_name, in_reply_to_status_id=tweet.id)
                    self.update_setting('last_answered_tweet', tweet.id)

        # Keep an eye on our rate limit, for science
        self.report_twitter_limit_status()
    
    def validate_tweet(self, tweet):
        """
        Check to see if a Tweet is valid (i.e. we want to reply to it). Tweets from ourselves, and mentions that
        are not directly addressed to us, are ignored
        """
        message = tweet.text

        # Bit of logging plus always return True for DMs
        if isinstance(tweet, tweepy.models.DirectMessage):
            logging.info("Have a DM from %s: %s", tweet.sender.screen_name, message)
            return True
        else:
            username = tweet.user.screen_name
            logging.info("Have an @ reply from %s: %s", username, message)

        # Don't start talking to yourself
        if username == self.username:
            logging.debug("Not talking to myself, that way madness lies")
            return False

        # Ignore mentions that are not direct replies
        if not message.lower().startswith('@%s' % self.username.lower()):
            logging.debug("Not a proper @ reply, skipping")
            return False

        return True

    def validate_geolocation(self, position):
        """
        Ensure any geolocation on a Tweet is valid
        """
        gridref = convertWGS84toOSGrid(position)[-1]
        # Grid reference provides us an easy way with checking to see if in the UK - it returns blank string if not in UK bounds
        if not gridref:
            raise WhensMyTransportException('not_in_uk')
        # Grids TQ and TL cover London, SU is actually west of the M25 but the 81 travels to Slough just to make life difficult for me
        elif gridref[:2] not in ('TQ', 'TL', 'SU'):
            raise WhensMyTransportException('not_in_london')           

    def check_politeness(self, tweet):
        """
        In case someone's just being nice to us, send them a "No problem"
        """
        message = tweet.text.lower()
        if message.find('thanks') > -1 or message.find('thank you') > -1:
            return ("No problem :)",)
        # The worst Easter Egg in the world
        if message.find('venga bus') > -1 or message.find('vengabus') > -1:
            return ("The Vengabus is coming, and everybody's jumping http://bit.ly/9uGZ9C",)

        return ()
            
    def send_reply_back(self, reply, username, is_direct_message=False, in_reply_to_status_id=None):
        """
        Send back a reply to the user; this might be a DM or might be a public reply
        """
        # Take care of over-long messages. 137 allows us breathing room for a letter D and spaces for
        # a direct message, so split this kind of reply into two
        if len(username) + len(reply) > 137:
            messages = reply.split("; ", 2)
            messages[0] = "%s..." % messages[0]
            messages[1] = "...%s" % messages[1]
        else:
            messages = (reply,)

        # Send the reply/replies we have generated to the user
        for message in messages:
            try:
                if is_direct_message:
                    logging.info("Sending direct message to %s: '%s'", username, message)
                    if not self.testing:
                        self.api.send_direct_message(user=username, text=message)
                else:
                    status = "@%s %s" % (username, message)
                    logging.info("Making status update: '%s'", status)
                    if not self.testing:
                        self.api.update_status(status=status, in_reply_to_status_id=in_reply_to_status_id)

            # This catches any errors, most typically if we send multiple Tweets to the same person with the same content
            # In which case, not much we can do
            except tweepy.error.TweepError:
                continue

    def process_tweet(self, tweet):
        """
        Placeholder function. This must be overridden by a child class to do anything useful
        """
        #pylint: disable=W0613
        return ()

    def process_exception(self, exc):
        """
        Turns an exception into a message for the user
        """
        logging.debug("Exception encountered: %s" , exc.value)
        return "Sorry! %s" % exc.value

    def sanitize_message(self, message):
        """ 
        Some standard things to sanitise a message - remove hashtags, @username, whitespace etc.
        """
        # Remove hashtags and @username
        message = re.sub(r"\s#\w+\b", '', message)
        if message.lower().startswith('@%s' % self.username.lower()):
            message = message[len('@%s ' % self.username):].lstrip()
        else:
            message = message.strip()

        # Exception if the Tweet contains nothing useful
        if not message:
            raise WhensMyTransportException('blank_tweet')
        return message

    def report_twitter_limit_status(self):
        """
        Helper function to log what our Twitter API hit count & limit is
        """
        limit_status = self.api.rate_limit_status()
        logging.info("I have %s out of %s hits remaining this hour", limit_status['remaining_hits'], limit_status['hourly_limit'])
        logging.debug("Next reset time is %s", (limit_status['reset_time']))

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
        """
        Constructor for the WhensMyBus class
        """
        WhensMyTransport.__init__(self, 'whensmybus', testing, silent)

    def process_tweet(self, tweet):
        """
        Process a single Tweet object and return a list of replies, one per bus route
        e.g. '341 Clerkenwell Road to Waterloo 1241; Rosebery Avenue to Angel Road 1247'
        Each reply might be more than 140 characters
        """
        # Get route number, from and to from the message
        message = tweet.text
        (route_numbers, origin, destination) = self.parse_message(message)
        
        if route_numbers == None:
            return ''
        
        # If no origin specified, let's see if we have co-ordinates on the Tweet
        position = None
        if origin == None:
            if hasattr(tweet, 'coordinates') and tweet.coordinates:
                logging.debug("Detect geolocation on Tweet, locating stops")
                # Twitter gives latitude then longitude, so need to reverse this
                position = tweet.coordinates['coordinates'][::-1]
                self.validate_geolocation(position)
            # Some people (especially Tweetdeck users) add a Place on the Tweet, but not an accurate enough long & lat
            elif hasattr(tweet, 'place') and tweet.place:
                raise WhensMyTransportException('placeinfo_only', ' '.join(route_numbers))
            # If there's no geoinformation at all then raise the appropriate exception
            else:
                if hasattr(tweet, 'coordinates'):
                    raise WhensMyTransportException('no_geotag', ' '.join(route_numbers))
                else:
                    raise WhensMyTransportException('dms_not_taggable', ' '.join(route_numbers))
                    
        replies = []
        
        for route_number in route_numbers:
            # Exceptions produced for an individual request are particular to a route/stop combination - e.g. the bus
            # given does not stop at the stop given, so we just provide an error message for that circumstance, treat as
            # a non-fatal error, and process the next one. The one case where there is a fatal error (TfL's servers are
            # down), we raise this exception to be caught higher up by check_tweets()
            try:
                replies.append(self.process_individual_request(route_number, origin, destination, position))
            except WhensMyTransportException as exc:
                if exc.msgid == 'tfl_server_down':
                    raise
                else:
                    replies.append(self.process_exception(exc))
                
        return replies
        
    def parse_message(self, message):
        """
        Parse a Tweet, but do not attempt to attain semantic meaning behind data
        Message is of format: "@whensmybus route_numbers [from origin] [to destination]"
        and may or may not have geodata on it
        Tuple returns is of format: (route_numbers, origin, destination)
        If we cannot find any of these three elements, None is used as default
        """
        # Split the message into tokens
        message = self.sanitize_message(message)
        tokens = re.split('\s', message)
        
        # Count along from the start and match as many tokens that look like a route number in a row as possible
        route_regex = "[A-Z]{0,2}[0-9]{1,3}"
        route_count = 0
        while route_count < len(tokens) and re.match(route_regex, tokens[route_count], re.I):
            route_count += 1
        route_numbers = [re.match(route_regex, t, re.I).group(0).upper() for t in tokens[:route_count]]
        if not route_numbers:
            logging.debug("@ reply didn't contain a valid-looking bus number, skipping")
            return (None, None, None)

        # Work out what boundaries "from" and "to" exist at
        if "from" in tokens:
            from_index = tokens.index("from")
        else:
            from_index = route_count - 1

        if "to" in tokens:
            to_index = tokens.index("to")
        elif "towards" in tokens:
            to_index = tokens.index("towards")        
        else:
            to_index = len(tokens)
    
        if from_index < to_index:
            origin = ' '.join(tokens[from_index+1:to_index]) or None
            destination = ' '.join(tokens[to_index+1:]) or None
        else:
            origin = ' '.join(tokens[from_index+1:]) or None
            destination = ' '.join(tokens[to_index+1:from_index]) or None
            
        return (route_numbers, origin, destination)

    def process_individual_request(self, route_number, origin, destination, position=None):
        """
        Take an individual route number, with either origin or position, and optional destination, and work out
        the stops and thus the appropriate times for the user
        """
        # Not all valid-looking bus numbers are real bus numbers (e.g. 214, RV11) so we check database to make sure
        self.geodata.execute("SELECT * FROM routes WHERE Route=?", (route_number,))
        if not len(self.geodata.fetchall()):
            raise WhensMyTransportException('nonexistent_bus', route_number)

        # Dig out relevant stop for this route from the geotag, if provided
        if position:
            relevant_stops = self.get_stops_by_geolocation(route_number, position)
        # Else there will be an origin (either a number or a placename), so try parsing it properly
        else:
            relevant_stops = self.get_stops_by_stop_name(route_number, origin)

        # See if we can narrow down the runs offered by destination
        if relevant_stops and destination:
            # Get possible destinations
            try:
                possible_destinations = self.get_stops_by_stop_name(route_number, destination)
                if possible_destinations:
                    # Filter by possible destinations. For each Run, see if there is a stop matching the destination on the same 
                    # run; if that stop has a sequence number greater than this stop then it's a valid route, so include this run 
                    relevant_stops = dict([(run, stop) for (run, stop) in relevant_stops.items() 
                                            if possible_destinations.get(run, {}).get('Sequence', -1) > stop['Sequence']])
                                            
            # We may not be able to find a destination, in which case - don't worry about this bit, and stick to unfiltered
            except WhensMyTransportException:
                pass

        # If the above has found stops on this route
        if relevant_stops:
            time_info = self.get_departure_data(relevant_stops, route_number)
            if time_info:
                reply = "%s %s" % (route_number, "; ".join(time_info))
                return reply
            else: 
                raise WhensMyTransportException('no_arrival_data', route_number)
        else:
            if re.match('^[0-9]{5}$', origin):
                raise WhensMyTransportException('stop_id_not_found', route_number, origin)
            else:
                raise WhensMyTransportException('stop_name_not_found', route_number, origin)
        
    def get_stops_by_geolocation(self, route_number, position):
        """
        Take a route number and a tuple specifying latitude & longitude, and works out closest bus stops in each direction
        
        Returns a dictionary:
            Keys are numbers of the Run (usually 1 or 2, sometimes 3 or 4).
            Values are dictionaries, with keys:
                'Stop_Name', 'Bus_Stop_Code', 'Heading', 'Distance', 'Sequence'
        """
        # GPSes use WGS84 model of Globe, but Easting/Northing based on OSGB36, so convert to an easting/northing
        logging.debug("Position in WGS84 determined as: %s %s", position[0], position[1])
        easting, northing, gridref = convertWGS84toOSGrid(position)
        logging.debug("Translated into OS Easting %s, Northing %s, Grid Reference %s", easting, northing, gridref)
        
        # A route typically has two "runs" (e.g. one eastbound, one west) but some have more than that, so work out how many we have to check
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
                          Sequence,
                          Heading,
                          Bus_Stop_Code,
                          Stop_Name
                    FROM routes
                    WHERE Route='%s' AND Run='%s'
                    ORDER BY dist_squared
                    LIMIT 1
                    """ % (easting, easting, northing, northing, route_number, run)
    
            # Note we fetch the Bus_Stop_Code not the Stop_Code_LBSL value out of this row - this is the ID used in TfL's system
            self.geodata.execute(query)
            row = self.geodata.fetchone()
            # Some Runs are non-existent (e.g. Routes that have a Run 4 but not a Run 3) so check if this is the case
            if row:
                stop = dict([(key, row[key]) for key in ('Stop_Name', 'Bus_Stop_Code', 'Heading', 'Sequence')])
                stop['Distance'] = round(math.sqrt(row['dist_squared']))
                relevant_stops[run] = stop
        
        logging.debug("Have found stop numbers: %s", ', '.join([s['Bus_Stop_Code'] for s in relevant_stops.values()]))
        return relevant_stops
            
    def get_stops_by_stop_number(self, route_number, stop_number):
        """
        Return a single dictionary representing a stop that has an ID of stop_number
        """
        # Pull the stop ID out of the routes database and see if it exists
        self.geodata.execute("SELECT * FROM routes WHERE Bus_Stop_Code=?", (stop_number, ))
        stop = self.geodata.fetchone()
        if not stop:
            raise WhensMyTransportException('bad_stop_id', stop_number)

        # Try and get a match on it
        logging.debug("Attempting to get an exact match on stop SMS ID %s", stop_number)
        self.geodata.execute("SELECT * FROM routes WHERE Bus_Stop_Code=? AND Route=?", (stop_number, route_number))
        route = self.geodata.fetchone()
        if route:
            stop = dict([(key, route[key]) for key in ('Stop_Name', 'Bus_Stop_Code', 'Heading', 'Sequence')])
            stop['Distance'] = 0
            return { route['Run'] : stop }
        else:
            return {}
            
    def get_stops_by_stop_name(self, route_number, origin):
        """
        Take a route number and name of the origin, and work out closest bus stops in each direction
        
        Returns a dictionary. Keys are numbers of the Run (usually 1 or 2, sometimes 3 and 4). Values are dictionaries
        with keys: 'Stop_Name', 'Bus_Stop_Code', 'Heading', 'Distance', 'Sequence'
        """
        # First check to see if the name is actually an ID number - if so, then use the more precise numeric method above
        match = re.match('^[0-9]{5}$', origin)
        if match:
            return self.get_stops_by_stop_number(route_number, origin)

        # First off, try to get a match against bus stop names in database
        # Users may not give exact details, so we try to match fuzzily
        logging.debug("Attempting to get a match on placename %s", origin)
        relevant_stops = {}
                     
        # A route typically has two "runs" (e.g. one eastbound, one west) but some have more than that, so work out how many we have to check
        self.geodata.execute("SELECT MAX(Run) FROM routes WHERE Route=?", (route_number,))
        max_runs = int(self.geodata.fetchone()[0])
        
        for run in range(1, max_runs+1):
            self.geodata.execute("""
                                 SELECT * FROM routes WHERE Route=? AND Run=?
                                 """, (route_number, run))
            rows = self.geodata.fetchall()
            # Some Runs are non-existent (e.g. Routes that have a Run 4 but not a Run 3) so check if this is the case
            if rows:
                best_match = get_best_fuzzy_match(origin, rows, 'Stop_Name', get_bus_stop_name_similarity)
                if best_match:
                    stop = dict([(key, best_match[key]) for key in ('Stop_Name', 'Bus_Stop_Code', 'Heading', 'Sequence')])                
                    stop['Distance'] = 0
                    logging.info("Found stop name %s for Run %s via fuzzy matching", best_match['Stop_Name'], best_match['Run'])
                    relevant_stops[run] = stop

        # If we can't find a location for either Run 1 or 2, use the geocoder to find a location on that Run matching our name
        for run in (1, 2):
            if run not in relevant_stops and self.geocoder:
                logging.debug("No match found for run %s, attempting to get geocode placename %s", run, origin)
                geocode_url = self.geocoder.get_geocode_url(origin)
                geodata = self.browser.fetch_json(geocode_url)
                points = self.geocoder.parse_geodata(geodata)
                if not points:
                    logging.debug("Could not find any matching location for %s", origin)
                    continue

                # For each of the places found, get the nearest stop that serves this run
                possible_stops = [self.get_stops_by_geolocation(route_number, p).get(run, None) for p in points]
                possible_stops = [p for p in possible_stops if p]
                possible_stops.sort(cmp=lambda a, b: cmp(a['Distance'], b['Distance']))

                if possible_stops:
                    relevant_stops[run] = possible_stops[0]
                    logging.debug("Have found stop named: %s", relevant_stops[run]['Stop_Name'])
                else:
                    logging.debug("Found a location, but could not find a nearby stop for %s", origin)
            
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
            stop_name = capwords(stop_name.strip())
        
            tfl_url = TFL_API_URL % stop_number
            bus_data = self.browser.fetch_json(tfl_url)
            arrivals = bus_data.get('arrivals', [])
            
            # Handle TfL's JSON-encoded error message
            if not arrivals and bus_data.get('stopBoardMessage', '') == "noPredictionsDueToSystemError":
                raise WhensMyTransportException('tfl_server_down')

            # Do the user a favour - check for both number and possible Night Bus version of the bus
            relevant_arrivals = [a for a in arrivals if (a['routeName'] == route_number or a['routeName'] == 'N' + route_number)
                                                        and a['isRealTime'] and not a['isCancelled']]

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

class WhensMyTube(WhensMyTransport):
    """
    Main class devoted to checking for Tube-related Tweets and replying to them. Instantiate with no variables
    (all config is done in the file whensmytransport.cfg) and then call check_tweets()
    """
    def __init__(self, testing=None, silent=False):
        WhensMyTransport.__init__(self, 'whensmytube', testing, silent)

    def process_tweet(self, tweet):
        """
        Process a single Tweet object and return a reply string
        """
        # Get route number, from and to from the message
        message = tweet.text
        self.parse_message(message)
        return ''
        
    def parse_message(self, message):
        """
        Parse a Tweet, but do not attempt to attain semantic meaning behind data
        """
        # Strip tokens out of 
        message = self.sanitize_message(message)
        tokens = re.split(r"\b(from|to)\b", message, maxsplit=2, flags=re.I)

        parsed_line = re.sub(' +Line', '', tokens[0].strip(), flags=re.I)
        origin = len(tokens) > 2 and tokens[2].strip().upper() or None
        destination = len(tokens) > 4 and tokens[4].strip().upper() or None
    
        line = parsed_line.upper()
    
        line_names = (
            'BAKERLOO',
            'CENTRAL',
            'DISTRICT',
            'HAMMERSMITH & CIRCLE',
            'JUBILEE',
            'METROPOLITAN',
            'NORTHERN',
            'PICCADILLY',
            'VICTORIA',
            'WATERLOO & CITY',
        )
        if line == 'CIRCLE':
            line = 'HAMMERSMITH & CIRCLE'
        if line not in line_names:
            line = get_best_fuzzy_match(line, line_names)
            if line is None:
                raise WhensMyTransportException('nonexistent_line', parsed_line)
        line_code = line[0]
    
        #print (line_code, origin, destination)

if __name__ == "__main__":
    WMB = WhensMyBus()
    WMB.check_tweets()
    WMB.check_followers()
    
    
    #WMT = WhensMyTube(testing=True)
    #WMT.parse_message("Norvern Line")
    #WMT.parse_message("Picadildo Line from Acton Town")
    #WMT.parse_message("Picadilly Line from Acton Town to Heathrow")
