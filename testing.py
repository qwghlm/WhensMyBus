#!/usr/bin/env python
"""
A set of unit tests for When's My Bus?

IMPORTANT: These unit tests require Python 2.7, even though When's My Bus will happily run in Python 2.6
"""
import sys
if sys.version_info < (2, 7):
    print "Sorry. While WhensMyBus can be run under Python 2.6, this unit testing script requires the more extensive unittest libraries in Python 2.7. Please upgrade!"
    sys.exit(1)    

from whensmybus import WhensMyBus, WhensMyBusException

import argparse
import re
import unittest
from pprint import pprint
    
class FakeTweet:
    """
    Fake Tweet object to simulate tweepy's Tweet object being passed to various functions
    """
    def __init__(self, text, longitude=None, latitude=None, place={}, username='testuser'):
        self.user = lambda:1
        self.user.screen_name = username
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
        
        self.test_tweets = (('@%s %s', '15'),)
        
        self.test_tweets_with_ids = (('@%s %s from 52240', '277'),)

        self.test_tweets_with_locations = (('@%s %s from Trafalgar Square', '15'),)

        
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
        tweet = FakeTweet('Hello @%s' % self.wmb.username)
        self.assertFalse(self.wmb.process_tweet(tweet))

    def test_talking_to_myself(self):
        """
        Test to confirm we are ignoring Tweets from the bot itself
        """
        tweet = FakeTweet('@%s 15' % self.wmb.username, username=self.wmb.username)
        self.assertFalse(self.wmb.process_tweet(tweet))

    def test_no_bus_number(self):
        """
        Test to confirm we are ignoring Tweets that do not have bus numbers in them
        """
        tweet = FakeTweet('@%s Thanks!' % self.wmb.username)
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
        for text in ('@%s' % self.wmb.username,
                     '@%s ' % self.wmb.username,
                     '@%s         ' % self.wmb.username,):
            tweet = FakeTweet(text)
            self._test_correct_exception_produced(tweet, 'blank_tweet')

    def test_nonexistent_bus(self):
        for text in ('@%s 218' % self.wmb.username,
                     '@%s    218' % self.wmb.username,
                     '@%s    218   #hashtag' % self.wmb.username,):
            tweet = FakeTweet(text)
            self._test_correct_exception_produced(tweet, 'nonexistent_bus', '218')

    def test_no_geotag(self):
        for (text, route) in self.test_tweets:
            tweet = FakeTweet(text % (self.wmb.username, route))
            self._test_correct_exception_produced(tweet, 'no_geotag')

    def test_placeinfo_only(self):
        for (text, route) in self.test_tweets:
            tweet = FakeTweet(text % (self.wmb.username, route), place='foo')
            self._test_correct_exception_produced(tweet, 'placeinfo_only')
            
    def test_not_in_uk(self):
        for (text, route) in self.test_tweets:
            tweet = FakeTweet(text % (self.wmb.username, route), -73.985656, 40.748433) # Empire State Building, New York
            self._test_correct_exception_produced(tweet, 'not_in_uk')

    def test_not_in_london(self):
        for (text, route) in self.test_tweets:
            tweet = FakeTweet(text % (self.wmb.username, route), -3.200833, 55.948611) # Edinburgh Castle, Edinburgh
            self._test_correct_exception_produced(tweet, 'not_in_london')

    def test_bad_stop_id(self):
        tweet = FakeTweet('@%s 15 from 00000' % (self.wmb.username,)) 
        self._test_correct_exception_produced(tweet, 'bad_stop_id', '00000') # Stop IDs begin at 47000
        
        tweet = FakeTweet('@%s 15 from Limehouse' % (self.wmb.username,)) 
        self._test_correct_exception_produced(tweet, 'stop_not_found', 'Limehouse') # We can't yet recognise ambiguous placenames

    def test_stop_id_mismatch(self):
        tweet = FakeTweet('@%s 15 from 52240' % (self.wmb.username,)) 
        self._test_correct_exception_produced(tweet, 'stop_id_mismatch', '15', '52240') # The 15 does not go from Canary Wharf
    
    def test_in_london_with_geotag(self):
        for (text, route) in self.test_tweets:
            tweet = FakeTweet(text % (self.wmb.username, route), -0.0397, 51.5124) # Limehouse Station, London
            result = self.wmb.process_tweet(tweet)[0]

            for unwanted in ('LIMEHOUSE STATION', '<>', '#', '\[DLR\]', '>T<'):                
                self.assertNotRegexpMatches(result, unwanted)

            self.assertRegexpMatches(result, '^@%s' % tweet.user.screen_name)
            self.assertRegexpMatches(result, route.upper())
            self.assertRegexpMatches(result, '(Limehouse Station to .* [0-9]{4}|None shown going)')

    def test_in_london_with_stop_id(self):
        for (text, route) in self.test_tweets_with_ids:
            tweet = FakeTweet(text % (self.wmb.username, route))
            result = self.wmb.process_tweet(tweet)[0]

            for unwanted in ('CANARY WHARF', '<>', '#', '\[DLR\]', '>T<'):                
                self.assertNotRegexpMatches(result, unwanted)

            self.assertRegexpMatches(result, '^@%s' % tweet.user.screen_name)
            self.assertRegexpMatches(result, route.upper())
            self.assertRegexpMatches(result, '(Canary Wharf Station to .* [0-9]{4}|None shown going)')

    def test_in_london_with_stop_locations(self):
        for (text, route) in self.test_tweets_with_locations:
            tweet = FakeTweet(text % (self.wmb.username, route))
            result = self.wmb.process_tweet(tweet)[0]

            for unwanted in ('TRAFALGAR SQUARE', '<>', '#', '\[DLR\]', '>T<'):                
                self.assertNotRegexpMatches(result, unwanted)

            self.assertRegexpMatches(result, '^@%s' % tweet.user.screen_name)
            self.assertRegexpMatches(result, route.upper())
            self.assertRegexpMatches(result, '(Trafalgar Square to .* [0-9]{4}|None shown going)')

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
        main_tests = ('talking_to_myself','mention','no_bus_number','blank_tweet','nonexistent_bus',# Tweet formatting errors
                      'no_geotag','placeinfo_only','not_in_uk','not_in_london',                     # Geotag errors
                      'bad_stop_id','stop_id_mismatch',                                             # Stop ID errors
                      'in_london_with_stop_id', 'in_london_with_stop_id', 'in_london_with_geotag')  # When it all goes right :)
        suite = unittest.TestSuite(map(WhensMyBusTestCase, ['test_%s' % t for t in main_tests]))
        results = unittest.TextTestRunner(verbosity=1, failfast=1).run(suite)
