#!/usr/bin/env python
"""
@whensmybus

A Twitter bot that takes requests for a bus timetable and @ replies on Twitter

Three ways of doing it

    @whensmybus 135
...will check the Tweet for its geocoded tag and work out what bus is going where

    @whensmybus 135 BP081
...will check the Tweet for that bus and that particular bus stop ID (found usually underneath the sign)

    @whensmybus 135 Limehouse Station
....will check for the name of the corresponding bus stop & route. Better to use the name on the stop itself than a general area

Will reply in the format

@username 135 LIMEHOUSE STATION 1834 East; LIMEHOUSE STATION 1855 West

My thanks go to Adrian Short for inspiring me to write this
http://adrianshort.co.uk/2011/09/08/open-data-for-everyday-life/

http://sourceforge.net/projects/sqlitebrowser/


"""
# Standard parts of Python 2.6
import json
import logging
import logging.handlers as logging_handlers
import re
import sqlite3
import string
import sys
import urllib2
import ConfigParser
import os
import time

# https://github.com/tweepy/tweepy
import tweepy

# From our file geotools.py
from geotools import LatLongToOSGrid, convertWGS84toOSGB36, gridrefNumToLet

# For debugging
from pprint import pprint

# command line & test options
TFL_API_URL = "http://countdown.tfl.gov.uk/stopBoard/%s"
VERSION_NUMBER = 0.10
WHENSMYBUS_HOME = os.path.split(sys.argv[0])[0] + '/'

# Exception we use to signal send an error to the user
class WhensMyBusException(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)

