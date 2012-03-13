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
from abc import abstractmethod, ABCMeta
import ConfigParser
import logging
import os
import re
import sys
from pprint import pprint # For debugging

# From library modules in this package
from lib.browser import WMTBrowser
from lib.exceptions import WhensMyTransportException
from lib.geo import convertWGS84toOSEastingNorthing, gridrefNumToLet, YahooGeocoder
from lib.locations import WMTLocations
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
    __metaclass__ = ABCMeta

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
            config = ConfigParser.SafeConfigParser({'test_mode': False,
                                                    'debug_level': 'INFO',
                                                    'yahoo_app_id': None})
            config.read(HOME_DIR + '/' + config_file)
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
        self.geodata = WMTLocations(self.instance_name)

        # Setup browser for JSON & XML
        self.browser = WMTBrowser()

        # Setup geocoder for looking up place names
        yahoo_app_id = config.get(self.instance_name, 'yahoo_app_id')
        self.geocoder = yahoo_app_id and YahooGeocoder(yahoo_app_id)

        # Setup Twitter client
        self.username = config.get(self.instance_name, 'username')
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
        if hasattr(tweet, 'geo') and tweet.geo and 'coordinates' in tweet.geo:
            logging.debug("Detect geolocation on Tweet")
            position = tweet.geo['coordinates']
            easting, northing = convertWGS84toOSEastingNorthing(*position)
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
        logging.debug("Exception encountered: %s", exc.get_value())
        return "Sorry! %s" % exc.get_value()

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
            origin = ' '.join(tokens[from_index + 1:to_index]) or None
            destination = ' '.join(tokens[to_index + 1:]) or None
        else:
            request = ' '.join(tokens[:to_index]) or None
            origin = ' '.join(tokens[from_index + 1:]) or None
            destination = ' '.join(tokens[to_index + 1:from_index]) or None

        return (request, origin, destination)

    def cleanup_departure_data(self, departure_data, null_object_constructor):
        """
        Takes a dictionary produced by get_departure_data and cleans it up. If no departures listed at all,
        then return an empty dictionary, else fill any slot with a null object, represented by null_object_constructor

        null_object_constructor is either a classname constructor, or a function that returns a created object
        e.g. lambda a: Constructor(a.lower())
        """
        # Make sure there is a bus in at least one stop, and if not then fill empty runs with NullDeparture objects
        if not [departures for departures in departure_data.values() if departures]:
            return {}
        for key in departure_data.keys():
            if not departure_data[key]:
                departure_data[key] = [null_object_constructor(key)]
        return departure_data

    def format_departure_data(self, departures_by_platform):
        """
        Take departure data (which is a dictionary of { platform_id : [Departure list], ... } values), and turn into a formatted
        string. Departures are sorted into earliest first and roughly clustered around common platforms

        Note that "platform" is a generic term and can refer to a platform (DLR), direction (Tube), or bus stop (Bus) depending
        on how the particular mode of transport is best organised
        """
        # Dictionaries alone do not preserve order, hence a list of the correct order for destinations as well
        destinations_correct_order = []
        departures_by_destination = {}
        # Go through each platform, and each platform's departures, sorted in time order
        for platform in sorted(departures_by_platform.keys()):
            for departure in sorted(departures_by_platform[platform]):
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

    @abstractmethod
    def parse_message(self, message):
        """
        Abstract method. This must be overridden by a child class to do anything useful
        Takes message, the message from the user. Returns a tuple of (line_or_routes_specified, origin, destination)
        """
        #pylint: disable=W0613
        return (None, None, None)

    @abstractmethod
    def process_individual_request(self, code, origin, destination, position):
        """
        Abstract method. This must be overridden by a child class to do anything useful
        Takes a code (e.g. a bus route or line name), origin, destination and (latitude, longitude) tuple
        Returns a string repesenting the message sent back to the user. This can be more than 140 characters
        """
        #pylint: disable=W0613
        return ""

    @abstractmethod
    def get_departure_data(self, station_or_stops, line_or_route):
        """
        Abstract method. This must be overridden by a child class to do anything useful
        Takes a string or list of strings representing a station or stop, and a string representing the line or route
        Returns a dictionary; items are lists of Departure objects, keys are however we have grouped those Departures
        e.g. buses are grouped by Run and the keys are thus the Run numbers
        """
        #pylint: disable=W0613
        return {}


