#!/usr/bin/env python
# -*- coding: utf-8 -*-
#pylint: disable=C0103,W0142,R0904,W0141,R0915,C0302
"""
A set of unit tests for When's My Train?

IMPORTANT: These unit tests require Python 2.7, although When's My Train will happily run in Python 2.6
"""
from tests.generic_tests import FakeTweet, WhensMyTransportTestCase
import sys
import time
import unittest
from whensmytrain import WhensMyTrain
from lib.exceptions import WhensMyTransportException


class WhensMyTubeTestCase(WhensMyTransportTestCase):
    """
    Main Test Case for When's My Tube
    """
    @classmethod
    def setupClass(cls, testing_level):
        """
        Setup class with expensive-to-load objects
        """
        try:
            cls.bot = WhensMyTrain("whensmytube", testing=testing_level)
        except RuntimeError as exc:
            print exc
            cls.tearDown()
            cls.fail("Sorry, a RuntimeError was encountered")

        cls.at_reply = '@%s ' % cls.bot.username
        cls.geodata_table_names = ('locations', )

    def setUp(self):
        """
        Setup test
        """
        # Regular test data
        #
        # Line, requested stop, latitude, longitude, destination, direction, correct stop name, unwanted destination (if destination or direction specified)
        self.standard_test_data = (
           ('District',             "Earl's Court",  51.4913, -0.1947, "Edgware Road", "Eastbound",   "Earls Ct",      'Wimbledon'),
           ('Victoria',             "Victoria",      51.4966, -0.1448, "Walthamstow",  "Northbound",  "Victoria",      'Brixton'),
           ('Waterloo & City',      "Waterloo",      51.5031, -0.1132, "Bank",         "Eastbound",   "Waterloo",      'Moorgate'),
           ('DLR',                  'Poplar',        51.5077, -0.0174, 'All Saints',   "Northbound",  'Poplar',        'Lewisham'),
           ('Hammersmith and City', "Liverpool St",  51.5186, -0.0813, "Plaistow",     "Eastbound",   "Liverpool St",  'Hammersmith'),
        )
        self.nonstandard_test_data = (
            # Hainault Loop and Northern Line handled correctly
            ("Central Line from White City to Redbridge",
                ("Hainault via Newbury Pk", "Woodford via Hainault"),
                ("Epping [0-9]{4}",)),
            ("Northern Line from Camden Town to Kennington",
                ("via Bank", "via Charing X"),
                ("High Barnet [0-9]{4}",)),
            # Directional sussing at a tricky station
            ("Circle Line from Edgware Road to Moorgate",
                ("Eastbound Train",),
                ("Hammersmith [0-9]{4}",)),
            # Handle ably when no line is specified but only one line serves the origin
            ('Arsenal',
                ('Cockfosters', 'Heathrow'),
                (str(WhensMyTransportException('no_line_specified', 'Arsenal')),)),
            # Handle ably when no line is specified but only one line serves both origin and destination
            ("Earl's Court to Plaistow",
                ('Upminster',),
                (str(WhensMyTransportException('no_line_specified_to', "Earl's Court", "Plaistow")),)),
            # Handle ably when no line is specified, there exists more than one line to get there, but we pick fastest
            ("Stockwell to Euston",
                ('Walthamstow Ctrl',),
                (str(WhensMyTransportException('no_line_specified_to', "Stockwell", "Euston")),)),            
        )

    def _test_correct_successes(self, tweet, _routes_specified, expected_origin, destination_to_avoid=''):
        """
        Generic test to confirm Tube Tweet is being processed correctly
        """
        print tweet.text
        t1 = time.time()
        results = self.bot.process_tweet(tweet)
        self.assertTrue(results)
        t2 = time.time()
        self.assertTrue(results)
        for result in results:
            print result
            self.assertTrue(result)
            self.assertNotEqual(result, result.upper())
            self.assertRegexpMatches(result, r"%s to .* [0-9]{4}" % expected_origin)
            if destination_to_avoid:
                self.assertNotRegexpMatches(result, destination_to_avoid)
        print 'Processing of Tweet took %0.3f ms\r\n' % ((t2 - t1) * 1000.0,)

    #
    # Core functionality tests
    #

    def test_location(self):
        """
        Unit tests for WMTLocation object and the Tube database
        """
        # Test station-finding works
        self.assertEqual(self.bot.geodata.find_closest((51.529444, -0.126944), {}).code, "KXX")
        self.assertEqual(self.bot.geodata.find_closest((51.529444, -0.126944), {'line': 'M'}).code, "KXX")
        self.assertEqual(self.bot.geodata.find_fuzzy_match("Kings Cross", {}).code, "KXX")
        self.assertEqual(self.bot.geodata.find_fuzzy_match("Kings Cross", {'line': 'M'}).code, "KXX")

        # Test route-tracing works as expected
        stockwell = self.bot.geodata.find_fuzzy_match("Stockwell", {})
        bank = self.bot.geodata.find_fuzzy_match("Bank", {})
        euston = self.bot.geodata.find_fuzzy_match("Euston", {})
        self.assertEqual(sorted(self.bot.geodata.get_lines_serving(stockwell)), ['N', 'V'])
        self.assertEqual(sorted(self.bot.geodata.get_lines_serving(bank)), ['C', 'N', 'W'])
        self.assertEqual(self.bot.geodata.length_of_route(stockwell, euston), 18)
        self.assertEqual(self.bot.geodata.length_of_route(stockwell, euston, 'N'), 20)
        self.assertIn(('Oxford Circus', '', 'Victoria'), self.bot.geodata.describe_route(stockwell, euston))
        self.assertIn(('Charing Cross', '', 'Northern'), self.bot.geodata.describe_route(stockwell, euston, "N"))
        self.assertIn(('Bank', '', 'Northern'), self.bot.geodata.describe_route(stockwell, euston, "N", bank))

        # Test route-testing works as expected
        west_ruislip = self.bot.geodata.find_fuzzy_match("West Ruislip", {})
        hainault = self.bot.geodata.find_fuzzy_match("Hainault", {})
        roding_valley = self.bot.geodata.find_fuzzy_match("Roding Valley", {})
        wanstead = self.bot.geodata.find_fuzzy_match("Wanstead", {})
        snaresbrook = self.bot.geodata.find_fuzzy_match("Snaresbrook", {})
        heathrow123 = self.bot.geodata.find_fuzzy_match("Heathrow Terminals 1, 2, 3", {})
        heathrow4 = self.bot.geodata.find_fuzzy_match("Heathrow Terminal 4", {})
        self.assertTrue(self.bot.geodata.direct_route_exists(west_ruislip, west_ruislip, "C"))
        self.assertTrue(self.bot.geodata.direct_route_exists(west_ruislip, hainault, "C"))
        self.assertTrue(self.bot.geodata.direct_route_exists(west_ruislip, roding_valley, "C", via=hainault))
        self.assertTrue(self.bot.geodata.direct_route_exists(west_ruislip, roding_valley, "C", via=hainault, must_stop_at=wanstead))
        self.assertFalse(self.bot.geodata.direct_route_exists(snaresbrook, wanstead, "C"))
        self.assertFalse(self.bot.geodata.direct_route_exists(heathrow123, heathrow4, "P"))
        self.assertFalse(self.bot.geodata.direct_route_exists(snaresbrook, heathrow123, "All"))
        self.assertFalse(self.bot.geodata.direct_route_exists(snaresbrook, heathrow123, "C"))

        # Test direction-finding works as expected
        morden = self.bot.geodata.find_fuzzy_match("Morden", {})
        high_barnet = self.bot.geodata.find_fuzzy_match("High Barnet", {})
        self.assertTrue(self.bot.geodata.is_correct_direction("Eastbound", west_ruislip, hainault, 'C'))
        self.assertTrue(self.bot.geodata.is_correct_direction("Westbound", hainault, west_ruislip, 'C'))
        self.assertTrue(self.bot.geodata.is_correct_direction("Northbound", morden, high_barnet, 'N'))
        self.assertTrue(self.bot.geodata.is_correct_direction("Southbound", hainault, wanstead, 'C'))
        self.assertFalse(self.bot.geodata.is_correct_direction("Southbound", snaresbrook, wanstead, 'C'))
        self.assertFalse(self.bot.geodata.is_correct_direction("Southbound", morden, high_barnet, 'N'))

        # DLR Location tests
        self.assertEqual(self.bot.geodata.find_closest((51.5124, -0.0397), {}).code, "lim")
        self.assertEqual(self.bot.geodata.find_closest((51.5124, -0.0397), {'line': 'DLR'}).code, "lim")
        self.assertEqual(self.bot.geodata.find_fuzzy_match("Limehouse", {}).code, "lim")
        self.assertEqual(self.bot.geodata.find_fuzzy_match("Limehouse", {'line': 'DLR'}).code, "lim")
        self.assertEqual(self.bot.geodata.find_fuzzy_match("Stratford Int", {}).code, "sti")
        self.assertEqual(self.bot.geodata.find_fuzzy_match("W'wich Arsenal", {}).code, "woa")

        stratford = self.bot.geodata.find_fuzzy_match("Stratford", {})
        beckton = self.bot.geodata.find_fuzzy_match("Beckton", {})
        poplar = self.bot.geodata.find_fuzzy_match("Poplar", {})
        self.assertIn(('West Ham', '', 'DLR'), self.bot.geodata.describe_route(stratford, beckton))
        self.assertIn(('Blackwall', '', 'DLR'), self.bot.geodata.describe_route(stratford, beckton, "DLR", poplar))

        limehouse = self.bot.geodata.find_fuzzy_match("Limehouse", {})
        all_saints = self.bot.geodata.find_fuzzy_match("All Saints", {})
        self.assertTrue(self.bot.geodata.direct_route_exists(limehouse, beckton, "DLR"))
        self.assertFalse(self.bot.geodata.direct_route_exists(limehouse, all_saints, "DLR"))
        self.assertTrue(self.bot.geodata.is_correct_direction("Eastbound", limehouse, beckton, "DLR"))
        self.assertFalse(self.bot.geodata.is_correct_direction("Eastbound", beckton, limehouse, "DLR"))

    def test_textparser(self):
        """
        Tests for the natural language parser
        """
        (line_name, origin, destination, direction) = ('Victoria', 'Sloane Square', 'Upminster', 'Eastbound')
        routes = [line_name]
        self.assertEqual(self.bot.parser.parse_message(""),                                                     (None, None, None, None))
        for route in (line_name, '%s Line' % line_name):
            self.assertEqual(self.bot.parser.parse_message("%s" % (route,)),                                    (routes, None, None, None))
            self.assertEqual(self.bot.parser.parse_message("%s %s" % (route, origin)),                          (routes, origin, None, None))
            self.assertEqual(self.bot.parser.parse_message("%s %s to %s" % (route, origin, destination)),       (routes, origin, destination, None))
            self.assertEqual(self.bot.parser.parse_message("%s from %s" % (route, origin)),                     (routes, origin, None, None))
            self.assertEqual(self.bot.parser.parse_message("%s from %s to %s" % (route, origin, destination)),  (routes, origin, destination, None))
            self.assertEqual(self.bot.parser.parse_message("%s to %s" % (route, destination)),                  (routes, None, destination, None))
            self.assertEqual(self.bot.parser.parse_message("%s to %s from %s" % (route, destination, origin)),  (routes, origin, destination, None))
            self.assertEqual(self.bot.parser.parse_message("%s %s" % (route, direction)),                       (routes, None, None, direction))
            self.assertEqual(self.bot.parser.parse_message("%s %s %s" % (route, origin, direction)),            (routes, origin, None, direction))
            self.assertEqual(self.bot.parser.parse_message("%s from %s %s" % (route, origin, direction)),       (routes, origin, None, direction))
            self.assertEqual(self.bot.parser.parse_message("%s %s %s" % (route, direction, origin)),            (routes, origin, None, direction))
            self.assertEqual(self.bot.parser.parse_message("%s %s from %s" % (route, direction, origin)),       (routes, origin, None, direction))

    #
    # Request-based tests
    #

    def test_bad_line_name(self):
        """
        Test to confirm bad line names are handled OK
        """
        message = 'Xrongwoihrwg line from Oxford Circus'
        tweet = FakeTweet(self.at_reply + message)
        self._test_correct_exception_produced(tweet, 'nonexistent_line', 'Xrongwoihrwg')

    def test_bad_routing(self):
        """
        Test to confirm routes that are not possible on the DLR are correctly handled
        """
        message = 'DLR from Lewisham to Woolwich Arsenal'
        tweet = FakeTweet(self.at_reply + message)
        self._test_correct_exception_produced(tweet, 'no_direct_route', 'Lewisham', 'Woolwich Arsenal', 'DLR')

    def test_missing_station_data(self):
        """
        Test to confirm certain stations which have no data are correctly reported
        """
        message = 'Metropolitan Line from Preston Road'
        tweet = FakeTweet(self.at_reply + message)
        self._test_correct_exception_produced(tweet, 'rail_station_not_in_system', 'Preston Road')

    def test_station_line_mismatch(self):
        """
        Test to confirm stations on the wrong lines, or not on the system at all, are correctly error reported
        """
        message = 'District Line from Stratford'
        tweet = FakeTweet(self.at_reply + message)
        self._test_correct_exception_produced(tweet, 'rail_station_name_not_found', 'Stratford', 'District Line')
        message = 'DLR from Ealing Broadway'
        tweet = FakeTweet(self.at_reply + message)
        self._test_correct_exception_produced(tweet, 'rail_station_name_not_found', 'Ealing Broadway', 'DLR')
        message = 'Wxitythr Park'
        tweet = FakeTweet(self.at_reply + message)
        network_name = self.bot.default_requested_route  # Either 'Tube' or 'DLR'
        self._test_correct_exception_produced(tweet, 'rail_station_name_not_found', 'Wxitythr Park', network_name)

    @unittest.skipIf('--live-data' in sys.argv, "No trains unit test will fail on live data")
    def test_no_trains(self):
        """
        Test for when there are no trains at a station
        """
        # Handle when there are no trains from a station
        message = 'Waterloo & City Line from Bank'
        tweet = FakeTweet(self.at_reply + message)
        self._test_correct_exception_produced(tweet, 'no_trains_shown', 'Waterloo & City Line', 'Bank')
        # Handle when there are no trains to a particular destination
        message = 'DLR from Lewisham to Poplar'
        tweet = FakeTweet(self.at_reply + message)
        self._test_correct_exception_produced(tweet, 'no_trains_shown_to', 'DLR', 'Lewisham', 'Poplar')
        # Handle when there are no trains in a particular direction
        message = 'Central Line from Fairlop Westbound'
        tweet = FakeTweet(self.at_reply + message)
        self._test_correct_exception_produced(tweet, 'no_trains_shown_in_direction', 'Westbound', 'Central Line', 'Fairlop')

    def test_no_line_specified(self):
        """
        Test for when no line is specified and it is impossible to deduce what the line is
        """
        # No direct line from Mansion House to Mornington Crescent
        message = 'Mansion House to Mornington Crescent'
        tweet = FakeTweet(self.at_reply + message)
        self._test_correct_exception_produced(tweet, 'no_direct_route', 'Mansion House', 'Mornington Crescent', 'Tube')
        # Leicester Square has two lines, could be either
        message = 'Leicester Square'
        tweet = FakeTweet(self.at_reply + message)
        self._test_correct_exception_produced(tweet, 'no_line_specified', 'Leicester Square')

    def test_known_problems(self):
        """
        Test known problematic inputs
        """
        # TODO Ideally, this function should be blank
        # District line from Victoria, or District & Victoria lines?
        message = 'District Victoria'
        tweet = FakeTweet(self.at_reply + message)
        self._test_correct_exception_produced(tweet, 'nonexistent_line', message)
        # Not sure if "Waterloo to Bank" or "Waterloo & City Line to Bank"
        message = 'Waterloo to Bank'
        tweet = FakeTweet(self.at_reply + message)
        self._test_correct_exception_produced(tweet, 'no_geotag', message)

    def test_standard_messages(self):
        """
        Generic test for standard-issue messages
        """
        #pylint: disable=W0612
        for (line, origin_name, lat, lon, destination_name, direction, expected_origin, destination_to_avoid) in self.standard_test_data:

            # C-string format helper
            test_variables = dict([(name, eval(name)) for name in ('line', 'origin_name', 'destination_name', 'line', 'direction')])

            # 2 types of origin (geotag, name) and 3 types of destination (none, name)
            from_fragments = [value % test_variables for value in ("", " %(origin_name)s", " from %(origin_name)s")]
            to_fragments = [value % test_variables for value in ("", " to %(destination_name)s", " %(direction)s")]
            # DLR allows blank Tweets as standard
            if self.bot.username == 'whensmydlr' and line == 'DLR':
                line_fragments = [value % test_variables for value in ("%(line)s", "")]
            elif line != 'DLR':
                line_fragments = [value % test_variables for value in ("%(line)s", ("%(line)s Line"))]
            else:
                line_fragments = [value % test_variables for value in ("%(line)s",)]

            for from_fragment in from_fragments:
                for to_fragment in to_fragments:
                    for line_fragment in line_fragments:
                        # There are some cases which cannot be used, e.g. "Victoria Victoria"
                        if line_fragment == from_fragment[1:]:
                            continue
                        messages = [(self.at_reply + line_fragment + from_fragment + to_fragment)]
                        # If we have a from in this, we can also put to first. from second
                        if from_fragment.startswith(" from"):
                            messages.append((self.at_reply + line_fragment + to_fragment + from_fragment))
                        for message in messages:
                            if not from_fragment:
                                tweet = FakeTweet(message, (lat, lon))
                            else:
                                tweet = FakeTweet(message)
                            self._test_correct_successes(tweet, line, expected_origin, to_fragment and destination_to_avoid)


