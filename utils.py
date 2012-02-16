#!/usr/bin/env python
"""
Utilities for WhensMyTransport
"""
import json
import logging
import os
import re
import sqlite3
import sys
import time
import urllib2
import tweepy
import ConfigParser
import xml.dom.minidom

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

# Twitter stuff

def is_direct_message(tweet):
    """
    Returns True if a Tweet object is that of Tweepy's Direct Message, False if any other kind
    """
    return isinstance(tweet, tweepy.models.DirectMessage)

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
        
    def fetch_url(self, url, exception_code):
        """
        Fetches a URL and returns the raw data as a string
        """
        if url in self.cache and (time.time() - self.cache[url]['time']) < 30:
            logging.debug("Using cached URL %s", url)
            url_data = self.cache[url]['data']
            
        else:
            logging.debug("Fetching URL %s", url)
            try:
                response = self.opener.open(url)
                url_data = response.read()
                self.cache[url] = { 'data' : url_data, 'time' : time.time() }
            # Handle browsing error
            except urllib2.HTTPError, exc:
                logging.error("HTTP Error %s reading %s, aborting", exc.code, url)
                raise WhensMyTransportException(exception_code)
            except Exception, exc:
                logging.error("%s (%s) encountered for %s, aborting", exc.__class__.__name__, exc, url)
                raise WhensMyTransportException(exception_code)
                
        return url_data

    def fetch_json(self, url, exception_code='tfl_server_down'):
        """
        Fetches a JSON URL and returns Python object representation of it
        """
        json_data = self.fetch_url(url, exception_code)
    
        # Try to parse this as JSON
        if json_data:
            try:
                obj = json.loads(json_data)
                return obj
            # If the JSON parser is choking, probably a 503 Error message in HTML so raise a ValueError
            except ValueError, exc:
                logging.error("%s encountered when parsing %s - likely not JSON!", exc, url)
                raise WhensMyTransportException(exception_code)  

    def fetch_xml(self, url, exception_code='tfl_server_down'):
        """
        Fetches an XML URL and returns Python object representation of the DOM
        """
        xml_data = self.fetch_url(url, exception_code)
    
        # Try to parse this as XML
        if xml_data:
            try:
                dom = xml.dom.minidom.parseString(xml_data)
                return dom
            except Exception, exc:
                logging.error("%s encountered when parsing %s - likely not XML!", exc, url)
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

# String utils

def capwords(phrase):
    """
    Capitalize each word in a string. A word is defined as anything with a space separating it from the next word.   
    """
    not_to_be_capitalized = ('via',)
    capitalized = ' '.join([s in not_to_be_capitalized and s or s.capitalize() for s in phrase.split(' ')])
    return capitalized
        
def cleanup_name_from_undesirables(name, undesirables):
    """
    Clean out every word in the iterable undesirables from the name supplied, and capitalise
    """
    name = name.upper()
    for undesirable in undesirables:
        name = name.replace(undesirable.upper(), '')
    name = re.sub(r' +', ' ', name)
    return capwords(name.strip())

def cleanup_stop_name(stop_name):
    """
    Get rid of TfL's ASCII symbols for Tube, National Rail, DLR & Tram from a string, and capitalise all words
    """
    return cleanup_name_from_undesirables(stop_name, ('<>', '#', '[DLR]', '>T<'))
    
def cleanup_station_name(station_name):
    """
    Get rid of TfL's odd designations
    """
    return cleanup_name_from_undesirables(station_name, ('sidings', 'then depot', 'depot', 'ex barnet branch', '/ london road', '(plat. 1)', ' loop '))
    
def filter_tube_trains(tube_xml_node):
    """
    Filter function for TfL's tube train XML tags, to get rid of misleading or bogus trains
    """
    destination = tube_xml_node.getAttribute('Destination')
    destination_code = tube_xml_node.getAttribute('DestCode')
    location = tube_xml_node.getAttribute('Location')
    
    # 546 and 749 appear to be codes for Out of Service
    if destination_code in ('546', '749'):
        return False
    # Trains in Sidings are not much use to us
    if destination_code == '0' and location.find('Sidings') > -1:
        return False
    if destination in ('Special', 'Out Of Service'):
        return False
    if destination.startswith('BR') or destination in ('Network Rail', 'Chiltern TOC'):
        return False
        
    return True
    
# List utils 
def unique_values(seq, idfun=lambda a:a):
    """
    Return unique values of sequence seq, according to ID function idfun. From http://www.peterbe.com/plog/uniqifiers-benchmark
    """
    seen = {} 
    result = [] 
    for item in seq: 
        marker = idfun(item)
        if marker in seen:
            continue 
        seen[marker] = 1 
        result.append(item) 
    return result

if __name__ == "__main__":
    #make_oauth_key()
    pass