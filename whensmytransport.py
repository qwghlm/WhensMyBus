#!/usr/bin/env python
# -*- coding: utf-8 -*-
#pylint: disable=W0142,R0201
"""

When's My Transport?

A Twitter bot that takes requests for a bus or Tube, and replies the real-time data from TfL on Twitter

(c) 2011-12 Chris Applegate (chris AT qwghlm DOT co DOT uk)
Released under the MIT License

Things to do:

WhensMyTube:

 - Destination handling
 - Direction handling

General:

 - Train, Tram, DLR & Boat equivalents
 
"""
# Standard libraries of Python 2.6
import ConfigParser
import logging
import logging.handlers
import os
import pickle
import re
import sys
import time
from pprint import pprint # For debugging

# Tweepy is a Twitter API library available from https://github.com/tweepy/tweepy
import tweepy

# From other modules in this package
from geotools import convertWGS84toOSGrid, YahooGeocoder
from exception_handling import WhensMyTransportException
from utils import WMBBrowser, load_database, is_direct_message 
from fuzzy_matching import get_best_fuzzy_match, get_rail_station_name_similarity

# Some constants we use
VERSION_NUMBER = 0.50
HOME_DIR = os.path.dirname(os.path.abspath(__file__))

class WhensMyTransport:
    """
    Parent class for all WhensMy* bots, with common functions shared by all
    """
    def __init__(self, instance_name, testing=None, silent_mode=False):
        """
        Read config and set up logging, settings database, geocoding and Twitter OAuth       
        """
        # Instance name is something like 'whensmybus', 'whensmytube' 
        self.instance_name = instance_name
        
        # Try opening the file first just to see if it exists, exception caught below
        try:
            config_file = 'whensmytransport.cfg'
            open(HOME_DIR + '/' + config_file)
            config = ConfigParser.SafeConfigParser({ 'test_mode' : False,
                                                     'debug_level' : 'INFO',
                                                     'yahoo_app_id' : None})
            config.read(HOME_DIR + '/whensmytransport.cfg')
            config.get(self.instance_name, 'debug_level')            
        except (ConfigParser.Error, IOError):
            print """Fatal error: can't find a valid config file with options for %s.""" % self.instance_name
            print """Please make sure there is a %s file in this directory""" % config_file
            sys.exit(1)

        self.admin_name = config.get(self.instance_name, 'admin_name')
        
        debug_level = config.get(self.instance_name, 'debug_level')
        self.setup_logging(silent_mode, debug_level)
        
        if testing is not None:
            self.testing = testing
        else:
            self.testing = config.get(self.instance_name, 'test_mode')
        
        if self.testing:
            self.log_info("In TEST MODE - No Tweets will be made!")

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
        self.log_debug("Authenticating with Twitter")
        consumer_key = config.get(self.instance_name, 'consumer_key')
        consumer_secret = config.get(self.instance_name, 'consumer_secret')
        key = config.get(self.instance_name, 'key')
        secret = config.get(self.instance_name, 'secret')
        auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
        auth.set_access_token(key, secret)        
        self.api = tweepy.API(auth)

    def setup_logging(self, silent_mode, debug_level):
        """
        Set up some logging for this instance
        """
        if len(logging.getLogger('').handlers) == 0:
            logging.basicConfig(level=logging.DEBUG, filename=os.devnull)

            # Logging to stdout shows info or debug level depending on user config file. Setting silent to True will override either
            if silent_mode:
                console_output = open(os.devnull, 'w')
            else:
                console_output = sys.stdout
            console = logging.StreamHandler(console_output)
            console.setLevel(logging.__dict__[debug_level])
            console.setFormatter(logging.Formatter('%(message)s'))

            # Set up some proper logging to file that catches debugs
            logfile = os.path.abspath('%s/logs/%s.log' % (HOME_DIR, self.instance_name))
            rotator = logging.handlers.RotatingFileHandler(logfile, maxBytes=256*1024, backupCount=99)
            rotator.setLevel(logging.DEBUG)
            rotator.setFormatter(logging.Formatter('%(asctime)s %(levelname)-8s %(message)s'))
            logging.getLogger('').addHandler(console)
            logging.getLogger('').addHandler(rotator)
            self.log_debug("Initializing...")

    def log_info(self, message, *args):
        """
        Wrapper for debugging at the INFO level
        """
        logging.info(message, *args)
    
    def log_debug(self, message, *args):
        """
        Wrapper for debugging at the DEBUG level
        """
        logging.debug(message, *args)

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
        self.log_info("Checking to see if I have any new followers...")
        self.update_setting("last_follower_check", time.time())

        # Get IDs of our friends (people we already follow), and our followers
        followers_ids = self.api.followers_ids()
        friends_ids = self.api.friends_ids()
        
        # Annoyingly, different versions of Tweepy implement the above; older versions return followers_ids() as a tuple and the list of 
        # followers IDs is the first element of that tuple. Newer versions return just the followers' IDs (which is much more sensible)
        if isinstance(followers_ids, tuple):
            followers_ids = followers_ids[0]
            friends_ids = friends_ids[0]
        
        # Some users are protected and have been requested but not accepted - we need not continually ping them
        protected_users_to_ignore = self.get_setting("protected_users_to_ignore") or []
        
        # Work out the difference between the two, and also ignore protected users we have already requested
        # Twitter gives us these in reverse order, so we pick the final twenty (i.e the earliest to follow)
        # reverse these to give them in normal order, and follow each one back!
        twitter_ids_to_follow = [f for f in followers_ids if f not in friends_ids and f not in protected_users_to_ignore][-20:] 
        for twitter_id in twitter_ids_to_follow[::-1]:
            try:
                person = self.api.create_friendship(twitter_id)
                self.log_info("Following user %s", person.screen_name )
            except tweepy.error.TweepError:
                protected_users_to_ignore.append(twitter_id)
                self.log_info("Error following user %s, most likely the account is protected", twitter_id)
                continue

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
            self.log_info("No new Tweets, exiting...")
        else:
            self.log_info("%s replies and %s direct messages received!" , len(tweets), len(direct_messages))

        for tweet in direct_messages + tweets:

            # If the Tweet is not valid (e.g. not directly addressed, from ourselves) then skip it
            if not self.validate_tweet(tweet):
                continue
                
            # Try processing the Tweet. This may fail with a WhensMyTransportException for a number of reasons, in which
            # case we catch the exception and process an apology accordingly
            try:
                replies = self.process_tweet(tweet)
            except WhensMyTransportException as exc:
                replies = (self.process_wmt_exception(exc),)
            # Other Python Exceptions may occur too - we handle these by DMing the admin with an alert
            except Exception as exc:
                self.alert_admin_about_exception(tweet, exc.__class__.__name__)
                replies = (self.process_wmt_exception(WhensMyTransportException('unknown_error')),)
                
            # If the reply is blank, probably didn't contain a bus number or Tube line, so check to see if there was a thank-you
            if not replies:
                replies = self.check_politeness(tweet)
                
            # Send a reply back, if we have one
            for reply in replies:
                # DMs and @ replies have different structures and different handlers
                if is_direct_message(tweet):            
                    self.send_reply_back(reply, tweet.sender.screen_name, send_direct_message=True)
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

        # Bit of logging, plus we always return True for DMs
        if is_direct_message(tweet):
            self.log_info("Have a DM from %s: %s", tweet.sender.screen_name, message)
            return True
        else:
            username = tweet.user.screen_name
            self.log_info("Have an @ reply from %s: %s", username, message)

        # Don't start talking to yourself
        if username == self.username:
            self.log_debug("Not talking to myself, that way madness lies")
            return False

        # Ignore mentions that are not direct replies
        if not message.lower().startswith('@%s' % self.username.lower()):
            self.log_debug("Not a proper @ reply, skipping")
            return False

        return True

    def get_tweet_geolocation(self, tweet, user_request):
        """
        Ensure any geolocation on a Tweet is valid, and return the co-ordinates as a (latitude, longitude) tuple
        """
        if hasattr(tweet, 'geo') and tweet.geo and tweet.geo.has_key('coordinates'):
            self.log_debug("Detect geolocation on Tweet")
            position = tweet.geo['coordinates']
            gridref = convertWGS84toOSGrid(position)[-1]
            # Grid reference provides us an easy way with checking to see if in the UK - it returns blank string if not in UK bounds
            if not gridref:
                raise WhensMyTransportException('not_in_uk')
            # Grids TQ and TL cover London, SU is actually west of the M25 but the 81 travels to Slough just to make life difficult for me
            elif gridref[:2] not in ('TQ', 'TL', 'SU'):
                raise WhensMyTransportException('not_in_london')
            else:
                return position

        # Some people (especially Tweetdeck users) add a Place on the Tweet, but not an accurate enough lat & long
        elif hasattr(tweet, 'place') and tweet.place:
            raise WhensMyTransportException('placeinfo_only', user_request)
        # If there's no geoinformation at all then raise the appropriate exception
        else:
            if hasattr(tweet, 'geo'):
                raise WhensMyTransportException('no_geotag', user_request)
            else:
                raise WhensMyTransportException('dms_not_taggable', user_request)

    def check_politeness(self, tweet):
        """
        In case someone's just being nice to us, send them a "No problem"
        """
        message = tweet.text.lower()
        if message.find('thanks') > -1 or message.find('thank you') > -1:
            return ("No problem :)",)
        # The worst Easter Egg in the world
        if self.instance_name == 'whensmybus' and (message.find('venga bus') > -1 or message.find('vengabus') > -1):
            return ("The Vengabus is coming, and everybody's jumping http://bit.ly/9uGZ9C",)

        return ()
            
    def send_reply_back(self, reply, username, send_direct_message=False, in_reply_to_status_id=None):
        """
        Send back a reply to the user; this might be a DM or might be a public reply
        """
        # Take care of over-long messages. 136 allows us breathing room for a letter D and spaces for
        # a direct message & three dots at the end, so split this kind of reply
        max_message_length = 136 - len(username)
        if len(reply) > max_message_length:
            words = reply.split(';')
            messages = [u""]
            for word in words:
                if len(word) > max_message_length:
                    continue
                if len(messages[-1]) + len(word) < max_message_length:
                    messages[-1] = messages[-1] + word + ';'
                else:
                    messages[-1] = messages[-1].strip() + u"…"
                    messages.append(u"…")
            messages[-1] = messages[-1][:-1]
            
        else:
            messages = [reply]

        # Send the reply/replies we have generated to the user
        for message in messages:
            try:
                if send_direct_message:
                    self.log_info("Sending direct message to %s: '%s'", username, message)
                    if not self.testing:
                        self.api.send_direct_message(user=username, text=message)
                else:
                    status = "@%s %s" % (username, message)
                    self.log_info("Making status update: '%s'", status)
                    if not self.testing:
                        self.api.update_status(status=status, in_reply_to_status_id=in_reply_to_status_id)

            # This catches any errors, most typically if we send multiple Tweets to the same person with the same content
            # - typically if the use sends the same bad request again and again, we will reply with same error
            # In which case, not much we can do about it, so we just ignore
            except tweepy.error.TweepError:
                continue

    def process_tweet(self, tweet):
        """
        Process a single Tweet object and return a list of replies, one per route or line
        e.g.:
            '@whensmybus 341 from Clerkenwell' produces
            '341 Clerkenwell Road to Waterloo 1241; Rosebery Avenue to Angel Road 1247'
        
        Each reply might be more than 140 characters
        """
        # Get route number, from and to from the message
        message = tweet.text
        (requested_routes, origin, destination) = self.parse_message(message)
        
        if requested_routes == None:
            return []
        
        # If no origin specified, let's see if we have co-ordinates on the Tweet
        if origin == None:
            position = self.get_tweet_geolocation(tweet, ' '.join(requested_routes))
        else:
            position = None

        replies = []
        
        for requested_route in requested_routes:
            # Exceptions produced for an individual request are particular to a route/stop combination - e.g. the bus
            # given does not stop at the stop given, so we just provide an error message for that circumstance, treat as
            # a non-fatal error, and process the next one. The one case where there is a fatal error (TfL's servers are
            # down), we raise this exception to be caught higher up by check_tweets()
            try:
                replies.append(self.process_individual_request(requested_route, origin, destination, position))
            except WhensMyTransportException as exc:
                if exc.msgid == 'tfl_server_down':
                    raise
                else:
                    replies.append(self.process_wmt_exception(exc))
                
        return replies

    def process_wmt_exception(self, exc):
        """
        Turns a WhensMyTransportException into a message for the user
        """
        self.log_debug("Exception encountered: %s" , exc.value)
        return "Sorry! %s" % exc.value

    def alert_admin_about_exception(self, tweet, exception_name):
        """
        Alert the administrator about a non-WhensMyTransportException encountered when processing a Tweet
        """
        if is_direct_message(tweet):
            tweet_time = tweet.created_at.strftime('%d-%m-%y %H:%M:%S')
            error_message = "Hey! A DM from @%s at %s GMT caused me to crash with a %s" % (tweet.sender.screen_name, tweet_time, exception_name)
        else:            
            twitter_permalink = "https://twitter.com/#!/%s/status/%s" % (tweet.user.screen_name, tweet.id)
            error_message = "Hey! A tweet from @%s caused me to crash with a %s: %s" % (tweet.user.screen_name, exception_name, twitter_permalink)
        self.send_reply_back(error_message, self.admin_name, send_direct_message=True)

    def tokenize_message(self, message, request_token_regex=None):
        """
        Split a message into tokens
        Message is of format: "@username requested_lines_or_routes [from origin] [to destination]"
        Tuple returns is of format: (requested_lines_or_routes, origin, destination)
        If we cannot find any of these three elements, None is used as default
        """
        message = self.sanitize_message(message)
        tokens = re.split('\s+', message)

        # Sometime people forget to put a 'from' in their message. So we try and put one in for them
        # Go through and find the index of the first token that does not match what a request token should be
        if "from" not in tokens and request_token_regex:
            non_request_token_indexes = [i for i in range(0, len(tokens)) if not re.match("^%s,?$" % request_token_regex, tokens[i], re.I)]
            if non_request_token_indexes:
                first_non_request_token_index = non_request_token_indexes[0]
                if first_non_request_token_index > 0 and tokens[first_non_request_token_index] != "to":
                    tokens.insert(first_non_request_token_index, "from")

        # Work out what boundaries "from" and "to" exist at
        if "from" in tokens:
            from_index = tokens.index("from")
        else:
            from_index = len(tokens)

        if "to" in tokens:
            to_index = tokens.index("to")
        elif "towards" in tokens:
            to_index = tokens.index("towards")        
        else:
            to_index = len(tokens)

        if from_index < to_index:
            request = ' '.join(tokens[:from_index]) or None
            origin = ' '.join(tokens[from_index+1:to_index]) or None
            destination = ' '.join(tokens[to_index+1:]) or None
        else:
            request = ' '.join(tokens[:to_index]) or None
            origin = ' '.join(tokens[from_index+1:]) or None
            destination = ' '.join(tokens[to_index+1:from_index]) or None
            
        return (request, origin, destination)

    def sanitize_message(self, message):
        """
        Takes a message and scrubs out any @username or #hashtags
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
        
    def parse_message(self, message):
        """
        Placeholder function. This must be overridden by a child class to do anything useful
        """
        #pylint: disable=W0613
        return (None, None, None)

    def process_individual_request(self, route_number, origin, destination, position):
        """
        Placeholder function. This must be overridden by a child class to do anything useful
        """
        #pylint: disable=W0613
        return ""
    
    def report_twitter_limit_status(self):
        """
        Helper function to log what our Twitter API hit count & limit is
        """
        limit_status = self.api.rate_limit_status()
        self.log_info("I have %s out of %s hits remaining this hour", limit_status['remaining_hits'], limit_status['hourly_limit'])
        self.log_debug("Next reset time is %s", (limit_status['reset_time']))


class RailStation():
    #pylint: disable=C0103,R0903,W0613
    """
    Class representing a railway station
    """
    def __init__(self, Name='', Code='', Location_Easting=0, Location_Northing=0, **kwargs):
        self.name = Name
        self.code = Code
        self.location_easting = Location_Easting
        self.location_northing = Location_Northing

class WhensMyRailTransport(WhensMyTransport):
    """
    Parent class for the WhensMyDLR and WhensMyTube bots. This deals with common functionality between the two -
    namely looking up stations from a database given a position or name. This works best when there is a limited number of
    stations and they have well-known, universally agreed names, which is normally railways and not buses.
    """
    def __init__(self, instance_name, testing=False, silent=False):
        """
        Constructor, called by child functions
        """
        WhensMyTransport.__init__(self, instance_name, testing, silent)
    
    def get_station_by_geolocation(self, line_code, position):
        """
        Take a line and a tuple specifying latitude & longitude, and works out closest station        
        """
        #pylint: disable=W0613
        # GPSes use WGS84 model of Globe, but Easting/Northing based on OSGB36, so convert to an easting/northing
        self.log_debug("Position in WGS84 determined as lat/long: %s %s", position[0], position[1])
        easting, northing, gridref = convertWGS84toOSGrid(position)
        self.log_debug("Translated into OS Easting %s, Northing %s, Grid Reference %s", easting, northing, gridref)

        # Do a funny bit of Pythagoras to work out closest stop. We can't find square root of a number in sqlite
        # but then again, we don't need to, the smallest square will do. Sort by this column in ascending order
        # and find the first row
        query = """
                SELECT (Location_Easting - %d)*(Location_Easting - %d) + (Location_Northing - %d)*(Location_Northing - %d) AS dist_squared,
                      Name,
                      Code,
                      Location_Easting,
                      Location_Northing
                FROM locations
                WHERE Line='%s'
                ORDER BY dist_squared
                LIMIT 1
                """ % (easting, easting, northing, northing, line_code)
        self.geodata.execute(query)
        row = self.geodata.fetchone()
        if row:
            self.log_debug("Have found %s station (%s)", row['Name'], row['Code'])
            return RailStation(**row)
        else:
            return None

    def get_station_by_station_name(self, line_code, origin):
        """
        Take a line and a string specifying origin, and work out matching for that name      
        """
        # First off, try to get a match against station names in database
        # Users may not give exact details, so we try to match fuzzily
        self.log_debug("Attempting to get a match on placename %s", origin)
        self.geodata.execute("""
                             SELECT Name, Code, Location_Easting, Location_Northing FROM locations WHERE Line=? OR Line='X'
                             """, line_code)
        rows = self.geodata.fetchall()
        if rows:
            best_match = get_best_fuzzy_match(origin, rows, 'Name', get_rail_station_name_similarity)
            if best_match:
                self.log_debug("Match found! Found: %s", best_match['Name'])
                return RailStation(**best_match)

        self.log_debug("No match found for %s, sorry", origin)
        return None


if __name__ == "__main__":
    print "Sorry, this file is not meant to be run directly. Please run either whensmybus.py or whensmytube.py"