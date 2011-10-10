#!/usr/bin/env python
#pylint: disable=R0201,W0231
"""
Geocoders for WhensMyBus. Define the URL and how to parse the resulting JSON object
"""
import urllib

class BaseGeocoder():
    """
    Base Geocoder which others inherit from
    """
    def __init__(self):
        """
        Constructor
        """
        self.url = ''
        self.params = {}
        return
        
class BingGeocoder(BaseGeocoder):
    """
    Geocoder for Bing Maps
    """
    def __init__(self, api_key):
        """
        Constructor
        """
        self.url = 'http://dev.virtualearth.net/REST/v1/Locations?%s'
        self.params = {
                'key' : api_key
            }

    def get_url(self, query):
        self.params['query'] = query + ', London'
        return self.url % urllib.urlencode(self.params)

    def parse_results(self, obj):
        """
        Parse results
        """
        if obj['resourceSets'][0]['estimatedTotal'] == 0:
            return []

        resources = [o for o in obj['resourceSets'][0]['resources'] if o['address']['countryRegion'] == 'United Kingdom']
        points = [tuple(r['point']['coordinates']) for r in resources]
        return points
        
class YahooGeocoder(BaseGeocoder):
    """
    Geocoder for Yahoo! Maps
    """
    def __init__(self, appid):
        """
        Constructor
        """
        self.url = 'http://where.yahooapis.com/geocode?%s'
        self.params = {
                'appid' : appid,
                'flags' : 'JL',
                'locale' : 'en_GB'
              }

    def get_url(self, query):
        self.params['q'] = query + ', London'
        return self.url % urllib.urlencode(self.params)

    def parse_results(self, obj):
        """
        Parse results
        """
        if obj['ResultSet']['Error'] or obj['ResultSet']['Found'] == 0:
            return []

        resources = [o for o in obj['ResultSet']['Results']]
        points = [(float(r['latitude']), float(r['longitude'])) for r in resources]
        return points            

class GoogleGeocoder(BaseGeocoder):
    """
    Geocoder for Google Maps
    """
    def __init__(self):

        self.url = 'http://maps.googleapis.com/maps/api/geocode/json?%s'
        self.params = {
                'region' : 'uk',
                'sensor' : 'false'
            }

    def get_url(self, query):
        self.params['address'] = query + ', London'
        return self.url % urllib.urlencode(self.params)

    def parse_results(self, obj):
        """
        Parse results
        """
        if not obj['results'] or obj['status'] == 'ZERO_RESULTS':
            return []
            
        results = obj['results']
        points = [(r['geometry']['location']['lat'], r['geometry']['location']['lng']) for r in results]
        return points