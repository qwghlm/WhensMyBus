#!/usr/bin/env python
# -*- coding: utf-8 -*-
#pylint: disable=W0142
"""

When's My Transport?

A Twitter bot that takes requests for a bus or Tube, and replies the real-time data from TfL on Twitter

This is a parent classes used by all three bots, handling common functionality between them all, such as (but not limited to)
loading the databases, config, connecting to Twitter, reading @ replies, replying to them, checking new followers, following them back
as well as models and classes for useful constructs such as Trains and Stations

The WhensMyBus and WhensMyRail classes handle looking up route, line, station and stop locations and names, and processing
data via the respective services' APIs

(c) 2011-12 Chris Applegate (chris AT qwghlm DOT co DOT uk)
Released under the MIT License

Things to do:

 - Fully merge WhensMyTube and WhensMyDLR, test thoroughly
 - Add corpus of Tube line & station names so we can better "guess" ambiguous messages
 - Deduces line needed for Tube/DLR if need be
 - Handle inputs based on direction


"""
# Standard libraries of Python 2.6
from abc import abstractmethod, ABCMeta
import ConfigParser
import logging
import os
import re
import sys
from pprint import pprint # For debugging

# From library modules in this package
from lib.browser import WMTBrowser
from lib.dataparsers import WMTURLProvider
from lib.exceptions import WhensMyTransportException
from lib.geo import convertWGS84toOSEastingNorthing, gridrefNumToLet, YahooGeocoder
from lib.listutils import unique_values
from lib.locations import WMTLocations
from lib.logger import setup_logging
from lib.textparser import WMTTextParser
from lib.twitterclient import WMTTwitterClient, is_direct_message

# Some constants we use
VERSION_NUMBER = 0.60
HOME_DIR = os.path.dirname(os.path.abspath(__file__))

TESTING_NONE = 0
TESTING_TEST_LOCAL_DATA = 1
TESTING_TEST_LIVE_DATA = 2


