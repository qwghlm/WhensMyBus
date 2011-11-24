#!/usr/bin/env python
"""
A set of unit tests for When's My Bus?

IMPORTANT: These unit tests require Python 2.7, even though When's My Bus will happily run in Python 2.6

FIXME Some way of flushing all Tweets generated for reassurance

"""
import sys
if sys.version_info < (2, 7):
    print "Sorry. While WhensMyBus can be run under Python 2.6, this unit testing script requires the more extensive unittest libraries in Python 2.7."
    print "Please upgrade!"
    sys.exit(1)    

from whensmybus import WhensMyBus
from exception_handling import WhensMyTransportException

import argparse
import re
import unittest
from pprint import pprint
    
class FakeTweet:
    """
    Fake Tweet object to simulate tweepy's Tweet object being passed to various functions
    """
    def __init__(self, text, longitude=None, latitude=None, place=None, username='testuser'):
        self.user = lambda:1
        self.user.screen_name = username
        self.text = text
        self.place = place
        self.coordinates = {}
        if longitude and latitude:
            self.coordinates['coordinates'] = [longitude, latitude]
        
class FakeDirectMessage:
    """
    Fake DirectMessage object to simulate tweepy's DirectMessage object being passed to various functions
    """
    def __init__(self, text, username='testuser'):
        self.user = lambda:1
        self.user.screen_name = username
        self.text = text
            
