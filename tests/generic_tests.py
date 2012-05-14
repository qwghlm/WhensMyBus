#!/usr/bin/env python
# -*- coding: utf-8 -*-
#pylint: disable=C0103,W0142,R0915,R0904,W0403,W0141
"""
Unit test libraries for Whens My Bus? and When's My Tube?
"""
import sys
if sys.version_info < (2, 7):
    print "Sorry. While WhensMyBus can be run under Python 2.6, this unit testing script requires the more extensive unittest libraries in Python 2.7."
    print "Please upgrade!"
    sys.exit(1)

import logging
import os.path
import random
import re
import time
import unittest

# Abort if a dependency is not installed
try:
    from lib.dataparsers import parse_bus_data, parse_tube_data, parse_dlr_data
    from lib.exceptions import WhensMyTransportException
    from lib.geo import heading_to_direction, gridrefNumToLet, convertWGS84toOSEastingNorthing, LatLongToOSGrid, convertWGS84toOSGB36
    from lib.listutils import unique_values
    from lib.models import Location, RailStation, BusStop, Departure, NullDeparture, Train, TubeTrain, DLRTrain, Bus, DepartureCollection
    from lib.stringutils import capwords, get_name_similarity, get_best_fuzzy_match, cleanup_name_from_undesirables, gmt_to_localtime
    from lib.twitterclient import split_message_for_twitter

    from whensmytrain import LINE_NAMES, get_line_code, get_line_name
    from whensmytransport import TESTING_TEST_LOCAL_DATA, TESTING_TEST_LIVE_DATA

except ImportError as err:
    print """
Sorry, testing failed because a package that WhensMyTransport depends on is not installed. Reported error:

    %s

Missing packages can be downloaded as follows:

 * nltk: http://nltk.github.com/install.html
 * pygraph: http://code.google.com/p/python-graph/
 * tweepy: http://code.google.com/p/tweepy/
""" % err
    sys.exit(1)