class WhensMyTransport:
    """
    Parent class for all WhensMy* bots, with common functions shared by all
    """
    __metaclass__ = ABCMeta

    def __init__(self, instance_name, testing=TESTING_NONE):
        """
        Read config and set up logging, settings database, geocoding and Twitter OAuth
        """
        # Instance name is something like 'whensmybus', 'whensmytube'
        self.instance_name = instance_name

        # Try opening the file first just to see if it exists, exception caught below
        try:
            config_file = 'config.cfg'
            open(HOME_DIR + '/' + config_file)
            config = ConfigParser.SafeConfigParser({'debug_level': 'INFO',
                                                    'yahoo_app_id': None})
            config.read(HOME_DIR + '/' + config_file)
            config.get(self.instance_name, 'debug_level')
        except (ConfigParser.Error, IOError):
            print """Fatal error: can't find a valid config file with options for %s.""" % self.instance_name
            print """Please make sure there is a %s file in this directory""" % config_file
            sys.exit(1)

        # Setup debugging
        debug_level = config.get(self.instance_name, 'debug_level')
        setup_logging(self.instance_name, testing, debug_level)
        if testing == TESTING_TEST_LOCAL_DATA:
            logging.info("In TEST MODE - No Tweets will be made and local test data will be used!")
        elif testing == TESTING_TEST_LIVE_DATA:
            logging.info("In TEST MODE - No Tweets will be made! Will be using LIVE TfL data")

        # Name of the admin so we know who to alert if there is an issue
        self.admin_name = config.get(self.instance_name, 'admin_name')

        # Setup database of stops/stations and their locations
        self.geodata = WMTLocations(self.instance_name)

        # Setup natural language parser
        self.parser = WMTTextParser(self.instance_name)

        # Setup browser for JSON & XML
        self.browser = WMTBrowser()
        self.urls = WMTURLProvider(use_test_data=(testing == TESTING_TEST_LOCAL_DATA))

        # Setup geocoder for looking up place names
        yahoo_app_id = config.get(self.instance_name, 'yahoo_app_id')
        self.geocoder = yahoo_app_id and YahooGeocoder(yahoo_app_id)

        # Setup Twitter client
        self.username = config.get(self.instance_name, 'username')
        consumer_key = config.get(self.instance_name, 'consumer_key')
        consumer_secret = config.get(self.instance_name, 'consumer_secret')
        access_token = config.get(self.instance_name, 'key')
        access_token_secret = config.get(self.instance_name, 'secret')
        self.twitter_client = WMTTwitterClient(self.instance_name, consumer_key, consumer_secret, access_token, access_token_secret, testing)

        # This can be overridden by child classes
        self.allow_blank_tweets = False

    def check_tweets(self):
        """
        Check incoming Tweets, and reply to them
        """
        tweets = self.twitter_client.fetch_tweets()
        logging.debug("%s Tweets to process", len(tweets))
        for tweet in tweets:
            # If the Tweet is not valid (e.g. not directly addressed, from ourselves) then skip it
            if not self.validate_tweet(tweet):
                continue

            # Try processing the Tweet. This may fail with a WhensMyTransportException for a number of reasons, in which
            # case we catch the exception and process an apology accordingly. Other Python Exceptions may occur too - we handle
            # these by DMing the admin with an alert
            try:
                replies = self.process_tweet(tweet)
            except WhensMyTransportException as exc:
                replies = (exc.get_user_message(),)
            except Exception as exc:
                self.alert_admin_about_exception(tweet, exc.__class__.__name__)
                replies = (WhensMyTransportException('unknown_error').get_user_message(),)

            # If the reply is blank, probably didn't contain a bus number or Tube line, so check to see if there was a thank-you
            if not replies:
                replies = self.check_politeness(tweet)

            # Send a reply back, if we have one. DMs and @ replies have different structures and different handlers
            for reply in replies:
                if is_direct_message(tweet):
                    self.twitter_client.send_reply_back(reply, tweet.sender.screen_name, True, tweet.id)
                else:
                    self.twitter_client.send_reply_back(reply, tweet.user.screen_name, False, tweet.id)

        self.twitter_client.check_followers()

    def validate_tweet(self, tweet):
        """
        Check to see if a Tweet is valid (i.e. we want to reply to it), and returns True if so
        Tweets from ourselves, and mentions that are not directly addressed to us, returns False
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

    def process_tweet(self, tweet):
        """
        Process a single Tweet object and return a list of strings (replies), one per route or line
        e.g.:
            '@whensmybus 341 from Clerkenwell' produces
            '341 Clerkenwell Road to Waterloo 1241; Rosebery Avenue to Angel Road 1247'

        Each reply might be more than 140 characters
        No replies at all are given if the message is a thank-you or does not include a route or line
        """
        # Don't do anything if this is a thank-you
        if self.check_politeness(tweet):
            logging.debug("This Tweet is a thank-you Tweet, skipping")
            return []

        # Get route number, from and to from the message
        message = self.sanitize_message(tweet.text)
        logging.debug("Message from user: %s", message)
        (requested_routes, origin, destination) = self.parser.parse_message(message)
        if requested_routes is None:
            if self.instance_name == 'whensmydlr':
                logging.debug("No line name detected, falling back on default of DLR")
                requested_routes = ('DLR',)
            else:
                logging.debug("No routes or lines detected on this Tweet, skipping")
                return []

        # If no origin specified, let's see if we have co-ordinates on the Tweet
        if origin is None:
            position = self.get_tweet_geolocation(tweet, message)
        else:
            position = None

        replies = []
        for requested_route in requested_routes:
            try:
                replies.append(self.process_individual_request(requested_route, origin, destination, position))
            # Exceptions produced for an individual request are particular to a route/stop combination - e.g. the bus
            # given does not stop at the stop given, so we just provide an error message for that circumstance, treat as
            # a non-fatal error, and process the next one. The one case where there is a fatal error (TfL's servers are
            # down), we raise this exception to be caught higher up by check_tweets()
            except WhensMyTransportException as exc:
                if exc.msgid == 'tfl_server_down':
                    raise
                else:
                    replies.append(exc.get_user_message())
        return replies

    def check_politeness(self, tweet):
        """
        Checks a Tweet for politeness. In case someone's just being nice to us, return a "No problem" else return an empty list
        """
        message = self.sanitize_message(tweet.text).lower()
        if message.startswith('thanks') or message.startswith('thank you'):
            return ("No problem :)",)
        return ()

    def sanitize_message(self, message):
        """
        Takes a message, scrub out the @username of this bot and any #hashtags, and return the sanitized messages
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

    def get_tweet_geolocation(self, tweet, user_request):
        """
        Ensure any geolocation on a Tweet is valid, and return the co-ordinates as a (latitude, longitude) tuple
        """
        if hasattr(tweet, 'geo') and tweet.geo and 'coordinates' in tweet.geo:
            logging.debug("Detecting geolocation on Tweet")
            position = tweet.geo['coordinates']
            easting, northing = convertWGS84toOSEastingNorthing(*position)
            # Grid reference provides us an easy way with checking to see if in the UK - it returns blank string if not in UK bounds
            if not gridrefNumToLet(easting, northing):
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

    @abstractmethod
    def process_individual_request(self, code, origin, destination, position):
        """
        Abstract method. This must be overridden by a child class to do anything useful
        Takes a code (e.g. a bus route or line name), origin, destination and (latitude, longitude) tuple
        Returns a string repesenting the message sent back to the user. This can be more than 140 characters
        """
        #pylint: disable=W0613,R0201
        return ""

    @abstractmethod
    def get_departure_data(self, station_or_stops, line_or_route, via):
        """
        Abstract method. This must be overridden by a child class to do anything useful

        Takes a string or list of strings representing a station or stop, and a string representing the line or route,
        and a string representing the stop the line or route has to stop at

        Returns a dictionary; items are lists of Departure objects, keys are "slots" that we have grouped these Departures into
            Buses are grouped by Run and the keys are thus the Run numbers
            TubeTrains are grouped by direction, keys are "Eastbound", "Westbound" etc.
            DLRTrains are grouped by platform, keys are "p1", "p2"
        """
        #pylint: disable=W0613,R0201
        return {}

    def cleanup_departure_data(self, departure_data, null_object_constructor):
        """
        Takes a dictionary produced by get_departure_data, cleans it up and returns it

        If no departures listed at all, then return an empty dictionary
        Any slot with an empty list as its value has it filled with a null object, which is constructed by null_object_constructor
        Any slot with None as its value is deleted

        null_object_constructor is either a classname constructor, or a function that returns a created object
        e.g. lambda a: Constructor(a.lower())
        """
        # Make sure there is a departure in at least one slot
        if not [departures for departures in departure_data.values() if departures]:
            return {}
        # Go through list of slots and departures for them.  If there is a None, then there is no slot at all and we delete it
        # If there is an empty list (no departures) then we replace it with the null object specified ("None shown...").
        for slot in departure_data.keys():
            if departure_data[slot] is None:
                del departure_data[slot]
            elif departure_data[slot] == []:
                departure_data[slot] = [null_object_constructor(slot)]
        return departure_data

    def format_departure_data(self, departure_data):
        """
        Takes a dictionary produced by get_departure_data, and turn into a formatted string for the user
        Departures are sorted by slot ID and then earliest first
        """
        # dict.keys() does not preserve order, hence a list of the correct order for destinations as well
        destinations_correct_order = []
        departures_by_destination = {}
        # Go through each slot, and each slot's departures, sorted in time order
        for slot in sorted(departure_data.keys()):
            for departure in unique_values(sorted(departure_data[slot]))[:3]:
                destination = departure.get_destination()
                # Create a slot for this departure if none exists
                if destination not in departures_by_destination:
                    departures_by_destination[destination] = []
                    destinations_correct_order.append(destination)
                # Add in the time for this departure
                if departure.get_departure_time() and len(departures_by_destination[destination]) < 3:
                    departures_by_destination[destination].append(departure.get_departure_time())

        departures_list = ["%s %s" % (destination, ', '.join(departures_by_destination[destination])) for destination in destinations_correct_order]
        return '; '.join([departure.strip() for departure in departures_list])

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


if __name__ == "__main__":
    print "Sorry, this file is not meant to be run directly. Please run either whensmybus.py or whensmyrail.py"