class WhensMyDLRTestCase(WhensMyTubeTestCase):
    """
    A sub-test Case for When's My DLR
    """
    @classmethod
    def setupClass(cls, testing_level):
        """
        Setup class with expensive-to-load objects
        """
        try:
            cls.bot = WhensMyTrain("whensmydlr", testing=testing_level)
        except RuntimeError as exc:
            print exc
            cls.tearDown()
            cls.fail("Sorry, a RuntimeError was encountered")

        cls.at_reply = '@%s ' % cls.bot.username
        cls.geodata_table_names = ('locations', )

    def setUp(self):
        """
        Setup test
        """
        WhensMyTubeTestCase.setUp(self)
        self.nonstandard_test_data = (
            # Handle when there are no trains
            ('DLR from Lewisham to Poplar',
                ('Sorry! There are no DLR trains',),
                ("Lewisham [0-9]{4}",)),
        )

    #
    # Core functionality tests
    #

    def test_textparser(self):
        """
        Tests for the natural language parser
        """
        for route in ('', 'DLR'):
            (origin, destination, direction) = ('Westferry', 'All Saints', "Northbound")
            routes = route and [route] or None
            self.assertEqual(self.bot.parser.parse_message(""),                                                 (None, None, None, None))
            self.assertEqual(self.bot.parser.parse_message("%s" % route),                                       (routes, None, None, None))
            self.assertEqual(self.bot.parser.parse_message("%s %s" % (route, origin)),                          (routes, origin, None, None))
            self.assertEqual(self.bot.parser.parse_message("%s %s to %s" % (route, origin, destination)),       (routes, origin, destination, None))
            self.assertEqual(self.bot.parser.parse_message("%s from %s" % (route, origin)),                     (routes, origin, None, None))
            self.assertEqual(self.bot.parser.parse_message("%s from %s to %s" % (route, origin, destination)),  (routes, origin, destination, None))
            self.assertEqual(self.bot.parser.parse_message("%s to %s" % (route, destination)),                  (routes, None, destination, None))
            self.assertEqual(self.bot.parser.parse_message("%s to %s from %s" % (route, destination, origin)),  (routes, origin, destination, None))
            self.assertEqual(self.bot.parser.parse_message("%s %s" % (route, direction)),                       (routes, None, None, direction))
            self.assertEqual(self.bot.parser.parse_message("%s %s %s" % (route, origin, direction)),            (routes, origin, None, direction))
            self.assertEqual(self.bot.parser.parse_message("%s from %s %s" % (route, origin, direction)),       (routes, origin, None, direction))
            self.assertEqual(self.bot.parser.parse_message("%s %s %s" % (route, direction, origin)),            (routes, origin, None, direction))
            self.assertEqual(self.bot.parser.parse_message("%s %s from %s" % (route, direction, origin)),       (routes, origin, None, direction))

    #
    # Request-based tests
    #

    def test_blank_tweet(self):
        """
        Override blank Tweet test as this is not needed
        """
        return

    def test_no_line_specified(self):
        """
        Override No Line Specified as this is not needed for DLR
        """
        return

    def test_known_problems(self):
        """
        No known problems specific to DLR so override with a return
        """
        return

tube_errors = ('bad_line_name',)
station_errors = ('bad_routing', 'missing_station_data', 'station_line_mismatch', 'no_trains', 'no_line_specified', 'known_problems')
tube_successes = ('nonstandard_messages', 'standard_messages',)
