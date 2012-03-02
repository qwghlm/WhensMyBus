#!/usr/bin/env python
# -*- coding: utf-8 -*-
#pylint: disable=C0103,W0141,R0904,W0142
"""
A set of unit tests for When's My Bus?

IMPORTANT: These unit tests require Python 2.7, although When's My Bus will happily run in Python 2.6
"""
import sys
if sys.version_info < (2, 7):
    print "Sorry. While WhensMyBus can be run under Python 2.6, this unit testing script requires the more extensive unittest libraries in Python 2.7."
    print "Please upgrade!"
    sys.exit(1)

from whensmybus import WhensMyBus
from whensmydlr import WhensMyDLR
from whensmytube import WhensMyTube
from lib.exceptions import WhensMyTransportException

from lib.geo import heading_to_direction, gridrefNumToLet, convertWGS84toOSEastingNorthing, LatLongToOSGrid, convertWGS84toOSGB36
from lib.listutils import unique_values
from lib.stringutils import capwords, get_name_similarity, get_best_fuzzy_match, cleanup_name_from_undesirables
from lib.models import RailStation, BusStop, Train, TubeTrain

import argparse
import random
import re
import unittest
from pprint import pprint


class FakeTweet:
    """
    Fake Tweet object to simulate tweepy's Tweet object being passed to various functions
    """
    #pylint: disable=R0903
    def __init__(self, text, coordinates=(), place=None, username='testuser'):
        self.user = lambda: 1
        self.user.screen_name = username
        self.text = text
        self.place = place
        self.geo = {}
        if coordinates:
            self.geo['coordinates'] = coordinates


class FakeDirectMessage:
    """
    Fake DirectMessage object to simulate tweepy's DirectMessage object being passed to various functions
    """
    #pylint: disable=R0903
    def __init__(self, text, username='testuser'):
        self.user = lambda: 1
        self.user.screen_name = username
        self.text = text


