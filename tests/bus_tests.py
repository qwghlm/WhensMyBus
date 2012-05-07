#!/usr/bin/env python
# -*- coding: utf-8 -*-
#pylint: disable=C0103,W0142,R0904,W0141,R0915,C0302
"""
A set of unit tests for When's My Bus?

IMPORTANT: These unit tests require Python 2.7, although When's My Bus will happily run in Python 2.6
"""
import time
from tests.generic_tests import WhensMyTransportTestCase, FakeTweet, FakeDirectMessage
from whensmybus import WhensMyBus


class WhensMyBusTestCase(WhensMyTransportTestCase):
    """
    Main Test Case for When's My Bus
    """
    #pylint: disable=R0904
    def setUp(self):
        """
        Setup test
        """
        try:
            self.bot = WhensMyBus(testing=self.testing_level)
        except RuntimeError as exc:
            print exc
            self.tearDown()
            self.fail("Sorry, a RuntimeError was encountered")

        if not self.bot.geocoder:
            self.fail("Sorry, this needs a geocoder in order to validate tests properly")

        self.at_reply = '@%s ' % self.bot.username
        self.geodata_table_names = ('locations', )

        # Route Number, Origin Name, Origin Number, Origin Longitude, Origin Latitude, Dest Name, Dest Number, Expected Origin, Unwanted Destination
        self.standard_test_data = (
            ('15',         'Limehouse Station', '53452', 51.5124, -0.0397, 'Poplar',           '73923', 'Limehouse Station', 'Regent Street'),
            ('425 25 205', 'Bow Road Station',  '55489', 51.5272, -0.0247, 'Mile End station', '76239', 'Bow Road Station',  '(Bow Church|Ilford|Stratford)'),
        )
        # Troublesome destinations & data
        self.nonstandard_test_data = (
            # Hoxton is mistaken as Brixton
            ('243 from Hoxton',
                ('Hoxton Station / Geffrye Museum',),
                ('Brixton',)),
            # Postcodes should be doable with a geocoder
            ('55 from EC1M 4PN',
                ('St John Street',),
                ()),
            # 103 has more than 2 runs, check we delete the empty one
            ('103 from Romford Station',
                ('Romford Station',),
                ('None shown',)),
            # Ignore use of the definite article
            ('the 15 from st pauls churchyard',
                ("St Paul's Churchyard",),
                ('None shown',)),
            # Ignore unknown words like directions before the "from"
            ('243 north bound from Hoxton Station please',
                ("Hoxton Station",),
                ('None shown',)),
        )

    def _test_correct_successes(self, tweet, routes_specified, expected_origin, destination_to_avoid=''):
        """
        Generic test to confirm a Bus Tweet is being processed correctly
        """
        print tweet.text
        t1 = time.time()
        results = self.bot.process_tweet(tweet)
        self.assertTrue(results)
        t2 = time.time()
        self.assertTrue(results)
        for result in results:
            print result
            # Result exists, no TfL garbage please, and no all-caps either
            self.assertTrue(result)
            for unwanted in ('<>', '#', '\[DLR\]', '>T<'):
                self.assertNotRegexpMatches(result, unwanted)
            self.assertNotEqual(result, result.upper())
            # Should say one of our route numbers, expected origin and a time
            route_regex = "^(%s)" % '|'.join(routes_specified.upper().replace(',', '').split(' '))
            self.assertRegexpMatches(result, route_regex)
            if result.find("None shown") > -1:
                self.assertRegexpMatches(result, 'None shown going (North|NE|East|SE|South|SW|West|NW)(;|$)')
            else:
                self.assertRegexpMatches(result, '(%s to .* [0-9]{4})' % expected_origin)
            # If we have specified a direction or destination, we should not be seeing buses going the other way
            # and the expected origin should therefore only be repeated once
            if destination_to_avoid:
                self.assertNotRegexpMatches(result, destination_to_avoid)
                self.assertNotRegexpMatches(result, ";")
                self.assertEqual(result.count(expected_origin), 1)
            else:
                self.assertRegexpMatches(result, ";")

        print 'Processing of Tweet took %0.3f ms\r\n' % ((t2 - t1) * 1000.0,)

    #
    # Core functionality tests
    #

    def test_location(self):
        """
        Unit tests for WMTLocation object and the bus database
        """
        self.assertEqual(self.bot.geodata.find_closest((51.5124, -0.0397), {'run': '1', 'route': '15'}).number, "53410")
        self.assertEqual(self.bot.geodata.find_fuzzy_match("Limehouse Sta", {'run': '1', 'route': '15'}).number, "53410")
        self.assertEqual(self.bot.geodata.find_exact_match({'run': '1', 'route': '15', 'name': 'LIMEHOUSE TOWN HALL'}).number, "48264")
        self.assertTrue(self.bot.geodata.database.check_existence_of('locations', 'bus_stop_code', '47001'))
        self.assertFalse(self.bot.geodata.database.check_existence_of('locations', 'bus_stop_code', '47000'))
        self.assertEqual(self.bot.geodata.database.get_max_value('locations', 'run', {}), 4)

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

    def test_textparser(self):
        """
        Tests for the natural language parser
        """
        (route, origin, destination) = ('A1', 'Heathrow Airport', '47000')
        routes = [route]
        self.assertEqual(self.bot.parser.parse_message(""),                                                 (None, None, None, None))
        self.assertEqual(self.bot.parser.parse_message("from %s to %s %s" % (origin, destination, route)),  (None, None, None, None))
        self.assertEqual(self.bot.parser.parse_message("%s" % route),                                       (routes, None, None, None))
        self.assertEqual(self.bot.parser.parse_message("%s %s" % (route, origin)),                          (routes, origin, None, None))
        self.assertEqual(self.bot.parser.parse_message("%s %s to %s" % (route, origin, destination)),       (routes, origin, destination, None))
        self.assertEqual(self.bot.parser.parse_message("%s from %s" % (route, origin)),                     (routes, origin, None, None))
        self.assertEqual(self.bot.parser.parse_message("%s from %s to %s" % (route, origin, destination)),  (routes, origin, destination, None))
        self.assertEqual(self.bot.parser.parse_message("%s to %s" % (route, destination)),                  (routes, None, destination, None))
        self.assertEqual(self.bot.parser.parse_message("%s to %s from %s" % (route, destination, origin)),  (routes, origin, destination, None))

    #
    # Request-based tests
    #

    def test_bad_stop_id(self):
        """
        Test to confirm bad stop IDs handled OK
        """
        message = '15 from 00000'
        tweet = FakeTweet(self.at_reply + message)
        self._test_correct_exception_produced(tweet, 'bad_stop_id', '00000')  # Stop IDs begin at 47000
        direct_message = FakeDirectMessage(message)
        self._test_correct_exception_produced(direct_message, 'bad_stop_id', '00000')  # Stop IDs begin at 47000

    def test_stop_id_mismatch(self):
        """
        Test to confirm when route and stop do not match up is handled OK
        """
        message = '15 from 52240'
        tweet = FakeTweet(self.at_reply + message)
        self._test_correct_exception_produced(tweet, 'stop_id_not_found', '15', '52240')  # The 15 does not go from Canary Wharf
        direct_message = FakeDirectMessage(message)
        self._test_correct_exception_produced(direct_message, 'stop_id_not_found', '15', '52240')

    def test_stop_name_nonsense(self):
        """
        Test to confirm when route and stop do not match up is handled OK
        """
        message = '15 from Eucgekewf78'
        tweet = FakeTweet(self.at_reply + message)
        self._test_correct_exception_produced(tweet, 'stop_name_not_found', '15', 'Eucgekewf78')

    def test_standard_messages(self):
        """
        Generic test for standard-issue messages
        """
        #pylint: disable=W0612
        for (route, origin_name, origin_id, lat, lon, destination_name, destination_id, expected_origin, destination_to_avoid) in self.standard_test_data:

            # C-string format helper
            test_variables = dict([(name, eval(name)) for name in ('route', 'origin_name', 'origin_id', 'destination_name', 'destination_id')])

            # 5 types of origin (geotag, ID, name, ID without 'from', name without 'from') and 3 types of destination (none, ID, name)
            from_fragments = [value % test_variables for value in ("", " from %(origin_name)s",    " from %(origin_id)s", " %(origin_name)s", " %(origin_id)s")]
            to_fragments = [value % test_variables for value in ("", " to %(destination_name)s", " to %(destination_id)s")]

            for from_fragment in from_fragments:
                for to_fragment in to_fragments:
                    message = (self.at_reply + route + from_fragment + to_fragment)
                    if not from_fragment:
                        tweet = FakeTweet(message, (lat, lon))
                    else:
                        tweet = FakeTweet(message)
                    if (from_fragment.find(origin_id) > -1) or to_fragment:
                        self._test_correct_successes(tweet, route, expected_origin, destination_to_avoid)
                    else:
                        self._test_correct_successes(tweet, route, expected_origin)

    def test_multiple_routes(self):
        """
        Test multiple routes from different bus stops in the same area (unlike the above function which
        tests multiple routes going in the same direction, from the same stop(s)
        """
        test_data = (("277 15", (51.511694, -0.030286), "(East India Dock Road|Limehouse Town Hall)"),)

        for (route, position, expected_origin) in test_data:
            tweet = FakeTweet(self.at_reply + route, position)
            self._test_correct_successes(tweet, route, expected_origin)


bus_errors = ('no_bus_number', 'nonexistent_bus',)
stop_errors = ('bad_stop_id', 'stop_id_mismatch', 'stop_name_nonsense',)
bus_successes = ('nonstandard_messages', 'standard_messages', 'multiple_routes',)
