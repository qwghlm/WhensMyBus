#!/usr/bin/env python
"""
A set of unit tests for When's My Bus?

IMPORTANT: Requires Python 2.7, even though When's My Bus will happily run in Python 2.6
"""
import sys
if sys.version_info < (2, 7):
    print "Sorry. While WhensMyBus can be run under Python 2.6, this unit testing script requires the unittest libraries in Python 2.7. Please upgrade!"
    sys.exit(1)    

from whensmybus import WhensMyBus, WhensMyBusException

import argparse
import re
import unittest
from pprint import pprint
    
DEFAULT_TEST_TWEETS = ('@whensmybus 15',
                       '@whensmybus   D3  ',
                       '@whensmybus   15  #hashtag ',)

class FakeTweet:
    """
    Fake Tweet object to simulate tweepy's Tweet object being passed to various functions
    """
    def __init__(self, text, longitude=None, latitude=None, place={}):
        self.user = lambda:1
        self.user.screen_name = 'testuser'
        self.text = text
        self.place = place
        self.coordinates = {}
        if longitude and latitude:
            self.coordinates['coordinates'] = [longitude,latitude]
        

class WhensMyBusTestCase(unittest.TestCase):
    """
    Main Test Case for When's My Bus
    """
    def setUp(self):
        """
        Setup test
        """
        self.wmb = WhensMyBus(testing=True, silent=True)
        
    def tearDown(self):
        """
        Tear down test
        """
        self.wmb = None  

    #
    # Fundamental functionality tests
    #

    def test_init(self):
        """
        Test to see if we can load the class in the first place
        """
        self.assertTrue(True)
        
    def test_database(self):
        """
        Test to see if databases have loaded correctly and files exist
        """
        self.wmb.settings.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='whensmybus_settings'")
        row = self.wmb.settings.fetchone()
        self.assertIsNotNone(row, 'Settings table does not exist')

        self.wmb.geodata.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='locations'")
        row = self.wmb.geodata.fetchone()
        self.assertIsNotNone(row, 'Locations table does not exist')

        self.wmb.geodata.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='routes'")
        row = self.wmb.geodata.fetchone()
        self.assertIsNotNone(row, 'Routes table does not exist')
        
    def test_oauth(self):
        """
        Test to see if our OAuth login details are correct
        """
        self.assertTrue(self.wmb.api.verify_credentials())
        
    #
    # Really important tests
    #

    def test_mention(self):
        """
        Test to confirm we are ignoring Tweets that are just mentions and not replies
        """
        tweet = FakeTweet('Hello @whensmybus')
        self.assertFalse(self.wmb.process_tweet(tweet))

    def test_no_bus_number(self):
        """
        Test to confirm we are ignoring Tweets that do not have bus numbers in them
        """
        tweet = FakeTweet('@whensmybus Thanks!')
        self.assertFalse(self.wmb.process_tweet(tweet))

    def _test_correct_exception_produced(self, tweet, exception_id, *string_params):
        """
        Generic test for the correct exception message
        """
        # Get the message for the exception_id specified, applying C string formatting if applicable
        # Then escape it so that regular expression module doesn't accidentally interpret brackets etc
        expected_error = re.escape(WhensMyBusException.exception_values[exception_id] % string_params)
        
        # Match the expected Exception message against the actual Exception raised when we try to process Tweet
        self.assertRaisesRegexp(WhensMyBusException, expected_error, self.wmb.process_tweet, tweet)    

        
    def test_blank_tweet(self):
        for text in ('@whensmybus',
                     '@whensmybus ',
                     '@whensmybus         ',):
            tweet = FakeTweet(text)
            self._test_correct_exception_produced(tweet, 'blank_tweet')

    def test_nonexistent_bus(self):
        for text in ('@whensmybus 218',
                     '@whensmybus    218',
                     '@whensmybus    218   #hashtag',):
            tweet = FakeTweet(text)
            self._test_correct_exception_produced(tweet, 'nonexistent_bus', '218')

    def test_no_geotag(self):
        for text in DEFAULT_TEST_TWEETS:
            tweet = FakeTweet(text)
            self._test_correct_exception_produced(tweet, 'no_geotag')

    def test_placeinfo_only(self):
        for text in DEFAULT_TEST_TWEETS:
            tweet = FakeTweet(text, place='foo')
            self._test_correct_exception_produced(tweet, 'placeinfo_only')
            
    def test_not_in_uk(self):
        for text in DEFAULT_TEST_TWEETS:
            tweet = FakeTweet(text, -73.985656, 40.748433) # Empire State Building, New York
            self._test_correct_exception_produced(tweet, 'not_in_uk')

    def test_not_in_london(self):
        for text in DEFAULT_TEST_TWEETS:
            tweet = FakeTweet(text, -3.200833, 55.948611) # Edinburgh Castle, Edinburgh
            self._test_correct_exception_produced(tweet, 'not_in_london')

    def test_in_london_with_geotag(self):
        for text in DEFAULT_TEST_TWEETS:
            tweet = FakeTweet(text, -0.0397, 51.5124) # Limehouse Station, London
            result = self.wmb.process_tweet(tweet)[0]

            for unwanted in ('LIMEHOUSE STATION', '<>', '#', '\[DLR\]', '>T<'):                
                self.assertNotRegexpMatches(result, unwanted)

            # Match username, number, stop name and either a destination & time or "None shown"
            self.assertRegexpMatches(result, '^@%s' % tweet.user.screen_name)
            self.assertRegexpMatches(result, re.split(' +', text)[1])
            self.assertRegexpMatches(result, '(Limehouse Station to .* [0-9]{4}|None shown going)')

if __name__ == "__main__":

    parser = argparse.ArgumentParser("Unit testing for When's My Bus?")
    parser.add_argument("--dologin", dest="dologin", action="store_true", default=False) 
    dologin = parser.parse_args().dologin
    
    if dologin:
        # Run tests initially on most crucial elements
        init_tests = ('init', 'oauth', 'database')
        suite = unittest.TestSuite(map(WhensMyBusTestCase, ['test_%s' % t for t in init_tests]))
        results = unittest.TextTestRunner(verbosity=1, failfast=1).run(suite)
    else:
        results = []
    
    # If we pass, then run tests on individual functionality
    if not results or not (results.failures + results.errors):
        main_tests = ('mention','no_bus_number','blank_tweet','nonexistent_bus','no_geotag','placeinfo_only','not_in_uk','not_in_london','in_london_with_geotag')
        suite = unittest.TestSuite(map(WhensMyBusTestCase, ['test_%s' % t for t in main_tests]))
        results = unittest.TextTestRunner(verbosity=1).run(suite)