class WhensMyTransportTestCase(unittest.TestCase):
    """
    Parent Test case for all When's My * bots
    """
    def setUp(self):
        """
        Setup test
        """
        # setUp is left to the individual test suite
        self.bot = None

    def tearDown(self):
        """
        Tear down test
        """
        # Bit of a hack - we insist that any print statements are output, after the tests regardless of whether we failed or not
        self._resultForDoCleanups._mirrorOutput = True
        self.bot = None

    def _test_correct_exception_produced(self, tweet, exception_id, *string_params):
        """
        A generic test that the correct exception message is produced
        """
        # Get the message for the exception_id specified, applying C string formatting if applicable
        # Then escape it so that regular expression module doesn't accidentally interpret brackets etc
        expected_error = re.escape(WhensMyTransportException(exception_id, *string_params).value)

        # Try processing the relevant Tweet
        try:
            messages = self.bot.process_tweet(tweet)
        # If an exception is thrown, then see if its message matches the one we want
        except WhensMyTransportException as exc:
            self.assertRegexpMatches(exc.value, expected_error)
        # If there is no exception thrown, then see if the reply generated matches what we want
        else:
            for message in messages:
                self.assertRegexpMatches(message, expected_error)

    # Fundamental unit tests. These test libraries and essential methods and classes. These do not need a bot set up
    # and are thus independent of config and setup
    def test_geo(self):
        """
        Unit test for geo conversion methods
        """
        # Test co-ordinate conversions on the location of St James's Park Station
        wgs84 = (51.4995893, -0.1342974)
        osgb36 = (51.4990781, -0.1326920)
        easting_northing = (529600, 179500)
        gridref = "TQ2960079500"

        self.assertEqual(convertWGS84toOSGB36(*wgs84)[:2], osgb36)
        self.assertEqual(LatLongToOSGrid(*osgb36), easting_northing)
        self.assertEqual(convertWGS84toOSEastingNorthing(*wgs84), easting_northing)
        self.assertEqual(gridrefNumToLet(*easting_northing), gridref)

        # Test heading_to_direction with a series of preset values
        for (heading, direction) in ((0, "North"), (90, "East"), (180, "South"), (270, "West"),):
            self.assertEqual(heading_to_direction(heading), direction)

    def test_listutils(self):
        """
        Unit test for listutils methods
        """
        test_list = [random.Random().randint(0, 10) for _i in range(0, 100)]
        unique_list = unique_values(test_list)
        # Make sure every value in new list was in old list
        for value in unique_list:
            self.assertTrue(value in test_list)
        # And that every value in the old list is now exactly once in new list
        for value in test_list:
            self.assertEqual(unique_list.count(value), 1)

    def test_stringutils(self):
        """
        Unit test for stringutils' methods
        """
        # Check capwords
        capitalised_strings = ("Bank", "Morden East", "King's Cross St. Pancras", "Kennington Oval via CX")
        for test_string in capitalised_strings:
            self.assertEqual(test_string, capwords(test_string))
            #self.assertEqual(test_string, capwords(test_string.lower())) FIXME
            #self.assertEqual(test_string, capwords(test_string.upper()))
            self.assertNotEqual(test_string.lower(), capwords(test_string))
            self.assertNotEqual(test_string.upper(), capwords(test_string))

        # Check to see cleanup string is working
        random_string = lambda a, b: "".join([chr(random.Random().randint(a, b)) for _i in range(0, 10)])
        dirty_strings = [random_string(48, 122) for _i in range(0, 10)]
        undesirables = ("a", "b+", "[0-9]", "^x")
        for dirty_string in dirty_strings:
            cleaned_string = cleanup_name_from_undesirables(dirty_string, undesirables)
            for undesirable in undesirables:
                self.assertIsNone(re.search(undesirable, cleaned_string, flags=re.I))

        # Check string similarities - 100 for identical strings, 90 or more for one character change
        # and nothing at all for a totally unidentical string
        similarity_string = random_string(65, 122)
        self.assertEqual(get_name_similarity(similarity_string, similarity_string), 100)
        self.assertGreaterEqual(get_name_similarity(similarity_string, similarity_string[:-1]), 90)
        self.assertEqual(get_name_similarity(similarity_string, random_string(48, 57)), 0)

        # Check to see most similar string gets picked out of an array of similar-looking strings, and that
        # with very dissimilar strings, there is no candidate at all
        similarity_candidates = (similarity_string[:3], similarity_string[:5], similarity_string[:9], "z" * 10)
        self.assertEqual(get_best_fuzzy_match(similarity_string, similarity_candidates), similarity_candidates[-2])
        dissimilarity_candidates = [random_string(48, 57) for _i in range(0, 10)]
        self.assertIsNone(get_best_fuzzy_match(similarity_string, dissimilarity_candidates))

    def test_models(self):
        """
        Unit tests for train, bus, station and bus stop objects
        """
        station = RailStation("Walford East", "WAL", 535630, 182141)
        # Test abbreviated name
        # Test fuzzy matching with other names
        self.assertEqual(station.get_similarity(station.name), 100)

        bus_stop = BusStop("WALFORD EAST STATION # [DLR]")
        # Sort a list and work out
        # Check clean name
        # Check normalised name
        # Check similarity

        train = Train
        # Test comparison of two trains
        # Test destination
        # Test clean destination

        tube_train = TubeTrain
        # Test undesirable text is removed
        # Test is hashable

    # Fundamental non-unit functionality tests. These need a WMT bot set up and are thus contingent on a
    # config.cfg files to test things such as a particular instance's databases, geocoder and browser
    def test_init(self):
        """
        Test to see if we can load the class in the first place
        """
        self.assertTrue(True)

    def test_browser(self):
        """
        Unit tests for WMTBrowser object
        """
        pass

    def test_database(self):
        """
        Unit tests for WMTDatabase object and to see if files exist
        """
        for name in self.geodata_table_names:
            row = self.bot.geodata.get_row("SELECT name FROM sqlite_master WHERE type='table' AND name='%s'" % name)
            self.assertIsNotNone(row, '%s table does not exist' % name)

    def test_geocoder(self):
        """
        Unit tests for Geocoder objects
        """
        pass

    def test_logger(self):
        """
        Unit tests for system logging
        """
        pass

    def test_settings(self):
        """
        Test to see if settings database does not exist
        """
        query = "SELECT name FROM sqlite_master WHERE type='table' AND name='%s_settings'" % self.bot.instance_name
        row = self.bot.twitter_client.settings.settingsdb.get_row(query)
        self.assertIsNotNone(row, 'Settings table does not exist')

    def test_twitter_client(self):
        """
        Test to see if our OAuth login details are correct
        """
        self.assertTrue(self.bot.twitter_client.api.verify_credentials())

    #
    # Tests that Tweets are in the right format
    #

    def test_politeness(self):
        """
        Test to see if we are replying to polite messagess correctly
        """
        tweet = FakeTweet(self.at_reply + 'Thank you!')
        self.assertFalse(self.bot.process_tweet(tweet))
        self.assertRegexpMatches(self.bot.check_politeness(tweet)[0], 'No problem')

    def test_mention(self):
        """
        Test to confirm we are ignoring Tweets that are just mentions and not replies
        """
        tweet = FakeTweet('Hello @%s' % self.bot.username)
        self.assertFalse(self.bot.validate_tweet(tweet))

    def test_talking_to_myself(self):
        """
        Test to confirm we are ignoring Tweets from the bot itself
        """
        tweet = FakeTweet(self.at_reply + self.test_standard_data[0][0], username=self.bot.username)
        self.assertFalse(self.bot.validate_tweet(tweet))

    def test_blank_tweet(self):
        """
        Test to confirm we are ignoring blank replies
        """
        for message in ('',
                     ' ',
                     '         '):
            tweet = FakeTweet(self.at_reply + message)
            self._test_correct_exception_produced(tweet, 'blank_%s_tweet' % self.bot.instance_name.replace('whensmy', ''))
            direct_message = FakeDirectMessage(message)
            self._test_correct_exception_produced(direct_message, 'blank_%s_tweet' % self.bot.instance_name.replace('whensmy', ''))

    #
    # Geotagging tests
    #

    def test_no_geotag(self):
        """
        Test to confirm lack of geotag handled OK
        """
        for test_data in self.test_standard_data:
            request = test_data[0]
            tweet = FakeTweet(self.at_reply + request)
            self._test_correct_exception_produced(tweet, 'no_geotag', request)
            direct_message = FakeDirectMessage(request)
            self._test_correct_exception_produced(direct_message, 'dms_not_taggable', request)

    def test_placeinfo_only(self):
        """
        Test to confirm ambiguous place information handled OK
        """
        for test_data in self.test_standard_data:
            request = test_data[0]
            tweet = FakeTweet(self.at_reply + request, place='foo')
            self._test_correct_exception_produced(tweet, 'placeinfo_only', request)

    def test_not_in_uk(self):
        """
        Test to confirm geolocations outside UK handled OK
        """
        for test_data in self.test_standard_data:
            request = test_data[0]
            tweet = FakeTweet(self.at_reply + request, (40.748433, -73.985656)) # Empire State Building, New York
            self._test_correct_exception_produced(tweet, 'not_in_uk')

    def test_not_in_london(self):
        """
        Test to confirm geolocations outside London handled OK
        """
        for test_data in self.test_standard_data:
            request = test_data[0]
            tweet = FakeTweet(self.at_reply + request, (55.948611, -3.200833)) # Edinburgh Castle, Edinburgh
            self._test_correct_exception_produced(tweet, 'not_in_london')