class WhensMyRailTransport(WhensMyTransport):
    """
    Parent class for the WhensMyDLR and WhensMyTube bots. This deals with common functionality between the two -
    namely looking up stations from a database given a position or name. This works best when there is a limited number of
    stations and they have well-known, universally agreed names, which is normally railways and not buses.
    """
    __metaclass__ = ABCMeta

    def __init__(self, instance_name, testing=False, silent=False):
        """
        Constructor, called by child functions
        """
        WhensMyTransport.__init__(self, instance_name, testing, silent)
        self.line_lookup = {}

    def process_individual_request(self, line_name, origin, destination, position):
        """
        Take an individual line, with either origin or position, and work out which station the user is
        referring to, and then get times for it
        """
        line = self.line_lookup.get(line_name, "") or get_best_fuzzy_match(line_name, self.line_lookup.values())
        if not line:
            raise WhensMyTransportException('nonexistent_line', line_name)
        line_code = get_line_code(line)
        if line != 'DLR':
            line_name += " Line"

        # Dig out relevant station for this line from the geotag, if provided
        # Else there will be an origin (either a number or a placename), so try parsing it properly
        if position:
            station = self.get_station_by_geolocation(line_code, position)
        else:
            station = self.get_station_by_station_name(line_code, origin)

        destination_name = None
        if destination:
            try:
                destination_station = self.get_station_by_station_name(line_code, destination)
                if destination_station:
                    destination_name = destination_station.name
            # We may not be able to find a destination, in which case - don't worry about this bit, and stick to unfiltered
            except WhensMyTransportException:
                logging.debug("Could not find a destination matching %s this route, skipping and not filtering results", destination)

        if destination_name and not self.geodata.direct_route_exists(station.name, destination_name, line=line):
            raise WhensMyTransportException('no_direct_route', station.name, destination_name, line_name)

        # If we have a station code, go get the data for it
        if station:
            if station.code == "XXX":  # XXX is the code for a station that does not have data given to it
                raise WhensMyTransportException('rail_station_not_in_system', station.name)

            departure_data = self.get_departure_data(station, line_code, must_stop_at=destination_name)
            if departure_data:
                return "%s to %s" % (station.get_abbreviated_name(), self.format_departure_data(departure_data))
            else:
                if destination_name:
                    raise WhensMyTransportException('no_trains_shown_to', line_name, station.name, destination_name)
                else:
                    raise WhensMyTransportException('no_trains_shown', line_name, station.name)
        else:
            raise WhensMyTransportException('rail_station_name_not_found', origin, line_name)

    def get_station_by_geolocation(self, line_code, position):
        """
        Take a line and a tuple specifying latitude & longitude, and works out closest station
        """
        logging.debug("Attempting to get closest to position: %s", position)
        return self.geodata.find_closest(position, {'Line': line_code}, RailStation)

    def get_station_by_station_name(self, line_code, origin):
        """
        Take a line and a string specifying origin, and work out matching for that name
        """
        logging.debug("Attempting to get a fuzzy match on placename %s", origin)
        return self.geodata.find_fuzzy_match({'Line': line_code}, origin, RailStation)


def get_line_code(line_name):
    """
    Return the TfL line code for the line requested, which is always the first letter except the Circle, whose code is 'O'
    """
    return (line_name == 'Circle') and 'O' or line_name[0]

if __name__ == "__main__":
    print "Sorry, this file is not meant to be run directly. Please run either whensmybus.py or whensmytube.py"
