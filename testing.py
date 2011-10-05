import unittest
from whensmybus import WhensMyBus, WhensMyBusException
import logging

# http://docs.python.org/release/2.6/library/unittest.html

class TestFakeTweet:
    def __init__(self, text):
        self.user = lambda:1
        self.user.screen_name = 'testuser'
        self.text = text

class WhensMyBusTestCase(unittest.TestCase):
    def setUp(self):
        self.WMB = WhensMyBus(testing=True, silent=True)
        
    def tearDown(self):
        self.WMB = None  
        
    def test_oauth(self):
        self.assertTrue(self.WMB.api.verify_credentials(), 'OAuth settings incorrect')
        
    def test_mention(self):
        t = TestFakeTweet('Hello @whensmybus')
        self.assertFalse(self.WMB.process_tweet(t), 'Incorrectly replying to non-reply mentions')

    def test_no_bus_number(self):
        t = TestFakeTweet('@whensmybus Thanks!')
        self.assertFalse(self.WMB.process_tweet(t), 'Incorrectly replying to mentions without bus number')

        
suite = unittest.TestLoader().loadTestsFromTestCase(WhensMyBusTestCase)
unittest.TextTestRunner(verbosity=2).run(suite)