HOME_DIR = os.path.dirname(os.path.abspath(__file__))


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
    def __init__(self, methodName, testing_level):
        """
        Override of the TestCase so we can also apply a testing level
        """
        self.testing_level = testing_level
        super(WhensMyTransportTestCase, self).__init__(methodName)

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
    def test_exceptions(self):
        """
        Unit tests for WhensMyTransportException objects
        """
        exc = WhensMyTransportException()
        self.assertEqual(exc.value, str(exc))
        self.assertLessEqual(len(exc.get_user_message()), 115)

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
        for (heading, direction) in ((0, "North"), (90, "East"), (135, "SE"), (225, "SW"),):
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
        capitalised_strings = ("Bank", "Morden East", "King's Cross St. Pancras", "Kennington Oval via Charing X")
        for test_string in capitalised_strings:
            self.assertEqual(test_string, capwords(test_string))
            self.assertEqual(test_string, capwords(test_string.lower()))
            self.assertEqual(test_string, capwords(test_string.upper()))
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

        # Check to see most similar string gets picked out of an list of similar-looking strings, and that
        # with very dissimilar strings, there is no candidate at all
        similarity_candidates = (similarity_string[:3], similarity_string[:5], similarity_string[:9], "z" * 10)
        self.assertEqual(get_best_fuzzy_match(similarity_string, similarity_candidates), similarity_candidates[-2])
        dissimilarity_candidates = [random_string(48, 57) for _i in range(0, 10)]
        self.assertIsNone(get_best_fuzzy_match(similarity_string, dissimilarity_candidates))

        if time.localtime().tm_isdst:
            self.assertEqual(gmt_to_localtime("2359"), "0059")
            self.assertEqual(gmt_to_localtime("23:59"), "0059")
            self.assertEqual(gmt_to_localtime("Tue 00:01"), "0101")
        else:
            self.assertEqual(gmt_to_localtime("2359"), "2359")
            self.assertEqual(gmt_to_localtime("23:59"), "2359")
            self.assertEqual(gmt_to_localtime("Tue 00:01"), "0001")

    def test_tubeutils(self):
        """
        Unit test for helper functions in WhensMyTrain
        """
        self.assertEqual(get_line_code('Central'), 'C')
        self.assertEqual(get_line_code('Circle'), 'O')
        self.assertEqual(get_line_name('C'), 'Central')
        self.assertEqual(get_line_name('O'), 'Circle')
        for (line_code, line_name) in LINE_NAMES.keys():
            self.assertEqual(line_name, get_line_name(get_line_code(line_name)))
            self.assertEqual(line_code, get_line_code(get_line_name(line_code)))

    @unittest.skipIf(time.localtime()[3] < 2, "Arbitrary nature of test data fails at midnight")
    def test_models(self):
        """
        Unit tests for train, bus, station and bus stop objects
        """
        # Location fundamentals
        location_name = "Trafalgar Square"
        location = Location(location_name)
        self.assertEqual(str(location), location_name)
        self.assertEqual(repr(location), location_name)
        self.assertEqual(len(location), len(location_name))

        # BusStop fundamentals
        bus_stop = BusStop("TRAFALGAR SQUARE / CHARING CROSS STATION <> # [DLR] >T<", bus_stop_code='10000', distance=2.0, run=1)
        bus_stop2 = BusStop("CHARING CROSS STATION <> # [DLR} >T< / TRAFALGAR SQUARE", bus_stop_code='10001', distance=1.0, run=2)
        self.assertLess(bus_stop2, bus_stop)
        self.assertEqual(len(bus_stop), 26)
        self.assertEqual(hash(bus_stop), hash(BusStop("TRAFALGAR SQUARE / CHARING CROSS STATION <> # [DLR] >T<", run=1)))

        # BusStop complex functions
        for undesirable in ('<>', '#', r'\[DLR\]', '>T<'):
            self.assertNotRegexpMatches(bus_stop.get_clean_name(), undesirable)
        self.assertEqual(bus_stop.get_clean_name(), "Trafalgar Square / Charing Cross Station")
        self.assertEqual(bus_stop.get_normalised_name(), "TRAFALGARSQCHARINGCROSSSTN")
        self.assertEqual(bus_stop.get_similarity(bus_stop.name), 100)
        self.assertEqual(bus_stop.get_similarity("Charing Cross Station"), 94)
        self.assertEqual(bus_stop2.get_similarity("Charing Cross Station"), 95)
        self.assertEqual(bus_stop.get_similarity("Charing Cross"), 90)
        self.assertEqual(bus_stop2.get_similarity("Charing Cross"), 91)

        # RailStation complex functions
        station = RailStation("King's Cross St. Pancras", "KXX", 530237, 182944)
        station2 = RailStation("Earl's Court", "ECT")
        self.assertEqual(station.get_abbreviated_name(), "Kings X St P")
        self.assertEqual(station2.get_abbreviated_name(), "Earls Ct")
        self.assertEqual(station.get_similarity(station.name), 100)
        self.assertGreaterEqual(station.get_similarity("Kings Cross St Pancras"), 95)
        self.assertGreaterEqual(station.get_similarity("Kings Cross St Pancreas"), 90)
        self.assertGreaterEqual(station.get_similarity("Kings Cross"), 90)

        # Departure
        departure = Departure("Trafalgar Square", "2359")
        departure2 = Departure("Trafalgar Square", "0001")
        self.assertLess(departure, departure2)  # Fails if test run at 0000-0059
        self.assertEqual(hash(departure), hash(Departure("Trafalgar Square", "2359")))
        self.assertEqual(str(departure), "Trafalgar Square 2359")
        self.assertEqual(departure.get_destination(), "Trafalgar Square")
        self.assertEqual(departure.get_departure_time(), "2359")

        # NullDeparture
        null_departure = NullDeparture("East")
        self.assertEqual(null_departure.get_destination(), "None shown going East")
        self.assertEqual(null_departure.get_departure_time(), "")

        # Bus
        bus = Bus("Blackwall", "2359")
        bus2 = Bus("Blackwall", "0001")
        self.assertLess(bus, bus2)  # Fails if test run at 0000-0059
        self.assertEqual(bus.get_destination(), "Blackwall")

        # Train
        train = Train("Charing Cross via Bank", "2359")
        train2 = Train("Charing Cross via Bank", "0001")
        self.assertLess(train, train2)  # Fails if test run at 0000-0059
        self.assertEqual(train.get_destination(), "Charing Cross via Bank")

        # TubeTrain
        tube_train = TubeTrain("Charing Cross via Bank", "Northbound", "2359", "N", "001")
        tube_train2 = TubeTrain("Charing Cross via Bank then depot", "Northbound", "2359", "N", "001")
        tube_train3 = TubeTrain("Northern Line", "Northbound", "2359", "N", "001")
        tube_train4 = TubeTrain("Heathrow T123 + 5", "Westbound", "2359", "P", "001")
        self.assertEqual(hash(tube_train), hash(tube_train2))
        self.assertEqual(tube_train.get_destination(), "Charing Cross via Bank")
        self.assertEqual(tube_train3.get_destination(), "Northbound Train")
        self.assertEqual(tube_train4.get_destination(), "Heathrow Terminal 5")
        self.assertEqual(tube_train.get_destination_no_via(), "Charing Cross")
        self.assertEqual(tube_train.get_via(), "Bank")

        # DLRTrain
        dlr_train = DLRTrain("Beckton", "1200")
        self.assertEqual(dlr_train.line_code, "DLR")

        # DepartureCollection fundamentals
        departures = DepartureCollection()
        departures[bus_stop] = [bus]
        self.assertEqual(departures[bus_stop], [bus])
        self.assertEqual(len(departures), 1)
        del departures[bus_stop]
        self.assertFalse(bus_stop in departures)

        # DepartureCollection for trains
        departures.add_to_slot(bus_stop, bus)
        departures.add_to_slot(bus_stop, bus2)
        self.assertEqual(str(departures), "Trafalgar Square / Charing Cross Station to Blackwall 2359 0001")
        departures[bus_stop2] = []
        departures.cleanup(lambda stop: NullDeparture("West"))
        self.assertEqual(str(departures), "None shown going West; Trafalgar Square / Charing Cross Station to Blackwall 2359 0001")
        departures.add_to_slot(bus_stop, Bus("Leamouth", "2358"))
        self.assertEqual(str(departures), "None shown going West; Trafalgar Square / Charing Cross Station to Leamouth 2358, Blackwall 2359 0001")

        # DepartureCollection for trains
        departures = DepartureCollection()
        departures["P1"] = [Train("Bank", "1210"), Train("Tower Gateway", "1203"), Train("Bank", "1200")]
        departures["P2"] = [Train("Tower Gateway", "1205"), Train("Tower Gateway", "1212"), Train("Bank", "1207")]
        departures["P3"] = [Train("Lewisham", "1200"), Train("Lewisham", "1204"), Train("Lewisham", "1208")]
        departures["P4"] = []
        departures.merge_common_slots()
        departures.cleanup(lambda platform: NullDeparture("from %s" % platform))
        self.assertEqual(str(departures), "Bank 1200 1207 1210, Tower Gateway 1203 1205; Lewisham 1200 1204 1208; None shown going from P4")
        departures.filter(lambda train: train.get_destination() != "Lewisham")
        self.assertEqual(str(departures), "Bank 1200 1207 1210, Tower Gateway 1203 1205; None shown going from P4")
        departures["P4"] = []
        departures.filter(lambda train: train.get_destination() != "Tower Gateway", True)
        self.assertEqual(str(departures), "Bank 1200 1207 1210")

    # Fundamental non-unit functionality tests. These need a WMT bot set up and are thus contingent on a
    # config.cfg files to test things such as a particular instance's databases, geocoder and browser
    def test_init(self):
        """
        Test to see if we can load the class in the first place
        """
        self.assertIsNotNone(self.bot)

    def test_browser(self):
        """
        Unit tests for WMTBrowser object
        """
        for filename in ("test.xml", "test.json"):
            url = "file://" + HOME_DIR + "/data/unit/" + filename
            if filename.endswith('json'):
                data = self.bot.browser.fetch_json(url)
                self.assertEqual(data['answer_to_life_universe_everything'], 42)
            elif filename.endswith('xml'):
                data = self.bot.browser.fetch_xml_tree(url)
                self.assertEqual(data.find("answer[@key='to_life_universe_everything']").attrib['value'], '42')
            self.assertIn(url, self.bot.browser.cache)

        for filename in ("test_broken.json", "test_broken.xml"):
            url = "file://" + HOME_DIR + "/data/unit/" + filename
            try:
                if filename.endswith('json'):
                    data = self.bot.browser.fetch_json(url)
                elif filename.endswith('xml'):
                    data = self.bot.browser.fetch_xml_tree(url)
            except WhensMyTransportException as exc:
                self.assertEqual('tfl_server_down', exc.msgid)
                continue
            finally:
                self.assertNotIn(url, self.bot.browser.cache)

    def test_database(self):
        """
        Unit tests for WMTDatabase object and to see if requisite database tables exist
        """
        self.bot.geodata.database.write_query("CREATE TEMPORARY TABLE test_data (key, value INT)")

        for key_value in (('a', 1), ('b', 2), ('b', 3)):
            self.bot.geodata.database.write_query("INSERT INTO test_data VALUES (?, ?)", key_value)
        row = self.bot.geodata.database.get_row("SELECT * FROM test_data WHERE key = 'a'")
        self.assertIsNotNone(row)
        self.assertEqual(row[1], 1)
        rows = self.bot.geodata.database.get_rows("SELECT * FROM test_data WHERE key = 'b' ORDER BY value")
        self.assertIsNotNone(rows)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][1], 3)
        value = self.bot.geodata.database.get_value("SELECT value FROM test_data WHERE key = 'a'")
        self.assertIsNotNone(value)
        self.assertEqual(value, 1)
        value = self.bot.geodata.database.get_value("SELECT value FROM test_data WHERE key = 'c'")
        self.assertIsNone(value)
        self.assertTrue(self.bot.geodata.database.check_existence_of('test_data', 'key', 'a'))
        self.assertEqual(self.bot.geodata.database.get_max_value('test_data', 'value', {}), 3)
        self.assertEqual(self.bot.geodata.database.make_where_statement('test_data', {}), (" 1 ", ()))
        self.assertEqual(self.bot.geodata.database.make_where_statement('test_data', {'key': 'a', 'value': 1}), ('"key" = ? AND "value" = ?', ('a', 1)))
        self.assertRaises(KeyError, self.bot.geodata.database.make_where_statement, 'test_data', {'foo': 'a'})

        self.bot.geodata.database.write_query("DROP TABLE test_data")

        for name in self.geodata_table_names:
            row = self.bot.geodata.database.get_row("SELECT name FROM sqlite_master WHERE type='table' AND name='%s'" % name)
            self.assertIsNotNone(row, '%s table does not exist' % name)

    @unittest.skipIf('--live-data' in sys.argv, "Data parser unit test will fail on live data")
    def test_dataparsers(self):
        """
        Unit tests for Data parsers objects
        """
        # Check against our test data and make sure we are correctly parsing & fetching the right objects from the data
        bus_data = parse_bus_data(self.bot.browser.fetch_json(self.bot.urls.BUS_URL % "53410"), '15')
        self.assertEqual(bus_data[0], Bus("Regent Street", gmt_to_localtime("1831")))
        tube_data = parse_tube_data(self.bot.browser.fetch_xml_tree(self.bot.urls.TUBE_URL % ("D", "ECT")), RailStation("Earl's Court"), "D")
        self.assertEqual(tube_data["Eastbound"][0], TubeTrain("Edgware Road", "Eastbound", "2139", "D", "075"))
        dlr_data = parse_dlr_data(self.bot.browser.fetch_xml_tree(self.bot.urls.DLR_URL % "pop"), RailStation("Poplar"))
        self.assertEqual(dlr_data['P1'][0], Train("Beckton", "2107"))

    def test_geocoder(self):
        """
        Unit tests for Geocoder objects
        """
        if not self.bot.geocoder:
            return
        test_locations = {"Blackfriars station": (51.5116, -0.1036),
                          "Buckingham Palace": (51.5012, -0.1425),
                          "Wembley Stadium": (51.5558, -0.2797),
                          "qwerty": None}
        for (name, value) in test_locations.items():
            geocode_url = self.bot.geocoder.get_geocode_url(name)
            geodata = self.bot.browser.fetch_json(geocode_url)
            points = self.bot.geocoder.parse_geodata(geodata)
            if value is None:
                self.assertFalse(points)
            else:
                self.assertAlmostEqual(points[0][0], value[0], places=3)
                self.assertAlmostEqual(points[0][1], value[1], places=3)

    def test_logger(self):
        """
        Unit tests for system logging
        """
        self.assertGreater(len(logging.getLogger('').handlers), 0)

    def test_settings(self):
        """
        Test to see if settings database does not exist
        """
        query = "SELECT name FROM sqlite_master WHERE type='table' AND name='%s_settings'" % self.bot.instance_name
        row = self.bot.twitter_client.settings.settingsdb.get_row(query)
        self.assertIsNotNone(row, 'Settings table does not exist')
        test_time = int(time.time())
        self.bot.twitter_client.settings.update_setting("_test_time", test_time)
        self.assertEqual(test_time, self.bot.twitter_client.settings.get_setting("_test_time"))

    def test_twitter_tools(self):
        """
        Test to see if Twitter helper functions such as message splitting work properly
        """
        (message1, message2) = ("486 Charlton Stn / Charlton Church Lane to Bexleyheath Ctr 1935",
                                "Charlton Stn / Charlton Church Lane to North Greenwich 1934")
        message = "%s; %s" % (message1, message2)
        split_messages = [u"%s…" % message1, u"…%s" % message2]
        self.assertEqual(split_message_for_twitter(message, '@test_username'), split_messages)

    def test_twitter_client(self):
        """
        Test to see if our OAuth login details are correct
        """
        self.assertTrue(self.bot.twitter_client.api.verify_credentials(), msg="Twitter API credentials failed. Fix or try running with --local-only")

    #
    # Tests that Tweets are in the right format
    #

    def test_politeness(self):
        """
        Test to see if we are replying to polite messages correctly
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
        tweet = FakeTweet(self.at_reply + self.standard_test_data[0][0], username=self.bot.username)
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
        for test_data in self.standard_test_data:
            request = "%s" % test_data[0]
            tweet = FakeTweet(self.at_reply + request)
            self._test_correct_exception_produced(tweet, 'no_geotag', request)
            direct_message = FakeDirectMessage(request)
            self._test_correct_exception_produced(direct_message, 'dms_not_taggable', request)

    def test_placeinfo_only(self):
        """
        Test to confirm ambiguous place information handled OK
        """
        for test_data in self.standard_test_data:
            request = "%s" % test_data[0]
            tweet = FakeTweet(self.at_reply + request, place='foo')
            self._test_correct_exception_produced(tweet, 'placeinfo_only', request)

    def test_not_in_uk(self):
        """
        Test to confirm geolocations outside UK handled OK
        """
        for test_data in self.standard_test_data:
            request = "%s" % test_data[0]
            tweet = FakeTweet(self.at_reply + request, (40.748433, -73.985656))  # Empire State Building, New York
            self._test_correct_exception_produced(tweet, 'not_in_uk')

    def test_not_in_london(self):
        """
        Test to confirm geolocations outside London handled OK
        """
        for test_data in self.standard_test_data:
            request = "%s" % test_data[0]
            tweet = FakeTweet(self.at_reply + request, (55.948611, -3.200833))  # Edinburgh Castle, Edinburgh
            self._test_correct_exception_produced(tweet, 'not_in_london')

    @unittest.skipIf('--live-data' in sys.argv, "Expected responses to messages not replicable with live data")
    def test_nonstandard_messages(self):
        """
        Test to confirm a message that can be troublesome comes out OK
        """
        for (request, mandatory_items, forbidden_items) in self.nonstandard_test_data:
            message = self.at_reply + request
            print message
            tweet = FakeTweet(message)
            t1 = time.time()
            results = self.bot.process_tweet(tweet)
            t2 = time.time()
            self.assertTrue(results)
            for result in results:
                print result
                # Result exists, no TfL garbag  e please, and no all-caps either
                self.assertTrue(result)
                for unwanted in ('<>', '#', '\[DLR\]', '>T<'):
                    self.assertNotRegexpMatches(result, unwanted)
                self.assertNotEqual(result, result.upper())
                for mandatory_item in mandatory_items:
                    self.assertRegexpMatches(result, mandatory_item)
                for forbidden_item in forbidden_items:
                    self.assertNotRegexpMatches(result, forbidden_item)
            print 'Processing of Tweet took %0.3f ms\r\n' % ((t2 - t1) * 1000.0,)

# Definition of which unit tests and in which order to run them in
#
# Init tests (same for all)
unit_tests = ('exceptions', 'geo', 'listutils', 'models', 'stringutils', 'tubeutils')
local_tests = ('init', 'browser', 'database', 'dataparsers', 'location', 'logger', 'settings', 'textparser', 'twitter_tools')
remote_tests = ('geocoder', 'twitter_client',)

# Common errors for all
format_errors = ('politeness', 'talking_to_myself', 'mention', 'blank_tweet',)
geotag_errors = ('no_geotag', 'placeinfo_only', 'not_in_uk', 'not_in_london',)
