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
import re
import unittest

class FakeTweet:
    """
    Fake Tweet object to simulate tweepy's Tweet object being passed to various functions
    """
    def __init__(self, text, longitude=None, latitude=None, place=None):
        self.user = lambda:1
        self.user.screen_name = 'testuser'
        self.text = text
        self.place = place
        self.coordinates = None

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
        
    def test_nonexistent_bus(self):
        tweet = FakeTweet('@whensmybus 218')
        self._test_correct_exception_produced(tweet, 'nonexistent_bus', '218')
        
    def test_no_geotag(self):
        tweet = FakeTweet('@whensmybus 15')
        self._test_correct_exception_produced(tweet, 'no_geotag')
    
   
# @whensmybus 15
# @whensmybus  15
# @whensmybus 15 #hashtag

# Run tests initially on most crucial elements
init_tests = ('init', 'oauth', 'database')
suite = unittest.TestSuite(map(WhensMyBusTestCase, ['test_%s' % t for t in init_tests]))
results = unittest.TextTestRunner(verbosity=1, failfast=1).run(suite)

# If we pass, then run tests on individual functionality
if not (results.failures + results.errors):
    main_tests = ('mention','no_bus_number','nonexistent_bus','no_geotag')
    suite = unittest.TestSuite(map(WhensMyBusTestCase, ['test_%s' % t for t in main_tests]))
    results = unittest.TextTestRunner(verbosity=1).run(suite)
