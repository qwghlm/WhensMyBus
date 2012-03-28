#!/usr/bin/env python
"""
Data browser for When's My Transport, with caching and JSON/XML parsing
"""
import json
import logging
import os
import urllib2
import time
from xml.dom.minidom import parseString
from xml.etree.ElementTree import fromstring

from lib.exceptions import WhensMyTransportException


#
# API URLs - for live APIs and test data we have cached for unit testing
#
HOME_DIR = os.path.dirname(os.path.abspath(__file__)) + '/..'
URL_SETS = {
    'live': {
        'BUS_URL':  "http://countdown.tfl.gov.uk/stopBoard/%s",
        'DLR_URL':  "http://www.dlrlondon.co.uk/xml/mobile/%s.xml",
        'TUBE_URL': "http://cloud.tfl.gov.uk/TrackerNet/PredictionDetailed/%s/%s",
        'STATUS_URL': "http://cloud.tfl.gov.uk/TrackerNet/StationStatus/IncidentsOnly",
    },
    'test': {
        'BUS_URL':  "file://" + HOME_DIR + "/testdata/bus/%s.json",
        'DLR_URL':  "file://" + HOME_DIR + "/testdata/dlr/%s.xml",
        'TUBE_URL': "file://" + HOME_DIR + "/testdata/tube/%s-%s.xml",
        'STATUS_URL': "file://" + HOME_DIR + "/testdata/tube/status.xml",
    }
}
CACHE_MAXIMUM_AGE = 30  # 30 seconds maximum cache age


class WMTURLProvider:
    """
    Simple wrapper that provides URLs for the TfL APIs, or test data depending on how we have set this up
    """
    #pylint: disable=R0903
    def __init__(self, use_test_data=False):
        if use_test_data:
            self.urls = URL_SETS['test']
        else:
            self.urls = URL_SETS['live']

    def __getattr__(self, key):
        return self.urls[key]


class WMTBrowser:
    """
    A simple JSON/XML fetcher with caching. Not designed to be used for many thousands of URLs, or for concurrent access
    """
    def __init__(self):
        self.opener = urllib2.build_opener()
        self.opener.addheaders = [('User-agent', 'When\'s My Transport?'),
                                  ('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8')]
        logging.debug("Starting up browser")
        self.cache = {}

    def fetch_url(self, url, default_exception_code):
        """
        Fetch a URL and returns the raw data as a string
        """
        # If URL is in cache and still considered fresh, fetch that
        if url in self.cache and (time.time() - self.cache[url]['time']) < CACHE_MAXIMUM_AGE:
            logging.debug("Using cached URL %s", url)
            url_data = self.cache[url]['data']
        # Else fetch URL and store
        else:
            logging.debug("Fetching URL %s", url)
            try:
                response = self.opener.open(url)
                url_data = response.read()
                self.cache[url] = {'data': url_data, 'time': time.time()}
            # Handle browsing error
            except urllib2.HTTPError, exc:
                logging.error("HTTP Error %s reading %s, aborting", exc.code, url)
                raise WhensMyTransportException(default_exception_code)
            except Exception, exc:
                logging.error("%s (%s) encountered for %s, aborting", exc.__class__.__name__, exc, url)
                raise WhensMyTransportException(default_exception_code)

        return url_data

    def fetch_json(self, url, default_exception_code='tfl_server_down'):
        """
        Fetch a JSON URL and returns Python object representation of it
        """
        json_data = self.fetch_url(url, default_exception_code)
        if json_data:
            try:
                obj = json.loads(json_data)
                return obj
            # If the JSON parser is choking, probably a 503 Error message in HTML so raise a ValueError
            except ValueError, exc:
                del self.cache[url]
                logging.error("%s encountered when parsing %s - likely not JSON!", exc, url)
                raise WhensMyTransportException(default_exception_code)
        else:
            return None

    def fetch_xml_tree(self, url, default_exception_code='tfl_server_down'):
        """
        Fetch an XML URL and returns Python object representation of it as an ElementTree
        """
        xml_data = self.fetch_url(url, default_exception_code)
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
            # If the XML parser is choking, probably a 503 Error message in HTML so raise a ValueError
            except Exception, exc:
                del self.cache[url]
                logging.error("%s encountered when parsing %s - likely not XML!", exc, url)
                raise WhensMyTransportException(default_exception_code)
        else:
            return None