# Main class
class WhensMyBus:

    def __init__(self):

        try:
            config = ConfigParser.SafeConfigParser({ 'test_mode' : False, 'debug_level' : 'INFO' })
            config.read(WHENSMYBUS_HOME + 'whensmybus.cfg')
        except ConfigParser.Error:
            print "Can't find a config file! Please make sure there is a whensmybus.cfg file in this directory"
            sys.exit(1)

        # Set up some logging
        if len(logging.getLogger('').handlers) == 0:
            logging.basicConfig(level=logging.DEBUG, filename='/dev/null')

            # Set up some basic logging to stdout that shows info or debug level depending on user config
            console = logging.StreamHandler(sys.stdout)
            console.setLevel(logging.__dict__[config.get('whensmybus', 'debug_level')])

            console.setFormatter(logging.Formatter('%(message)s'))

            # Set up some proper logging to file that catches debugs
            logfile = os.path.abspath(WHENSMYBUS_HOME + 'logs/whensmybus.log')
            rotator = logging_handlers.TimedRotatingFileHandler(logfile, 'D', 1)
            rotator.setLevel(logging.DEBUG)
            rotator.setFormatter(logging.Formatter('%(asctime)s %(levelname)-8s %(message)s'))

            logging.getLogger('').addHandler(console)
            logging.getLogger('').addHandler(rotator)
            logging.debug("Initializing...")

        self.testing = config.get('whensmybus', 'test_mode')
        if self.testing:
            logging.info("In TEST MODE - No Tweets will be made!")

        # Load up the databases - one for the geodata, and one used a generic settings
        dbfilename = 'whensmybus.geodata.db'
        logging.debug("Opening database %s" % dbfilename)
        db = sqlite3.connect(WHENSMYBUS_HOME + dbfilename)
        db.row_factory = sqlite3.Row
        self.geodata = db.cursor()

        dbfilename = 'whensmybus.settings.db'
        logging.debug("Opening database %s" % dbfilename)
        self.settingsdb = sqlite3.connect(WHENSMYBUS_HOME + dbfilename)
        self.settingsdb.row_factory = sqlite3.Row
        self.settings = self.settingsdb.cursor()
        self.settings.execute("create table if not exists whensmybus_settings (setting_name unique, setting_value)")
        self.settingsdb.commit()

        # OAuth on Twitter
        self.username = config.get('whensmybus','username')
        
        logging.debug("Authenticating with Twitter")
        consumer_key = config.get('whensmybus','consumer_key')
        consumer_secret = config.get('whensmybus','consumer_secret')
        key = config.get('whensmybus','key')
        secret = config.get('whensmybus','secret')

        auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
        auth.set_access_token(key, secret)        
        self.api = tweepy.API(auth)
        #if not self.api.verify_credentials():
            #logging.error("Error: OAuth connection to Twitter failed, probably due to an invalid token")
            #sys.exit(1)
    
    def get_setting(self, setting_name):
        self.settings.execute("select setting_value from whensmybus_settings where setting_name = '%s'" % setting_name)
        row = self.settings.fetchone()
        return row and row[0]

    def update_setting(self, setting_name, setting_value):
        self.settings.execute("insert or replace into whensmybus_settings (setting_name, setting_value) values ('%s', '%s')" % (setting_name, setting_value))
        self.settingsdb.commit()
        
    """Check Tweets replied to"""
    def check_tweets(self):
    
        # Check For @ reply Tweets
        try:
            last_answered_tweet = self.get_setting('last_answered_tweet')
        except tweepy.error.TweepError:
            logging.error("Error: OAuth connection to Twitter failed, probably due to an invalid token")
            sys.exit(1)
        
        # FIXME: Rotate through pages if lots of them ?
        tweets = self.api.mentions(since_id=last_answered_tweet)
        
        if not tweets:
            logging.info("No new Tweets, exiting...")
        
        for tweet in tweets[::-1]:
            message = tweet.text
            username = tweet.user.screen_name
            logging.info("Have a message from %s: %s" % (username, message))

            try:
                # Ignore mentions that are not direct replies
                if not message.lower().startswith('@%s' % self.username):
                    logging.debug("Not a proper @ reply, skipping")
                    continue
                
                # Just get the guts of the message
                message = message[len('@%s ' % self.username):].strip()
                message = re.split(' +', message, 2)
                
                # Check to see if it's a valid bus number
                route_number = message[0]
                self.geodata.execute("SELECT * FROM routes WHERE Route=?", (route_number.upper(),))
                
                if not len(self.geodata.fetchall()):
                    raise WhensMyBusException("I couldn't recognise the number you gave me (%s) as a London bus" % route_number)
                
                route_number = route_number.upper()
                
                # Parse the message
                if len(message) >= 1:
                    # FIXME Use Tweetdeck's geolocation as well
                    # http://twitter.com/#!/alliekeith
                    # http://twitter.com/#!/NeilMackin
                    if tweet.coordinates:
                        logging.debug("Detect geolocation on Tweet, locating stops")
                        position = tweet.coordinates['coordinates'][::-1] # Twitter had longitude & latitude the wrong way round
                        relevant_stops = self.get_stops_by_geolocation(route_number, position)
                    elif tweet.place:
                        raise WhensMyBusException("The Place info on your Tweet isn't precise enough to find nearest bus stop. Try again with a GPS-enabled device")
                    else:
                        raise WhensMyBusException("Your Tweet wasn't geotagged. Please make sure you're using a GPS-equipped device and enable geolocation for Twitter")
                
                # If we have stops given to us
                if relevant_stops:
                    time_info = self.lookup_stops(relevant_stops, route_number)
                    reply = "@%s %s %s" % (username, route_number, "; ".join(time_info))
                else:
                    raise WhensMyBusException("I couldn't find any bus stops by that name")
            
            except WhensMyBusException as w:
                 reply = "@%s Sorry! %s" % (username, w.value)
            
            # Reply back to the user
            logging.info("Replying back to user with: %s" % reply)
            if not self.testing:
                try:
                    self.api.update_status(status=reply, in_reply_to_status_id=tweet.id)
                    self.update_setting('last_answered_tweet', tweet.id)
                except tweepy.error.TweepError:
                    continue

        self.report_twitter_limit_status()

    """Takes a route number and lat/lng and works out closest bus stops in each direction"""
    def get_stops_by_geolocation(self, route_number, position):
        
        logging.debug("Position in WGS84 determined as: %s %s" % tuple(position))
        
        # GPSes use WGS84 model of Globe, but Easting/Northing based on OSGB36
        position = convertWGS84toOSGB36(*position)
        logging.debug("Converted to OSGB36: %s %s" % tuple(position)[0:2])

        # Turn it into an Easting/Northing
        easting, northing = LatLongToOSGrid(position[0], position[1])
        gridref = gridrefNumToLet(easting, northing)
        
        # Grid reference provides us a way with checking to see if in the UK - it returns blank string if not in UK bounds
        if not gridref:
            raise WhensMyBusException("You do not appear to be located in the United Kingdom") # FIXME Narrow down to London?
            
        else:
            logging.debug("Translated into OS Easting %s, Northing %s" % (easting, northing))
            logging.debug("Translated into Grid Reference %s" % (gridref))

        self.geodata.execute("SELECT MAX(Run) FROM routes WHERE Route='%s'" % route_number)
        max_runs = int(self.geodata.fetchone()[0])
        
        relevant_stops = []
        for run in range(1, max_runs+1):
            query = """
                    SELECT (locations.Location_Easting - %d)*(locations.Location_Easting - %d) + (locations.Location_Northing - %d)*(locations.Location_Northing - %d) AS dist_squared,
                          Run,
                          locations.Heading,
                          Sms_Code,
                          locations.Stop_Name
                    FROM routes
                    JOIN locations ON routes.Stop_Code_LBSL = locations.Stop_Code_LBSL
                    WHERE Route='%s' AND Run='%s' AND routes.Virtual_Bus_Stop != 0 
                    ORDER BY dist_squared
                    LIMIT 1
                    """ % (easting, easting, northing, northing, route_number, run)
    
            self.geodata.execute(query)
            row = self.geodata.fetchone()
            relevant_stops.append([row[key] for key in ('Stop_Name', 'Sms_Code', 'Run', 'Heading')])
        
        if relevant_stops:
            logging.debug("Have found stop numbers: %s" % ', '.join([s[1] for s in relevant_stops]))
            return relevant_stops
        else:
            raise WhensMyBusException("I could not find any stops near you")
            return 
            
    # Browser that fetches the JSON data from the TfL website
    def lookup_stops(self, relevant_stops, route_number):
            
        opener = urllib2.build_opener()
        opener.addheaders = [('User-agent', 'When\'s My Bus? v. %s' % VERSION_NUMBER),
                             ('Accept','text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8')]
        time_info = []

        # Make requests to TfL for timetables for those bus stops
        # Parse requests and grab data for most relevant buses
        for (stop_name, stop_number, run, heading) in relevant_stops:
        
            # Get rid of TfL's symbols for Tube, National Rail & DLR
            for unwanted in ('<>', '#', '[DLR]'):
                stop_name = stop_name.replace(unwanted, '')
            stop_name = string.capwords(stop_name.strip())
        
            tfl_url = TFL_API_URL % stop_number
            logging.debug("Getting %s" % tfl_url)
    
            try:
                response = opener.open(tfl_url)
                json_data = response.read()
    
            except urllib2.HTTPError, e:
                logging.error("HTTP Error %s reading %s, aborting" % (e.code, tfl_url))
                raise WhensMyBusException("Sorry I can't access TfL's servers right now. Will try later")
    
            except httplib.HTTPException, e:
                logging.error("HTTP Exception %s reading %s, aborting" % (e, tfl_url))
                raise WhensMyBusException("Sorry I can't access TfL's servers right now. Will try later")
                            
            except Exception, e:
                logging.error("%s (%s) encountered for %s, aborting" % (e.__class__.__name__, e, tfl_url))
                raise WhensMyBusException("Sorry I can't access TfL's servers right now. Will try later")
    
            if json_data:
                try:
                    bus_data = json.loads(json_data)
                    arrivals = bus_data.get('arrivals', [])
                    if not arrivals:
                        if bus_data.get('stopBoardMessage', '') == "noPredictionsDueToSystemError":
                            raise WhensMyBusException("TfL's servers are down right now :( Try a bit later")
                        else:
                            logging.error("No arrival data for this stop right now")
                    else:
                        relevant_arrivals = [a for a in arrivals if (a['routeName'] == route_number or a['routeName'] == 'N' + route_number) and a['isRealTime'] and not a['isCancelled']]
                        if relevant_arrivals:
                            a = relevant_arrivals[0]
                            
                            scheduled_time =  a['scheduledTime'].replace(':', '')
                            if time.daylight:
                                hour = (int(scheduled_time[0:2]) + 1) % 24
                                scheduled_time = '%02d%s' % (hour, scheduled_time[2:4])
                                
                            time_info.append("%s to %s %s" % (stop_name, a['destination'], scheduled_time))
                        else:
                            time_info.append("%s: None shown going %s" % (stop_name, heading_to_direction(heading)))

                        # FIXME Need to deal with names that are too long
                        # @username = 16
                        # space = 1
                        # route no = 4
                        # " from " = 4
                        # ";" = 1
                        #  26 chars max
                        
                        # So we have 114 characters, or 57 per fragment to exploit
                
                        # Longest is HANWORTH AIR PARK LEISURE CENTRE & LIBRARY = 42 
                        # " to " = 4
                        # Longest terminus name = 20?
                        # " 2359" = 4
                        # = 72 maximum
                                        
                except ValueError, e:
                    logging.error("%s encountered when parsing %s - likely not JSON!" % (e, tfl_url))
        
        return time_info

    def report_twitter_limit_status(self):
        json = self.api.rate_limit_status()
        logging.debug("I have %s out of %s hits remaining this hour" % (json['remaining_hits'], json['hourly_limit']))
        logging.debug("Next reset time is %s" % (json['reset_time']))


# Helper function to convert a bus stop's heading to human-readable direction
def heading_to_direction(heading):
    dirs = ('North','NE','East','SE','South','SW','West','NW')
    i = ((int(heading)+22)%360)/45
    return dirs[i]
    
if __name__ == "__main__":
    wmb = WhensMyBus()
    wmb.check_tweets()
    # Some unit testing shit should go here