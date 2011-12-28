#!/usr/bin/env python
#pylint: disable=C0103
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
from exception_handling import WhensMyTransportException

import argparse
import re
import unittest
from pprint import pprint
    
class FakeTweet:
    """
    Fake Tweet object to simulate tweepy's Tweet object being passed to various functions
    """
    def __init__(self, text, coordinates=(), place=None, username='testuser'):
        self.user = lambda:1
        self.user.screen_name = username
        self.text = text
        self.place = place
        self.coordinates = {}
        if coordinates:
            self.coordinates['coordinates'] = coordinates
        
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
        self.wmb = WhensMyBus(testing=True, silent=True)
        
        self.at_reply = '@%s ' % self.wmb.username
        
        # Route Number, Origin Name, Origin Number, Origin Longitude, Origin Latitude, Dest Name, Dest Number, Expected Origin
        self.test_standard_data = (('15', 'Limehouse Station', '53452', -0.0397, 51.5124, 'Poplar', '73923', 'Limehouse Station'),)

        self.test_nonstandard_data = (('%s from Stratford to Walthamstow', ('257',), 'The Grove'),
                                    ('%s from Hoxton',           ('243',),  'Hoxton Station'),   # Troublesome destinations 
                                    ('%s from Bow Common Lane',  ('323',),  'Bow Common Lane'),
                                    ('%s from EC1M 4PN',         ('55',),   'St John Street'),
                                    ('%s from Clerkenwell',      ('55', '243'), 'St John Street'),
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

    def test_politeness(self):
        """
        Test to see if we are replying to polite messagess correctly
        """
        tweet = FakeTweet(self.at_reply + 'Thank you!')
        result = self.wmb.process_tweet(tweet) or self.wmb.check_politeness(tweet)
        self.assertRegexpMatches(result, 'No problem')

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
        direct_message = FakeDirectMessage(message)
        self.assertFalse(self.wmb.process_tweet(direct_message))

    def _test_correct_exception_produced(self, tweet, exception_id, *string_params):
        """
        Generic test for the correct exception message
        """
        # Get the message for the exception_id specified, applying C string formatting if applicable
        # Then escape it so that regular expression module doesn't accidentally interpret brackets etc
        expected_error = re.escape(WhensMyTransportException(exception_id, *string_params).value)

        # Try processing the relevant Tweet        
        try:
            message = self.wmb.process_tweet(tweet)
        # If an exception is thrown, then see if its message matches the one we want
        except WhensMyTransportException as exc:
            self.assertRegexpMatches(exc.value, expected_error)
        # If there is no exception thrown, then see if the reply generated matches what we want
        else:
            self.assertRegexpMatches(message, expected_error)

    def test_blank_tweet(self):
        """
        Test to confirm we are ignoring blank replies
        """
        for message in ('',
                     ' ',
                     '         '):
            tweet = FakeTweet(self.at_reply + message)
            self._test_correct_exception_produced(tweet, 'blank_tweet')
            direct_message = FakeDirectMessage(message)
            self._test_correct_exception_produced(direct_message, 'blank_tweet')

    def test_nonexistent_bus(self):
        """
        Test to confirm non-existent buses handled OK
        """
        for message in ('218 from Trafalgar Square', '   218 from Trafalgar Square', '   218   from Trafalgar Square #hashtag'):
            tweet = FakeTweet(self.at_reply + message)
            self._test_correct_exception_produced(tweet, 'nonexistent_bus', '218')
            direct_message = FakeDirectMessage(message)
            self._test_correct_exception_produced(direct_message, 'nonexistent_bus', '218')


    def test_no_geotag(self):
        """
        Test to confirm lack of geotag handled OK
        """
        for test_data in self.test_standard_data:
            route = test_data[0]
            tweet = FakeTweet(self.at_reply + route)
            self._test_correct_exception_produced(tweet, 'no_geotag', route)
            direct_message = FakeDirectMessage(route)
            self._test_correct_exception_produced(direct_message, 'dms_not_taggable', route)

    def test_placeinfo_only(self):
        """
        Test to confirm ambiguous place information handled OK
        """
        for test_data in self.test_standard_data:
            route = test_data[0]
            tweet = FakeTweet(self.at_reply + route, place='foo')
            self._test_correct_exception_produced(tweet, 'placeinfo_only', route)
            
    def test_not_in_uk(self):
        """
        Test to confirm geolocations outside UK handled OK
        """
        for test_data in self.test_standard_data:
            route = test_data[0]
            tweet = FakeTweet(self.at_reply + route, (-73.985656, 40.748433)) # Empire State Building, New York
            self._test_correct_exception_produced(tweet, 'not_in_uk')

    def test_not_in_london(self):
        """
        Test to confirm geolocations outside London handled OK
        """
        for test_data in self.test_standard_data:
            route = test_data[0]
            tweet = FakeTweet(self.at_reply + route, (-3.200833, 55.948611)) # Edinburgh Castle, Edinburgh
            self._test_correct_exception_produced(tweet, 'not_in_london')

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
        message = '15 from eucg;#$78' 
        tweet = FakeTweet(self.at_reply + message) 
        self._test_correct_exception_produced(tweet, 'stop_name_not_found', '15', 'eucg;#$78')
        
    def test_destination_is_wrong(self):
        """
        Test to confirm when destination given is gibberish
        """
        message = '15 from eucg;#$78' 
        tweet = FakeTweet(self.at_reply + message) 
        self._test_correct_exception_produced(tweet, 'stop_name_not_found', '15', 'eucg;#$78')
        
    def test_standard_messages(self):
        """
        Generic test for standard-issue messages
        """
        for (route, origin_name, origin_id, lon, lat, destination_name, destination_id, expected_origin) in self.test_standard_data:
        
            # Nine different types of message: 3 types of origin (geotag, ID, name) and 3 types of destination
            # (none, ID, name)
        
            test_messages = (
                "%s"               % (route),
                "%s from %s"       % (route, origin_id),
                "%s from %s"       % (route, origin_name),
                "%s to %s"         % (route, destination_id),
                "%s from %s to %s" % (route, origin_id, destination_id),
                "%s from %s to %s" % (route, origin_name, destination_id),
                "%s to %s"         % (route, destination_name),
                "%s from %s to %s" % (route, origin_id, destination_name),
                "%s from %s to %s" % (route, origin_name, destination_name),
            )

            for message in test_messages:
                message = self.at_reply + message
                if message.find('from') == -1:
                    tweet = FakeTweet(message, (lon, lat))
                else:
                    tweet = FakeTweet(message)

                result = self.wmb.process_tweet(tweet)

                for unwanted in (expected_origin.upper(), '<>', '#', '\[DLR\]', '>T<'):                
                    self.assertNotRegexpMatches(result, unwanted)
                self.assertRegexpMatches(result, route.upper())
                self.assertRegexpMatches(result, '(%s to .* [0-9]{4}|None shown going)' % expected_origin)

                # We should get two results and hence a semi-colon separating them, if this is not from a specific stop
                if message.find(' to ') == -1 and message.find(origin_id) == -1:
                    self.assertRegexpMatches(result, ';')
                else:
                    self.assertNotRegexpMatches(result, ';')
                    
    def test_nonstandard_messages(self):
        """
        Test to confirm a message that can be troublesome comes out OK
        """
        for (text, routes, stop_name) in self.test_nonstandard_data:
            for route in routes:
                message = text % route
                tweet = FakeTweet(self.at_reply + message)
                result = self.wmb.process_tweet(tweet)
                
                for unwanted in ('<>', '#', '\[DLR\]', '>T<'):                
                    self.assertNotRegexpMatches(result, unwanted)
                self.assertRegexpMatches(result, route.upper())
                if message.find(' to ') == -1:
                    self.assertRegexpMatches(result, ';')
                else:
                    self.assertNotRegexpMatches(result, ';')
                self.assertRegexpMatches(result, '(%s.* to .* [0-9]{4}|None shown going)' % stop_name)

def test_whensmybus(): 
    """
    Run a suite of tests
    """
    parser = argparse.ArgumentParser("Unit testing for When's My Bus?")
    parser.add_argument("--dologin", dest="dologin", action="store_true", default=False) 
    
    init = ('init', 'oauth', 'database',)
    failures = (  'politeness', 'talking_to_myself', 'mention',
                  'no_bus_number', 'blank_tweet', 'nonexistent_bus', # Tweet formatting errors
                  'no_geotag', 'placeinfo_only', 'not_in_uk', 'not_in_london',                     # Geotag errors
                  'bad_stop_id', 'stop_id_mismatch', 'stop_name_nonsense',                         # Stop ID errors
                )
    successes = ('nonstandard_messages', 'standard_messages',)
    
    if parser.parse_args().dologin:
        test_names = init + failures + successes
    else:
        test_names = failures + successes
            
    suite = unittest.TestSuite(map(WhensMyBusTestCase, ['test_%s' % t for t in test_names]))
    runner = unittest.TextTestRunner(verbosity=1, failfast=1, buffer=False)
    runner.run(suite)

if __name__ == "__main__":
    test_whensmybus()