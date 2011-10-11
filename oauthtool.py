#!/usr/bin/env python
"""
Adapted from
http://talkfast.org/2010/05/31/twitter-from-the-command-line-in-python-using-oauth

Helper script to produce an OAuth user key & secret for a Twitter app, given the consumer key & secret
Log in as the user you want to authorise, visit the URL this script produces, then type in the PIN
Twitter's OAuth servers provide you to get a key/secret pair
"""
import tweepy
import sys
import ConfigParser

def make_oauth_key():
    config = ConfigParser.SafeConfigParser()
    config.read('whensmybus.cfg')
    
    CONSUMER_KEY = config.get('whensmybus','consumer_key')
    CONSUMER_SECRET = config.get('whensmybus','consumer_secret')
    
    if not CONSUMER_KEY or not CONSUMER_SECRET:
        print "Could not find consumer key or secret, exiting"
        sys.exit(0)
    
    auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
    auth_url = auth.get_authorization_url()
    print 'Please authorize: ' + auth_url
    verifier = raw_input('PIN: ').strip()
    auth.get_access_token(verifier)
    print "key : %s" % auth.access_token.key
    print "secret : %s" % auth.access_token.secret
    
if __name__ == "__main__":
    make_oauth_key()