class WhensMyBusTestCase(unittest.TestCase):
    """
    Main Test Case for When's My Bus
    """
    def setUp(self):
        """
        Setup test
        """
        self.wmb = WhensMyBus(testing=True, silent=False)
        
        self.at_reply = '@%s ' % self.wmb.username
        
        self.test_messages = (('%s', '15'),)
        
        self.test_messages_with_ids = (('%s from 52240', '277'),)

        self.test_messages_with_locations = (#('%s from Hoxton', '243'),
                                            #('%s from Hoxton station', '243'),
                                            ('%s from Bow Common Lane', '323'),
                                            ('%s from EC1M 4PN', '55'),
                                            )

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

        #self.wmb.geodata.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='locations'")
        #row = self.wmb.geodata.fetchone()
        #self.assertIsNotNone(row, 'Locations table does not exist')

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
        self.assertFalse(self.wmb.validate_tweet(tweet))

    def test_talking_to_myself(self):
        """
        Test to confirm we are ignoring Tweets from the bot itself
        """
        tweet = FakeTweet(self.at_reply + '15', username=self.wmb.username)
        self.assertFalse(self.wmb.validate_tweet(tweet))

    def test_no_bus_number(self):
        """
        Test to confirm we are ignoring Tweets that do not have bus numbers in them
        """
        message = 'Thanks!'
        tweet = FakeTweet(self.at_reply + message)
        self.assertFalse(self.wmb.process_tweet(tweet))
        dm = FakeDirectMessage(message)
        self.assertFalse(self.wmb.process_tweet(dm))

    def _test_correct_exception_produced(self, tweet, exception_id, *string_params):
        """
        Generic test for the correct exception message
        """
        # Get the message for the exception_id specified, applying C string formatting if applicable
        # Then escape it so that regular expression module doesn't accidentally interpret brackets etc
        expected_error = re.escape(WhensMyTransportException.exception_values[exception_id] % string_params)
        
        # Match the expected Exception message against the actual Exception raised when we try to process Tweet
        self.assertRaisesRegexp(WhensMyTransportException, expected_error, self.wmb.process_tweet, tweet)    
        
    def test_blank_tweet(self):
        """
        Test to confirm we are ignoring blank replies
        """
        for message in ('',
                     ' ',
                     '         '):
            tweet = FakeTweet(self.at_reply + message)
            self._test_correct_exception_produced(tweet, 'blank_tweet')
            dm = FakeDirectMessage(message)
            self._test_correct_exception_produced(dm, 'blank_tweet')

    def test_nonexistent_bus(self):
        """
        Test to confirm non-existent buses handled OK
        """
        for message in ('218', '   218', '   218   #hashtag'):
            tweet = FakeTweet(self.at_reply + message)
            self._test_correct_exception_produced(tweet, 'nonexistent_bus', '218')
            dm = FakeDirectMessage(message)
            self._test_correct_exception_produced(dm, 'nonexistent_bus', '218')


    def test_no_geotag(self):
        """
        Test to confirm lack of geotag handled OK
        """
        for (text, route) in self.test_messages:
            message = text % route
            tweet = FakeTweet(self.at_reply + message)
            self._test_correct_exception_produced(tweet, 'no_geotag', route)
            dm = FakeDirectMessage(message)
            self._test_correct_exception_produced(dm, 'dms_not_taggable', route)

    def test_placeinfo_only(self):
        """
        Test to confirm ambiguous place information handled OK
        """
        for (text, route) in self.test_messages:
            message = text % route
            tweet = FakeTweet(self.at_reply + message, place='foo')
            self._test_correct_exception_produced(tweet, 'placeinfo_only', route)
            
    def test_not_in_uk(self):
        """
        Test to confirm geolocations outside UK handled OK
        """
        for (text, route) in self.test_messages:
            message = text % route
            tweet = FakeTweet(self.at_reply + message, -73.985656, 40.748433) # Empire State Building, New York
            self._test_correct_exception_produced(tweet, 'not_in_uk')

    def test_not_in_london(self):
        """
        Test to confirm geolocations outside London handled OK
        """
        for (text, route) in self.test_messages:
            message = text % route
            tweet = FakeTweet(self.at_reply + message, -3.200833, 55.948611) # Edinburgh Castle, Edinburgh
            self._test_correct_exception_produced(tweet, 'not_in_london')

    def test_bad_stop_id(self):
        """
        Test to confirm bad stop IDs handled OK
        """
        message = '15 from 00000'
        tweet = FakeTweet(self.at_reply + message) 
        self._test_correct_exception_produced(tweet, 'bad_stop_id', '00000') # Stop IDs begin at 47000
        dm = FakeDirectMessage(message) 
        self._test_correct_exception_produced(dm, 'bad_stop_id', '00000') # Stop IDs begin at 47000
        
    def test_stop_id_mismatch(self):
        """
        Test to confirm when route and stop do not match up is handled OK
        """
        message = '15 from 52240'
        tweet = FakeTweet(self.at_reply + message) 
        self._test_correct_exception_produced(tweet, 'stop_id_mismatch', '15', '52240') # The 15 does not go from Canary Wharf
        dm = FakeDirectMessage(message) 
        self._test_correct_exception_produced(dm, 'stop_id_mismatch', '15', '52240') # Stop IDs begin at 47000
    
    def test_in_london_with_geotag(self):
        """
        Test to confirm a correctly-geotagged message is handled OK
        """
        for (text, route) in self.test_messages:
            message = text % route
            tweet = FakeTweet(self.at_reply + message, -0.0397, 51.5124) # Limehouse Station, London
            result = self.wmb.process_tweet(tweet)

            for unwanted in ('LIMEHOUSE STATION', '<>', '#', '\[DLR\]', '>T<'):                
                self.assertNotRegexpMatches(result, unwanted)

            self.assertRegexpMatches(result, route.upper())
            self.assertRegexpMatches(result, '(Limehouse Station to .* [0-9]{4}|None shown going)')

    def test_in_london_with_stop_id(self):
        """
        Test to confirm a message with correct stop ID is handled OK
        """
        for (text, route) in self.test_messages_with_ids:
            message = text % route
            tweet = FakeTweet(self.at_reply + message)
            result = self.wmb.process_tweet(tweet)

            for unwanted in ('CANARY WHARF', '<>', '#', '\[DLR\]', '>T<'):                
                self.assertNotRegexpMatches(result, unwanted)

            self.assertRegexpMatches(result, route.upper())
            self.assertRegexpMatches(result, '(Canary Wharf Station to .* [0-9]{4}|None shown going)')
            
            dm = FakeDirectMessage(message)
            result = self.wmb.process_tweet(dm)
            for unwanted in ('CANARY WHARF', '<>', '#', '\[DLR\]', '>T<'):                
                self.assertNotRegexpMatches(result, unwanted)

            self.assertRegexpMatches(result, route.upper())
            self.assertRegexpMatches(result, '(Canary Wharf Station to .* [0-9]{4}|None shown going)')            
            

    def test_in_london_with_stop_locations(self):
        """
        Test to confirm a message with location name is handled OK
        """
        for (text, route) in self.test_messages_with_locations:
            message = text % route
            tweet = FakeTweet(self.at_reply + message)
            result = self.wmb.process_tweet(tweet)
            
            for unwanted in ('<>', '#', '\[DLR\]', '>T<'):                
                self.assertNotRegexpMatches(result, unwanted)

            self.assertRegexpMatches(result, route.upper())
            self.assertRegexpMatches(result, '(.* to .* [0-9]{4}|None shown going)')

            """
            dm = FakeDirectMessage(message)
            result = self.wmb.process_tweet(dm)
            
            for unwanted in ('<>', '#', '\[DLR\]', '>T<'):                
                self.assertNotRegexpMatches(result, unwanted)

            self.assertRegexpMatches(result, route.upper())
            self.assertRegexpMatches(result, '(.* to .* [0-9]{4}|None shown going)')
            """

def test_whensmybus(): 
    """
    Run a suite of tests
    """
    parser = argparse.ArgumentParser("Unit testing for When's My Bus?")
    parser.add_argument("--dologin", dest="dologin", action="store_true", default=False) 
    
    init = ('init', 'oauth', 'database',)
    failures = (  'talking_to_myself', 'mention',
                  'no_bus_number', 'blank_tweet', 'nonexistent_bus', # Tweet formatting errors
                  'no_geotag', 'placeinfo_only', 'not_in_uk', 'not_in_london',                     # Geotag errors
                  'bad_stop_id', 'stop_id_mismatch',                                               # Stop ID errors
                )
    successes = ('in_london_with_geotag', 'in_london_with_stop_id', 'in_london_with_stop_locations', )
    
    if parser.parse_args().dologin:
        test_names = init + failures + successes
    else:
        test_names = ('in_london_with_stop_locations', ) #failures + successes
            
    suite = unittest.TestSuite(map(WhensMyBusTestCase, ['test_%s' % t for t in test_names]))
    unittest.TextTestRunner(verbosity=1, failfast=1).run(suite)
    
if __name__ == "__main__":
    test_whensmybus()