class WhensMyBusTestCase(WhensMyTransportTestCase):
    """
    Main Test Case for When's My Bus
    """
    #pylint: disable=R0904
    def setUp(self):
        """
        Setup test
        """
        self.bot = WhensMyBus(testing=True, silent=True)
        self.at_reply = '@%s ' % self.bot.username
        self.geodata_table_names = ('routes', )

        # Route Number, Origin Name, Origin Number, Origin Longitude, Origin Latitude, Dest Name, Dest Number, Expected Origin
        self.test_standard_data = (
                                   ('15', 'Limehouse Station', '53452', 51.5124, -0.0397, 'Poplar', '73923', 'Limehouse Station'),
                                   ('425 25 205', 'Bow Road Station', '55489',  51.52722, -0.02472, 'Mile End station', '76239', 'Bow Road Station'),
                                   )
        # Troublesome destinations & data
        self.test_nonstandard_data = (('%s from Stratford to Walthamstow', ('257',),      'Stratford Bus Station'),
                                      ('%s from Hoxton',                   ('243',),      'Hoxton Station / Geffrye Museum'),
                                      ('%s from Bow Common Lane',          ('323',),      'Bow Common Lane'),
                                      ('%s from EC1M 4PN',                 ('55',),       'St John Street'),
                                      ('%s from Mile End',                 ('d6', 'd7'),  'Mile End \w+'),
                                     )

    def _test_correct_successes(self, result, routes_specified, expected_origin, destination_not_specified=True):
        """
        Generic test to confirm message is being produced correctly
        """
        # No TfL garbage please, and no all-caps either
        for unwanted in ('<>', '#', '\[DLR\]', '>T<'):
            self.assertNotRegexpMatches(result, unwanted)
        self.assertNotEqual(result, result.upper())

        # Should say one of our route numbers, expected origin and a time
        route_regex = "^(%s)" % '|'.join(routes_specified.upper().replace(',', '').split(' '))
        self.assertRegexpMatches(result, route_regex)
        self.assertRegexpMatches(result, '(%s to .* [0-9]{4}|None shown going)' % expected_origin)

        # We should get two results and hence a semi-colon separating them, if this is not from a specific stop
        if destination_not_specified:
            self.assertRegexpMatches(result, ';')
        else:
            self.assertNotRegexpMatches(result, ';')

        print result

    #
    # Bus-specific tests
    #

    def test_no_bus_number(self):
        """
        Test to confirm we are ignoring Tweets that do not have bus numbers in them
        """
        message = 'Thanks!'
        tweet = FakeTweet(self.at_reply + message)
        self.assertFalse(self.bot.process_tweet(tweet))
        direct_message = FakeDirectMessage(message)
        self.assertFalse(self.bot.process_tweet(direct_message))

    def test_nonexistent_bus(self):
        """
        Test to confirm non-existent buses handled OK
        """
        for message in ('218 from Trafalgar Square', '   218 from Trafalgar Square', '   218   from Trafalgar Square #hashtag'):
            tweet = FakeTweet(self.at_reply + message)
            self._test_correct_exception_produced(tweet, 'nonexistent_bus', '218')
            direct_message = FakeDirectMessage(message)
            self._test_correct_exception_produced(direct_message, 'nonexistent_bus', '218')

    #
    # Stop-related errors
    #

    def test_bad_stop_id(self):
        """
        Test to confirm bad stop IDs handled OK
        """
        message = '15 from 00000'
        tweet = FakeTweet(self.at_reply + message)
        self._test_correct_exception_produced(tweet, 'bad_stop_id', '00000') # Stop IDs begin at 47000
        direct_message = FakeDirectMessage(message)
        self._test_correct_exception_produced(direct_message, 'bad_stop_id', '00000') # Stop IDs begin at 47000

    def test_stop_id_mismatch(self):
        """
        Test to confirm when route and stop do not match up is handled OK
        """
        message = '15 from 52240'
        tweet = FakeTweet(self.at_reply + message)
        self._test_correct_exception_produced(tweet, 'stop_id_not_found', '15', '52240') # The 15 does not go from Canary Wharf
        direct_message = FakeDirectMessage(message)
        self._test_correct_exception_produced(direct_message, 'stop_id_not_found', '15', '52240')

    def test_stop_name_nonsense(self):
        """
        Test to confirm when route and stop do not match up is handled OK
        """
        message = '15 from eucg;$78'
        tweet = FakeTweet(self.at_reply + message)
        self._test_correct_exception_produced(tweet, 'stop_name_not_found', '15', 'eucg;$78')

    def test_standard_messages(self):
        """
        Generic test for standard-issue messages
        """
        #pylint: disable=W0612
        for (route, origin_name, origin_id, lat, lon, destination_name, destination_id, expected_origin) in self.test_standard_data:

            # C-string format helper
            test_variables = dict([(name, eval(name)) for name in ('route', 'origin_name', 'origin_id', 'destination_name', 'destination_id')])

            # 5 types of origin (geotag, ID, name, ID without 'from', name without 'from') and 3 types of destination (none, ID, name)
            from_fragments = [value % test_variables for value in ("", " from %(origin_name)s",    " from %(origin_id)s", " %(origin_name)s", " %(origin_id)s")]
            to_fragments =   [value % test_variables for value in ("", " to %(destination_name)s", " to %(destination_id)s")]

            for from_fragment in from_fragments:
                for to_fragment in to_fragments:
                    message = (self.at_reply + route + from_fragment + to_fragment)
                    print message
                    if not from_fragment:
                        tweet = FakeTweet(message, (lat, lon))
                    else:
                        tweet = FakeTweet(message)

                    results = self.bot.process_tweet(tweet)
                    for result in results:
                        self._test_correct_successes(result, route, expected_origin, (from_fragment.find(origin_id) == -1) and not to_fragment)

    def test_multiple_routes(self):
        """
        Test multiple routes from different bus stops in the same area (unlike the above function which
        tests multiple routes going in the same direction, from the same stop(s)
        """
        test_data = (("277 15", (51.511694, -0.030286), "(East India Dock Road|Limehouse Town Hall)"),)

        for (route, position, expected_result_regex) in test_data:
            tweet = FakeTweet(self.at_reply + route, position)
            results = self.bot.process_tweet(tweet)
            for result in results:
                self._test_correct_successes(result, route, expected_result_regex, True)

    def test_nonstandard_messages(self):
        """
        Test to confirm a message that can be troublesome comes out OK
        """
        for (text, routes, stop_name) in self.test_nonstandard_data:
            for route in routes:
                message = text % route
                tweet = FakeTweet(self.at_reply + message)
                results = self.bot.process_tweet(tweet)
                for result in results:
                    self._test_correct_successes(result, route, stop_name, (message.find(' to ') == -1))

