#!/usr/bin/env python
"""
Data browser for When's My Transport
"""
import json
import logging
import urllib2
import time
from xml.dom.minidom import parseString
from xml.etree.ElementTree import fromstring

from lib.exceptions import WhensMyTransportException

class WMTBrowser:
    """
    A simple JSON/XML fetcher with caching. Not designed to be used for many thousands of URLs, or for concurrent access
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
        Fetch a URL and returns the raw data as a string
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
        Fetch a JSON URL and returns Python object representation of it
        """
        json_data = self.fetch_url(url, exception_code)
    
        # Try to parse this as JSON
        if json_data:
            try:
                obj = json.loads(json_data)
                return obj
            # If the JSON parser is choking, probably a 503 Error message in HTML so raise a ValueError
            except ValueError, exc:
                # FIXME Delete this from the cache
                logging.error("%s encountered when parsing %s - likely not JSON!", exc, url)
                raise WhensMyTransportException(exception_code)  

    def fetch_xml_tree(self, url, exception_code='tfl_server_down'):
        """
        Fetch an XML URL and returns Python object representation of it as an ElementTree
        """
        xml_data = self.fetch_url(url, exception_code)
        # Try to parse this as XML
        if xml_data:
            try:
                tree = fromstring(xml_data)
                namespace = '{%s}' % parseString(xml_data).firstChild.getAttribute('xmlns')               
                # Remove horrible namespace functionality
                if namespace:
                    for elem in tree.getiterator():
                        if elem.tag.startswith(namespace):
                            elem.tag = elem.tag[len(namespace):]
                return tree
            except Exception, exc:
                # FIXME Delete this from the cache
                logging.error("%s encountered when parsing %s - likely not XML!", exc, url)
                raise WhensMyTransportException(exception_code)