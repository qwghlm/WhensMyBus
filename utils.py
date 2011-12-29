#!/usr/bin/env python
"""
Utilities for WhensMyTransport
"""
import json
import logging
import os
import sqlite3
import sys
import time
import urllib2
import tweepy
import ConfigParser

from pprint import pprint

from exception_handling import WhensMyTransportException

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

# JSON stuff

class WMBBrowser:
    """
    A simple JSON fetcher with caching. Not designed to be used for many thousands of URLs, or for concurrent access
    """
    def __init__(self):
        """
        Start up
        """
        self.opener = urllib2.build_opener()
        self.opener.addheaders = [('User-agent', 'When\'s My Transport?'),
                                  ('Accept','text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8')]
        logging.debug("Starting up browser")
        
        self.cache = {}
    

    def fetch_json(self, url, exception_code='tfl_server_down'):
        """
        Fetches a JSON URL and returns Python object representation of it
        """
        if url in self.cache and (time.time() - self.cache[url]['time']) < 30:
            logging.debug("Using cached URL %s", url)
            json_data = self.cache[url]['data']
            
        else:
            logging.debug("Fetching URL %s", url)
            try:
                response = self.opener.open(url)
                json_data = response.read()
                self.cache[url] = { 'data' : json_data, 'time' : time.time() }
            # Handle browsing error
            except urllib2.HTTPError, exc:
                logging.error("HTTP Error %s reading %s, aborting", exc.code, url)
                raise WhensMyTransportException(exception_code)
            except Exception, exc:
                logging.error("%s (%s) encountered for %s, aborting", exc.__class__.__name__, exc, url)
                raise WhensMyTransportException(exception_code)
    
        # Try to parse this as JSON
        if json_data:
            try:
                obj = json.loads(json_data)
                return obj
            # If the JSON parser is choking, probably a 503 Error message in HTML so raise a ValueError
            except ValueError, exc:
                logging.error("%s encountered when parsing %s - likely not JSON!", exc, url)
                raise WhensMyTransportException(exception_code)  

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

# String util
def capwords(phrase):
    """
    Capitalize each word in a string. A word is defined as anything with a space separating it from the next word.   
    """
    return ' '.join([s.capitalize() for s in phrase.split(' ')])

if __name__ == "__main__":
    #make_oauth_key()
    pass