class WhensMyTubeTestCase(WhensMyTransportTestCase):
    """
    Main Test Case for When's My Tube
    """
    def setUp(self):
        """
        Setup test
        """
        self.bot = WhensMyTube(testing=True, silent=True)
        self.at_reply = '@%s ' % self.bot.username
        self.geodata_table_names = ('locations', )

        self.test_standard_data = (
                                   ('Central', "White City", 51.5121, -0.2246, "Ruislip Gardens", "White City"),
                                   ('Central', 'Epping', 51.693, 0.1138, "Bank", 'Epping'), # Second-most northern after Chesham
                                   ('District', 'Upminster', 51.559, 0.2511, "Tower Hill", 'Upminster'), # Most eastern
                                   ('Northern', 'Morden', 51.402222, -0.195, "Bank", 'Morden'), # Most southern
                                   ('Metropolitan', 'Amersham', 51.674108, -0.6074, "Baker Street", 'Amersham'), # Second-most western after Chesham
                                   ('District', "Earl's Court", 51.4913, -0.1947, "Edgware Road", "Earls Ct"),
                                   ('Piccadilly', "Acton Town", 51.5028, -0.28, "Arsenal", "Acton Town"),
                                   ('Northern', "Camden Town", 51.5394, -0.1427, "Morden", "Camden Town"),
                                   ('Circle', "Edgware Road", 51.52, -0.167778, "Moorgate", "Edgware Rd"),
                                   ('Waterloo & City', "Waterloo", 51.5031, -0.1132, "Bank", "Waterloo"),
                                   ('Victoria', "Victoria", 51.4966, -0.1448, "Walthamstow", "Victoria"),
                                  )
        self.test_nonstandard_data = ()

    def _test_correct_successes(self, result, routes_specified, expected_origin, destination_not_specified=True):
        """
        Generic test to confirm message is being produced correctly
        """
        self.assertNotEqual(result, result.upper())
        self.assertRegexpMatches(result, r"(%s to .* [0-9]{4}|There aren't any %s Line trains)" % (expected_origin, routes_specified))
        if destination_not_specified:
            pass # TODO Tests for when a destination is specified
        print result

    def test_bad_line_name(self):
        """
        Test to confirm bad line names are handled OK
        """
        message = 'Xrongwoihrwg line from Oxford Circus'
        tweet = FakeTweet(self.at_reply + message)
        self._test_correct_exception_produced(tweet, 'nonexistent_line', 'Xrongwoihrwg')

    def test_missing_station_data(self):
        """
        Test to confirm certain stations which have no data are correctly reported
        """
        message = 'Metropolitan Line from Preston Road'
        tweet = FakeTweet(self.at_reply + message)
        self._test_correct_exception_produced(tweet, 'rail_station_not_in_system', 'Preston Road')

    def test_station_line_mismatch(self):
        """
        Test to confirm stations on the wrong lines are correctly error reported
        """
        message = 'District Line from Stratford'
        tweet = FakeTweet(self.at_reply + message)
        self._test_correct_exception_produced(tweet, 'rail_station_name_not_found', 'Stratford', 'District Line')

    def test_standard_messages(self):
        """
        Generic test for standard-issue messages
        """
        #pylint: disable=W0612
        for (line, origin_name, lat, lon, destination_name, expected_origin) in self.test_standard_data:

            # C-string format helper
            test_variables = dict([(name, eval(name)) for name in ('line', 'origin_name', 'destination_name', 'line')])

            # 3 types of origin (geotag, name, name without 'from') and 2 types of destination (none, name)
            from_fragments = [value % test_variables for value in ("", " from %(origin_name)s", " %(origin_name)s")]
            to_fragments =   [value % test_variables for value in ("", " to %(destination_name)s")]
            line_fragments = [value % test_variables for value in ("%(line)s", "%(line)s Line")]

            for from_fragment in from_fragments:
                for to_fragment in to_fragments:
                    for line_fragment in line_fragments:
                        message = (self.at_reply + line_fragment + from_fragment + to_fragment)

                        # FIXME We have to skip any request like "Victoria Victoria" or "Waterloo & City Waterloo" as parser can't tell the difference
                        if from_fragment and line_fragment.find(from_fragment.strip()) > -1:
                            continue

                        if not from_fragment:
                            tweet = FakeTweet(message, (lat, lon))
                        else:
                            tweet = FakeTweet(message)

                        results = self.bot.process_tweet(tweet)
                        for result in results:
                            self._test_correct_successes(result, line, expected_origin, not to_fragment)

