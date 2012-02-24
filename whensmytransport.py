#!/usr/bin/env python
# -*- coding: utf-8 -*-
#pylint: disable=W0142,R0201
"""

When's My Transport?

A Twitter bot that takes requests for a bus or Tube, and replies the real-time data from TfL on Twitter

This is a parent classes used by all three bots, handling common functionality between them all, such as (but not limited to)
loading the databases, config, connecting to Twitter, reading @ replies, replying to them, checking new followers, following them back
as well as models and classes for useful constructs such as Trains and Stations

(c) 2011-12 Chris Applegate (chris AT qwghlm DOT co DOT uk)
Released under the MIT License

Things to do:

WhensMyTube/DLR:

 - Destination handling
 - Direction handling

General:

 - Equivalent for National Rail (alas, tram & boat have no public APIs)
 - Better Natural Language parsing
 - Knowledge of network layouts for Tube & bus
 - Checking of TfL APIs for weekend & long-term closures
 
"""
# Standard libraries of Python 2.6
import ConfigParser
import logging
import os
import re
import sys
from pprint import pprint # For debugging

# From library modules in this package
from lib.browser import WMTBrowser
from lib.database import WMTDatabase
from lib.exceptions import WhensMyTransportException
from lib.geo import convertWGS84toOSEastingNorthing, gridrefNumToLet, YahooGeocoder
from lib.logger import setup_logging
from lib.models import RailStation
from lib.stringutils import get_best_fuzzy_match
from lib.twitterclient import WMTTwitterClient, is_direct_message

# Some constants we use
VERSION_NUMBER = 0.60
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
            config_file = 'config.cfg'
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

        # Name of the admin so we know who to alert if there is an issue
        self.admin_name = config.get(self.instance_name, 'admin_name')

        # Setup debugging
        debug_level = config.get(self.instance_name, 'debug_level')
        setup_logging(self.instance_name, silent_mode, debug_level)
        
        # Setup database of stops/stations and their locations
        self.geodata = WMTDatabase('%s.geodata.db' % self.instance_name)
        
        # Setup browser for JSON & XML
        self.browser = WMTBrowser()
        
        # Setup geocoder for looking up place names
        yahoo_app_id = config.get(self.instance_name, 'yahoo_app_id')
        self.geocoder = yahoo_app_id and YahooGeocoder(yahoo_app_id)
        
        # Setup Twitter client
        self.username = config.get(self.instance_name,'username')
        consumer_key = config.get(self.instance_name, 'consumer_key')
        consumer_secret = config.get(self.instance_name, 'consumer_secret')
        access_token = config.get(self.instance_name, 'key')
        access_token_secret = config.get(self.instance_name, 'secret')
        if testing is None:
            testing = config.get(self.instance_name, 'test_mode')
        if testing:
            logging.info("In TEST MODE - No Tweets will be made!")
        self.twitter_client = WMTTwitterClient(self.instance_name, consumer_key, consumer_secret, access_token, access_token_secret, testing)

        # This can be overridden by child classes
        self.allow_blank_tweets = False
        
    def check_tweets(self):
        """
        Check incoming Tweets, and reply to them
        """
        tweets = self.twitter_client.fetch_tweets()
        for tweet in tweets:

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
                    self.twitter_client.send_reply_back(reply, tweet.sender.screen_name, True, tweet.id)
                else:
                    self.twitter_client.send_reply_back(reply, tweet.user.screen_name, False, tweet.id)
    
        self.twitter_client.check_followers()
    
    def validate_tweet(self, tweet):
        """
        Check to see if a Tweet is valid (i.e. we want to reply to it). Tweets from ourselves, and mentions that
        are not directly addressed to us, are ignored
        """
        message = tweet.text

        # Bit of logging, plus we always return True for DMs
        if is_direct_message(tweet):
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

    def get_tweet_geolocation(self, tweet, user_request):
        """
        Ensure any geolocation on a Tweet is valid, and return the co-ordinates as a (latitude, longitude) tuple
        """
        if hasattr(tweet, 'geo') and tweet.geo and tweet.geo.has_key('coordinates'):
            logging.debug("Detect geolocation on Tweet")
            position = tweet.geo['coordinates']
            easting, northing = convertWGS84toOSEastingNorthing(position)
            gridref = gridrefNumToLet(easting, northing)
            # Grid reference provides us an easy way with checking to see if in the UK - it returns blank string if not in UK bounds
            if not gridref:
                raise WhensMyTransportException('not_in_uk')
            # Check minimums & maximum numeric grid references - corresponding to Chesham (W), Shenfield (E), Dorking (S) and Potters Bar (N)
            elif not (495000 <= easting <= 565000 and 145000 <= northing <= 205000):
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
        message = self.sanitize_message(tweet.text).lower()
        if message.startswith('thanks') or message.startswith('thank you'):
            return ("No problem :)",)
        return ()
            
    def process_tweet(self, tweet):
        """
        Process a single Tweet object and return a list of replies, one per route or line
        e.g.:
            '@whensmybus 341 from Clerkenwell' produces
            '341 Clerkenwell Road to Waterloo 1241; Rosebery Avenue to Angel Road 1247'
        
        Each reply might be more than 140 characters
        """
        # Don't do anything if this is a thank-you
        if self.check_politeness(tweet):
            return []
            
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
        logging.debug("Exception encountered: %s" , exc.value)
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
        self.twitter_client.send_reply_back(error_message, self.admin_name, True)

    def tokenize_message(self, message, request_token_regex=None, request_token_optional=False):
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
                if tokens[first_non_request_token_index] != "to":
                    if first_non_request_token_index > 0 or request_token_optional:  
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
        if not message and not self.allow_blank_tweets:
            raise WhensMyTransportException('blank_%s_tweet' % self.instance_name.replace('whensmy', ''))

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
        logging.debug("Position in WGS84 determined as lat/long: %s %s", position[0], position[1])
        easting, northing = convertWGS84toOSEastingNorthing(position)
        logging.debug("Translated into OS Easting %s, Northing %s", easting, northing)

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
        row = self.geodata.get_row(query)
        if row:
            logging.debug("Have found %s station (%s)", row['Name'], row['Code'])
            return RailStation(**row)
        else:
            return None

    def get_station_by_station_name(self, line_code, origin):
        """
        Take a line and a string specifying origin, and work out matching for that name      
        """
        # First off, try to get a match against station names in database
        # Users may not give exact details, so we try to match fuzzily
        logging.debug("Attempting to get a match on placename %s", origin)
        rows = self.geodata.get_rows("""
                                     SELECT Name, Code, Location_Easting, Location_Northing FROM locations WHERE Line=? OR Line='X'
                                     """, (line_code,))
        if rows:
            possible_stations = [RailStation(**row) for row in rows]
            best_match = get_best_fuzzy_match(origin, possible_stations)
            if best_match:
                logging.debug("Match found! Found: %s", best_match.name)
                return best_match

        logging.debug("No match found for %s, sorry", origin)
        return None

if __name__ == "__main__":
    print "Sorry, this file is not meant to be run directly. Please run either whensmybus.py or whensmytube.py"