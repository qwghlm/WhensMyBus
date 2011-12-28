#!/usr/bin/env python
"""
Utilities for WhensMyTransport
"""
import csv
import json
import logging
import os
import sqlite3
import sys
import urllib2
import subprocess
import tempfile
import tweepy
import ConfigParser

from xml.dom.minidom import parse, parseString

from pprint import pprint

from exception_handling import WhensMyTransportException
#from geotools import convertWGS84toOSGB36, LatLongToOSGrid, gridrefNumToLet

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

def fetch_json(url, exception_code='tfl_server_down'):
    """
    Fetches a JSON URL and returns Python object representation of it
    """
    opener = urllib2.build_opener()
    opener.addheaders = [('User-agent', 'When\'s My Transport?'),
                         ('Accept','text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8')]
    
    logging.debug("Fetching URL %s", url)
    try:
        response = opener.open(url)
        json_data = response.read()

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

# Data importing stuff

def import_bus_csv_to_db():
    """
    Utility script that produces the script for converting TfL's bus data CSV into sqlite
    
    If you are updating the database, you first have to download the CSV file
    from the TfL website. Signup as a developer here: http://www.tfl.gov.uk/businessandpartners/syndication/
    
    Save the the routes as ./sourcedata/routes.csv
    
    It takes the original file from TfL, fixes them to use semicolons (because sqlite's
    CSV parser is really dumb and can't deal with quoted values) and then converts it to
    the database file ./db/whensmybus.geodata.db
    
    The data used to be in two separate tables, one for locations and one for routes, but TfL
    have de-normalised the data and now all the relevant data is in the routes table. The locations
    table, sourced from a file called locations.csv, is thus deprecated
    
    """ 
    sql = ""

    for inputpath in ('routes.csv',):   # Used to be ('routes.csv', 'locations.csv',)
    
        # Fix CSV - replace commas with semi-colons, allow sqlite to import without cocking it all up
        inputfile = open('./sourcedata/' + inputpath)
        reader = csv.reader(inputfile)
        fieldnames = reader.next()  # Skip first line (fieldnames)
    
        outputpath = inputpath.replace('.csv', '.ssv')
        outputfile = open('./sourcedata/' + outputpath, 'w')
        writer = csv.writer(outputfile, delimiter=";")
        
        for line in reader:
            writer.writerow(line)
        outputfile.flush()
        outputfile.close()
    
        tablename = inputpath.split('.')[0]
    
        integer_values = ('Location_Easting',
                        'Location_Northing',
                        'Heading',
                        'Virtual_Bus_Stop',
                        'Run',
                        'Sequence',)
                        
        fieldnames = ['%s%s' % (f, integer_values.count(f) and ' INT' or '') for f in fieldnames]
        
        # Produce SQL for this table
        sql += "drop table if exists %s;\r\n" % tablename
        sql += "create table %s(%s);\r\n" % (tablename, ", ".join(fieldnames))
        sql += '.separator ";"\r\n'
        sql += ".import %s %s\r\n" % ('./sourcedata/' + outputpath, tablename)
        sql += "delete from %s WHERE Virtual_Bus_Stop;\r\n" % tablename
        sql += "\r\n"
    
    sql += "CREATE INDEX route_index ON routes (Route);\r\n"
    sql += "CREATE INDEX route_run_index ON routes (Route, Run);\r\n"
    sql += "CREATE INDEX route_stop_index ON routes (Route, Bus_Stop_Code);\r\n"
    
    tempf = tempfile.NamedTemporaryFile('w')
    tempf.write(sql)
    tempf.flush()
    print subprocess.check_output(["sqlite3", "./db/whensmybus.geodata.db"], stdin=open(tempf.name))

def import_tube_xml_to_db():
    """
    Utility script that produces the script for converting TfL's Tube data KML into a sqlite database
        
    Pulls together data from two files:
    
    1. The data for Tube station codes & line details, from:
    https://raw.github.com/blech/gae-fakesubwayapis-data/d365a8b56d7b5abfec378816e3d91fb901f0cc59/data/tfl/stops.txt
    corrected for station names, and saved as tube-references.csv
    
    2. The data for Tube station locations, originally from TfL but augmented with new data (Heathrow Terminal 5) 
    corrected for station names (e.g. Shepherd's Bush Market), and saved as tube-locations.kml
    
    """
    tablename = 'locations'
    
    fieldnames = ('name', 'code', 'line', 'easting INT', 'northing INT')
    
    sql = ""
    sql += "drop table if exists %s;\r\n" % tablename
    sql += "create table %s(%s);\r\n" % (tablename, ", ".join(fieldnames))

    stations = {}
    
    dom = parse(open('./sourcedata/tube-locations.kml'))
    station_geodata = dom.getElementsByTagName('Placemark')    
    for station in station_geodata:
    
        name = station.getElementsByTagName('name')[0].firstChild.data.strip().replace(' Station', '')
        style = station.getElementsByTagName('styleUrl')[0].firstChild.data.strip()
        # Ignore non-Tube stations
        if style != "#tubeStyle" or name in ('Shadwell', 'Wapping', 'Rotherhithe', 'Surrey Quays', 'New Cross', 'New Cross Gate'):
            continue

        coordinates = station.getElementsByTagName('coordinates')[0].firstChild.data.strip()
        (lon, lat) = tuple([float(c) for c in coordinates.split(',')[0:2]])
        (lat, lon) = convertWGS84toOSGB36(lat, lon)[:2]
        (easting, northing) = LatLongToOSGrid(lat, lon)
        gridref = gridrefNumToLet(easting, northing)
        stations[name.lower()] = { 'name' : name, 'easting' : easting, 'northing' : northing, 'code' : '', 'lines' : '' }

    g = open('./sourcedata/tube-references.csv')
    reader = csv.reader(g)
    fieldnames = reader.next()
    for line in reader:
        code = line[0]
        name = line[1]
        lines = line[-1].split(";")
        if name.lower() in stations:
            stations[name.lower()]['code'] = code
            stations[name.lower()]['lines'] = lines            
        else:
            print "Cannot find %s in geodata!" % name
        
    for station in stations.values():
        if not station['code']:
            print "Could not find a code for %s!" % station['name']
            sql += "insert into locations values (\"%s\");\r\n" % '", "'.join((station['name'], '', '', str(station['easting']), str(station['northing'])))
            
        else:
            for line in station['lines']:
                if line != 'O': 
                    sql += "insert into locations values (\"%s\");\r\n" % '", "'.join((station['name'], station['code'], line, str(station['easting']), str(station['northing'])))

    sql += "CREATE INDEX code_index ON locations (code);\r\n"

    tempf = tempfile.NamedTemporaryFile('w')
    tempf.write(sql)
    tempf.flush()
    print subprocess.check_output(["sqlite3", "./db/whensmytube.geodata.db"], stdin=open(tempf.name))

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
def capwords(str):
    """
    Capitalize each word in a string. A word is defined as anything with a space separating it from the next word.   
    """
    return ' '.join([s.capitalize() for s in str.split(' ')])

if __name__ == "__main__":
    #import_bus_csv_to_db()
    #make_oauth_key()
    import_tube_xml_to_db()
    pass