class WhensMyDLRTestCase(WhensMyTransportTestCase):
    """
    Main Test Case for When's My DLR
    """
    def setUp(self):
        """
        Setup test
        """
        self.bot = WhensMyDLR(testing=True, silent=True)
        self.at_reply = '@%s ' % self.bot.username
        self.geodata_table_names = ('locations', )

        self.test_standard_data = (
                                   ('DLR', 'Bank', 51.513, -0.088, 'Canary Wharf', 'Bank'),
                                   ('DLR', 'Tower Gateway', 51.5104, -0.0746, 'Beckton', 'Tower Gateway'),
                                   ('DLR', 'Limehouse', 51.5124, -0.0397, 'Canary Wharf', 'Limehouse'),
                                   ('DLR', 'Heron Quay', 51.5028, -0.0213, 'Canary Wharf', 'Heron Quays'),
                                   ('DLR', 'Lewisham', 51.4653, -0.0133, 'Canary Wharf', 'Lewisham'),
                                   ('DLR', 'W India Quay', 51.506667, -0.022222, 'Canary Wharf', 'W India Quay'),
                                   ('DLR', 'Canning Town', 51.514, 0.0083, 'Westferry', 'Canning Town'),
                                   ('DLR', 'Poplar', 51.5077, -0.0174, 'Westferry', 'Poplar'),
                                   ('DLR', 'Limehouse', 51.5124, -0.0397, 'Canary Wharf', 'Limehouse'),
                                   ('DLR', 'Heron Quay', 51.5028, -0.0213, 'Canary Wharf', 'Heron Quays'),
                                  )
        self.test_nonstandard_data = ()

    def _test_correct_successes(self, result, routes_specified, expected_origin, destination_not_specified=True):
        """
        Generic test to confirm message is being produced correctly
        """
        self.assertNotEqual(result, result.upper())
        self.assertRegexpMatches(result, r"(%s to .* ([0-9]{1,4})|There aren't any %s trains)" % (expected_origin, routes_specified))
        if destination_not_specified:
            pass # TODO Tests for when a destination is specified
        print result

    def test_bad_station_name(self):
        """
        Test to confirm stations that don't exist on the DLR are correctly handled
        """
        message = 'DLR from Ealing Broadway'
        tweet = FakeTweet(self.at_reply + message)
        self._test_correct_exception_produced(tweet, 'rail_station_name_not_found', 'Ealing Broadway', 'DLR')

    def test_standard_messages(self):
        """
        Generic test for standard-issue messages
        """
        #pylint: disable=W0612
        for (line, origin_name, lat, lon, destination_name, expected_origin) in self.test_standard_data:

            # C-string format helper
            test_variables = dict([(name, eval(name)) for name in ('origin_name', 'destination_name', 'line')])

            # 3 types of origin (geotag, name, name without 'from') and 2 types of destination (none, name)
            from_fragments = [value % test_variables for value in ("", " from %(origin_name)s", " %(origin_name)s")]
            to_fragments =   [value % test_variables for value in ("", " to %(destination_name)s")]
            line_fragments = [value % test_variables for value in ("", "%(line)s",)]

            for from_fragment in from_fragments:
                for to_fragment in to_fragments:
                    for line_fragment in line_fragments:
                        message = (self.at_reply + line_fragment + from_fragment + to_fragment)
                        if not from_fragment:
                            tweet = FakeTweet(message, (lat, lon))
                        else:
                            tweet = FakeTweet(message)

                        results = self.bot.process_tweet(tweet)
                        for result in results:
                            self._test_correct_successes(result, 'DLR', expected_origin, not to_fragment)

