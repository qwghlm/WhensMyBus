#!/usr/bin/env python
#pylint: disable=W0107
"""
Utilities for WhensMyTransport
"""
import logging
import os
import sqlite3
import sys
import tweepy
import ConfigParser

from pprint import pprint

HOME_DIR = os.path.dirname(os.path.abspath(__file__))

# Database stuff

def load_database(dbfilename):
    """
    Helper function to load a database and return links to it and its cursor
    """
    logging.debug("Opening database %s", dbfilename)
    dbs = sqlite3.connect(HOME_DIR + '/db/' + dbfilename)
    dbs.row_factory = sqlite3.Row
    return (dbs, dbs.cursor())

# Twitter stuff

def is_direct_message(tweet):
    """
    Returns True if a Tweet object is that of Tweepy's Direct Message, False if any other kind
    """
    return isinstance(tweet, tweepy.models.DirectMessage)

# OAuth stuff

def make_oauth_key(instance_name='whensmybus'):
    """
    Adapted from
    http://talkfast.org/2010/05/31/twitter-from-the-command-line-in-python-using-oauth
    
    Helper script to produce an OAuth user key & secret for a Twitter app, given the consumer key & secret
    Log in as the user you want to authorise, visit the URL this script produces, then type in the PIN
    Twitter's OAuth servers provide you to get a key/secret pair
    """
    config = ConfigParser.SafeConfigParser()
    config.read('whensmytransport.cfg')
    
    consumer_key = config.get(instance_name,'consumer_key')
    consumer_secret = config.get(instance_name,'consumer_secret')
    
    if not consumer_key or not consumer_secret:
        print "Could not find consumer key or secret, exiting"
        sys.exit(0)
    
    auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
    auth_url = auth.get_authorization_url()
    print 'Please authorize: ' + auth_url
    verifier = raw_input('PIN: ').strip()
    auth.get_access_token(verifier)
    print "key : %s" % auth.access_token.key
    print "secret : %s" % auth.access_token.secret

# List utils

def unique_values(seq):
    """
    Return unique values of sequence seq, according to ID function idfun. From http://www.peterbe.com/plog/uniqifiers-benchmark
    and modified. Values in seq must be hashable for this to work
    """
    seen = {} 
    result = [] 
    for item in seq: 
        if item in seen:
            continue 
        seen[item] = 1 
        result.append(item) 
    return result

if __name__ == "__main__":
    make_oauth_key()
    pass