#!/usr/bin/env python
#pylint: disable=C0103,R0201,W0231,W0142,R0903,R0914,R0913
"""
Geotools for WhensMyTransport. Include GeoCoders for Yahoo!, Bing and Google Maps, and functions
to convert between different co-ordinate systems
"""
import math
import urllib
from pprint import pprint

# Geocoders Define the URL and how to parse the resulting JSON object

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

    def get_query_url(self):
        """
        Fetch a URL to fetch geodata
        """
        for (key, value) in self.params.items():
            if isinstance(value, unicode):
                self.params[key] = value.encode('utf-8')

        query_url = self.url % urllib.urlencode(self.params)
        return query_url


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
                'key': api_key
            }

    def get_geocode_url(self, placename):
        """
        Get URL to access API, given a search query
        """
        self.params['query'] = placename + ', London'
        return self.get_query_url()

    def parse_geodata(self, obj):
        """
        Given a JSON object of geodata for a query, return list of matching place(s), each represented by a (latitude, longitude) tuple
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
                'appid': appid,
                'flags': 'JL',
                'locale': 'en_GB'
              }

    def get_geocode_url(self, placename):
        """
        Get URL to access API, given a search query
        """
        self.params['q'] = placename + ', London, UK'
        return self.get_query_url()

    def parse_geodata(self, obj):
        """
        Given a JSON object of geodata for a query, return list of matching place(s), each represented by a (latitude, longitude) tuple
        """
        if obj['ResultSet']['Error'] and int(obj['ResultSet']['Error']):
            return []
        if obj['ResultSet']['Found'] == 0:
            return []
        
        # Filter out non-UK results and the default object representing London
        resources = [o for o in obj['ResultSet']['Results'] if o['country'] == "United Kingdom" and o['woeid'] != '44418']
        points = [(float(r['latitude']), float(r['longitude'])) for r in resources]
        return points


class GoogleGeocoder(BaseGeocoder):
    """
    Geocoder for Google Maps
    """
    def __init__(self):
        """
        Constructor
        """
        self.url = 'http://maps.googleapis.com/maps/api/geocode/json?%s'
        self.params = {
                'region': 'uk',
                'sensor': 'false'
            }

    def get_geocode_url(self, placename):
        """
        Get URL to access API, given a search query
        """
        self.params['address'] = placename + ', London'
        return self.get_query_url()

    def parse_geodata(self, obj):
        """
        Given a JSON object of geodata for a query, return list of matching place(s), each represented by a (latitude, longitude) tuple
        """
        if not obj['results'] or obj['status'] == 'ZERO_RESULTS':
            return []

        results = obj['results']
        results = [r for r in results if r.get('formatted_address', '') != 'London, UK']
        points = [(r['geometry']['location']['lat'], r['geometry']['location']['lng']) for r in results]
        return points


# Thanks go to Chris Veness, as this is basically
# a translation of his JavaScript co-ordinate translation scripts
# http://www.movable-type.co.uk/scripts/latlong-gridref.html
#
# Original code (c) 2005-2010 Chris Veness
# Licensed under the Creative Commons BY-CC licence
#
# Python Translation (c) 2011 Chris Applegate  (chris AT qwghlm DOT co DOT uk)
# Released under the MIT License
#
# http://www.movable-type.co.uk/scripts/latlong-gridref.html
#
def LatLongToOSGrid(lat, lon):
    """
    Convert Geodesic co-ordinates to an OS grid reference, returned as an (eastings, northings) tuple
    """
    lat = math.radians(lat)
    lon = math.radians(lon)

    a = 6377563.396
    b = 6356256.910          # Airy 1830 major & minor semi-axes
    F0 = 0.9996012717                         # NatGrid scale factor on central meridian
    lat0 = math.radians(49)
    lon0 = math.radians(-2)  # NatGrid true origin
    N0 = -100000
    E0 = 400000                 # northing & easting of true origin, metres
    e2 = 1 - (b*b)/(a*a)                      # eccentricity squared
    n = (a-b)/(a+b)
    n2 = n*n
    n3 = n*n*n

    cosLat = math.cos(lat)
    sinLat = math.sin(lat)
    nu = a*F0/math.sqrt(1-e2*sinLat*sinLat)              # transverse radius of curvature
    rho = a*F0*(1-e2)/math.pow(1-e2*sinLat*sinLat, 1.5)  # meridional radius of curvature
    eta2 = nu/rho-1

    Ma = (1 + n + (5.0/4.0)*n2 + (5.0/4.0)*n3) * (lat-lat0)
    Mb = (3*n + 3*n*n + (21.0/8.0)*n3) * math.sin(lat-lat0) * math.cos(lat+lat0)
    Mc = ((15.0/8.0)*n2 + (15.0/8.0)*n3) * math.sin(2*(lat-lat0)) * math.cos(2*(lat+lat0))
    Md = (35.0/24.0)*n3 * math.sin(3*(lat-lat0)) * math.cos(3*(lat+lat0))
    M = b * F0 * (Ma - Mb + Mc - Md)              # meridional arc

    cos3lat = cosLat*cosLat*cosLat
    cos5lat = cos3lat*cosLat*cosLat
    tan2lat = math.tan(lat)*math.tan(lat)
    tan4lat = tan2lat*tan2lat

    I = M + N0
    II = (nu/2)*sinLat*cosLat
    III = (nu/24)*sinLat*cos3lat*(5-tan2lat+9*eta2)
    IIIA = (nu/720)*sinLat*cos5lat*(61-58*tan2lat+tan4lat)
    IV = nu*cosLat
    V = (nu/6)*cos3lat*(nu/rho-tan2lat)
    VI = (nu/120) * cos5lat * (5 - 18*tan2lat + tan4lat + 14*eta2 - 58*tan2lat*eta2)

    dLon = lon-lon0
    dLon2 = dLon*dLon
    dLon3 = dLon2*dLon
    dLon4 = dLon3*dLon
    dLon5 = dLon4*dLon
    dLon6 = dLon5*dLon

    N = I + II*dLon2 + III*dLon4 + IIIA*dLon6
    E = E0 + IV*dLon + V*dLon3 + VI*dLon5

    return (int(round(E)), int(round(N)))

def gridrefNumToLet(e, n, digits=10):
    """
    Convert Easting & Northing and return it as string representing the OS Grid Reference
    """
    e100k = math.floor(e/100000.0)
    n100k = math.floor(n/100000.0)

    if (e100k<0 or e100k>6 or n100k<0 or n100k>12):
        return ''

    # translate those into numeric equivalents of the grid letters
    l1 = (19-n100k) - (19-n100k)%5 + math.floor((e100k+10)/5)
    l2 = (19-n100k)*5%25 + e100k%5

    # compensate for skipped 'I' and build grid letter-pairs
    if (l1 > 7):
        l1 += 1
    if (l2 > 7):
        l2 += 1

    letPair = chr(int(l1) + ord('A')) + chr(int(l2) + ord('A'))

    # strip 100km-grid indices from easting & northing, and reduce precision
    e = math.floor((e%100000)/math.pow(10, 5-digits/2))
    n = math.floor((n%100000)/math.pow(10, 5-digits/2))

    gridRef = letPair + str(int(e)).zfill(digits/2) + str(int(n)).zfill(digits/2)

    return gridRef


def convertWGS84toOSGB36(lat, lon, height=0):
    """
    Convert a latitude & longitude from WGS84 (used by GPS) and return a (latitude, longitude)
    tuple of its equivalent in the OSGB36 system (used by OS maps)

    This allows us to convert from one model of the earth's spherality to another and make our
    geolocations *really* accurate
    """
    # ellipse parameters
    e = { 'WGS84':    { 'a': 6378137.0,   'b': 6356752.3142, 'f': 1/298.257223563 },
              'Airy1830': { 'a': 6377563.396, 'b': 6356256.910,  'f': 1/299.3249646   } }

    # helmert transform parameters
    h = { 'WGS84toOSGB36': { 'tx': -446.448,  'ty':  125.157,   'tz': -542.060,   # m
                               'rx':   -0.1502, 'ry':   -0.2470,  'rz':   -0.8421,  # sec
                               's':    20.4894 },                               # ppm
          'OSGB36toWGS84': { 'tx':  446.448,  'ty': -125.157,   'tz':  542.060,
                               'rx':    0.1502, 'ry':    0.2470,  'rz':    0.8421,
                               's':   -20.4894 } }

    return convert(lat, lon, height, e['WGS84'], h['WGS84toOSGB36'], e['Airy1830'])


def convert(lat, lon, height, e1, t, e2):
    """
    General-purpose spheroid conversion function
    """
    # -- convert polar to cartesian coordinates (using ellipse 1)
    lat = math.radians(lat)
    lon = math.radians(lon)

    a = e1['a']
    b = e1['b']

    sinPhi = math.sin(lat)
    cosPhi = math.cos(lat)
    sinLambda = math.sin(lon)
    cosLambda = math.cos(lon)
    H = height

    eSq = (a*a - b*b) / (a*a)
    nu = a / math.sqrt(1 - eSq*sinPhi*sinPhi)

    x1 = (nu+H) * cosPhi * cosLambda
    y1 = (nu+H) * cosPhi * sinLambda
    z1 = ((1-eSq)*nu + H) * sinPhi
    # -- apply helmert transform using appropriate params
    tx = t['tx']
    ty = t['ty']
    tz = t['tz']
    rx = t['rx']/3600 * math.pi/180
    # normalise seconds to radians
    ry = t['ry']/3600 * math.pi/180
    rz = t['rz']/3600 * math.pi/180
    s1 = t['s']/1e6 + 1 # normalise ppm to (s+1)

    # apply transform
    x2 = tx + x1*s1 - y1*rz + z1*ry
    y2 = ty + x1*rz + y1*s1 - z1*rx
    z2 = tz - x1*ry + y1*rx + z1*s1


    # -- convert cartesian to polar coordinates (using ellipse 2)

    a = e2['a']
    b = e2['b']
    precision = 4 / a
    # results accurate to around 4 metres

    eSq = (a*a - b*b) / (a*a)
    p = math.sqrt(x2*x2 + y2*y2)
    phi = math.atan2(z2, p*(1-eSq))
    phiP = 2*math.pi
    while (math.fabs(phi-phiP) > precision):
        nu = a / math.sqrt(1 - eSq*math.sin(phi)*math.sin(phi))
        phiP = phi
        phi = math.atan2(z2 + eSq*nu*math.sin(phi), p)

    Lambda = math.atan2(y2, x2)
    H = p/math.cos(phi) - nu

    # Rounding to 7 decimal places in a degree gives us about +/- 0.01m accuracy
    return (round(math.degrees(phi), 7), round(math.degrees(Lambda), 7), H)


def convertWGS84toOSEastingNorthing(latitude, longitude):
    """
    Convert a WGS84 (latitude, longitude) position, returns a (easting, northing) tuple
    """
    (new_latitude, new_longitude, _ignore) = convertWGS84toOSGB36(latitude, longitude)
    easting, northing = LatLongToOSGrid(new_latitude, new_longitude)
    return (easting, northing)


def heading_to_direction(heading):
    """
    Helper function to convert a heading (in degrees), returns a human-readable direction as a string
    """
    dirs = ('North', 'NE', 'East', 'SE', 'South', 'SW', 'West', 'NW')
    # North lies between -22 and +22, NE between 23 and 67, East between 68 and 112, etc
    i = ((int(heading) + 22) % 360) / 45
    return dirs[i]