def run_tests():
    """
    Run a suite of tests for When's My Transport
    """
    parser = argparse.ArgumentParser(description="Unit testing for When's My Transport?")
    parser.add_argument("test_case_name", action="store", default="", help="Name of the class to test (e.g. WhensMyBus, WhensMyTube)")
    parser.add_argument("--dologin", dest="dologin", action="store_true", default=False, help="Force check of databases and logins")

    test_case_name = parser.parse_args().test_case_name


    # Init tests (same for all)
    init = ('init', 'databases_exist', 'oauth_works')
    libraries = ('geo', 'listutils', 'stringutils', )

    # Common errors for all
    format_errors = ('politeness', 'talking_to_myself', 'mention', 'blank_tweet',)
    geotag_errors = ('no_geotag', 'placeinfo_only', 'not_in_uk', 'not_in_london',)

    if test_case_name == "WhensMyBus":
        bus_errors = ('no_bus_number', 'nonexistent_bus',)
        stop_errors = ('bad_stop_id', 'stop_id_mismatch', 'stop_name_nonsense',)
        failures = format_errors + geotag_errors + bus_errors + stop_errors
        successes = ('nonstandard_messages', 'standard_messages', 'multiple_routes',)
    elif test_case_name == "WhensMyTube":
        tube_errors = ('bad_line_name',)
        station_errors = ('missing_station_data', 'station_line_mismatch')
        failures = format_errors + geotag_errors + tube_errors + station_errors
        successes = ('standard_messages',)
    elif test_case_name == "WhensMyDLR":
        dlr_errors = ()
        station_errors = ('bad_station_name',)
        failures = format_errors[:-1] + geotag_errors + dlr_errors + station_errors  # Exclude blank tweet test
        successes = ('standard_messages',)
    else:
        print "Error - %s is not a valid Test Case Name" % test_case_name
        sys.exit(1)

    if parser.parse_args().dologin:
        test_names = libraries # init  + failures + successes FIXME
    else:
        test_names = failures + successes

    suite = unittest.TestSuite(map(eval(test_case_name + 'TestCase'), ['test_%s' % t for t in test_names]))
    runner = unittest.TextTestRunner(verbosity=1, failfast=1, buffer=True)
    runner.run(suite)

if __name__ == "__main__":
    run_tests()

