#!/usr/bin/env python
# -*- coding: utf-8 -*-
#pylint: disable=W0142,R0201
"""

When's My Bus?
(c) 2011-12 Chris Applegate (chris AT qwghlm DOT co DOT uk)
Released under the MIT License

A Twitter bot that takes requests for a bus, and replies with the real-time data from TfL on Twitter

Inherits many methods and data structures from WhensMyTransport, including: loading the databases, config, connecting to Twitter,
reading @ replies, replying to them, checking new followers, following them back

This module just does work specific to buses: Parsing & interpreting a bus-specific message, and looking it up against the database of
buses and routes, checking the TfL bus API and formatting an appropriate reply to be sent back

==Things to do==
 - Review all logging and make sure consistent with WhensMyTube

"""
# Standard libraries of Python 2.6
import re
from math import sqrt
from time import localtime
from pprint import pprint # For debugging

# From other modules in this package
from whensmytransport import WhensMyTransport
from geotools import convertWGS84toOSGrid, heading_to_direction
from exception_handling import WhensMyTransportException
from utils import cleanup_name_from_undesirables
from fuzzy_matching import get_best_fuzzy_match, get_bus_stop_name_similarity

class BusStop():
    #pylint: disable=C0103,R0903,W0613
    """
    Class representing a bus stop
    """
    def __init__(self, Stop_Name='', Bus_Stop_Code='', Heading=0, Sequence=1, Distance=0.0, **kwargs):
        self.name = Stop_Name
        self.number = Bus_Stop_Code
        self.heading = Heading
        self.sequence = Sequence
        self.distance_away = Distance

    def __cmp__(self, other):
        """
        Comparator function - measure by distance away from the point the user is
        """
        return cmp(self.distance_away, other.distance_away)


class WhensMyBus(WhensMyTransport):
    """
    Main class devoted to checking for bus-related Tweets and replying to them. Instantiate with no variables
    (all config is done in the file whensmytransport.cfg) and then call check_tweets()
    """
    def __init__(self, testing=None, silent=False):
        """
        Constructor for the WhensMyBus class
        """
        WhensMyTransport.__init__(self, 'whensmybus', testing, silent)

    def parse_message(self, message):
        """
        Parse a Tweet - tokenize it, and then pull out any bus numbers in it
        """
        route_regex = "[A-Z]{0,2}[0-9]{1,3}"
        (route_string, origin, destination) = self.tokenize_message(message, route_regex)
        # Count along from the start and match as many tokens that look like a route number
        route_token_matches = [re.match(route_regex, r, re.I) for r in route_string.split(' ')]
        route_numbers = [r.group(0).upper() for r in route_token_matches if r]
        if not route_numbers:
            self.log_debug("@ reply didn't contain a valid-looking bus number, skipping")
            return (None, None, None)

        return (route_numbers, origin, destination)

    def process_individual_request(self, route_number, origin, destination, position=None):
        """
        Take an individual route number, with either origin or position, and optional destination, and work out
        the stops and thus the appropriate times for the user, and return an appropriate reply to that user
        """
        # Not all valid-looking bus numbers are real bus numbers (e.g. 214, RV11) so we check database to make sure
        self.geodata.execute("SELECT * FROM routes WHERE Route=?", (route_number,))
        if not len(self.geodata.fetchall()):
            raise WhensMyTransportException('nonexistent_bus', route_number)

        # Dig out relevant stop for this route from the geotag, if provided
        if position:
            relevant_stops = self.get_stops_by_geolocation(route_number, position)
        # Else there will be an origin (either a number or a placename), so try parsing it properly
        else:
            relevant_stops = self.get_stops_by_stop_name(route_number, origin)

        # See if we can narrow down the runs offered by destination
        if relevant_stops and destination:
            try:
                possible_destinations = self.get_stops_by_stop_name(route_number, destination)
                if possible_destinations:
                    # Filter by possible destinations. For each Run, see if there is a stop matching the destination on the same 
                    # run; if that stop has a sequence number greater than this stop then it's a valid route, so include this run 
                    relevant_stops = dict([(run, stop) for (run, stop) in relevant_stops.items() 
                                            if run in possible_destinations and possible_destinations[run].sequence > stop.sequence])
                                            
            # We may not be able to find a destination, in which case - don't worry about this bit, and stick to unfiltered
            except WhensMyTransportException:
                pass

        # If the above has found stops on this route, get data for each
        if relevant_stops:
            departure_data = self.get_departure_data(relevant_stops, route_number)
            if departure_data:
                reply = "%s %s" % (route_number, "; ".join(departure_data))
                return reply
            else: 
                raise WhensMyTransportException('no_bus_arrival_data', route_number)
        else:
            if re.match('^[0-9]{5}$', origin):
                raise WhensMyTransportException('stop_id_not_found', route_number, origin)
            else:
                raise WhensMyTransportException('stop_name_not_found', route_number, origin)
        
    def get_stops_by_geolocation(self, route_number, position):
        """
        Take a route number and a tuple specifying latitude & longitude, and works out closest bus stops in each direction
        
        Returns a dictionary:
            Keys are numbers of the Run (usually 1 or 2, sometimes 3 or 4).
            Values are BusStop objects
        """
        # GPSes use WGS84 model of Globe, but Easting/Northing based on OSGB36, so convert to an easting/northing
        self.log_debug("Position in WGS84 determined as: %s %s", position[0], position[1])
        easting, northing, gridref = convertWGS84toOSGrid(position)
        self.log_debug("Translated into OS Easting %s, Northing %s, Grid Reference %s", easting, northing, gridref)
        
        # A route typically has two "runs" (e.g. one eastbound, one west) but some have more than that, so work out how many we have to check
        self.geodata.execute("SELECT MAX(Run) FROM routes WHERE Route=?", (route_number,))
        max_runs = int(self.geodata.fetchone()[0])
        
        relevant_stops = {}
        for run in range(1, max_runs+1):
        
            # Do a funny bit of Pythagoras to work out closest stop. We can't find square root of a number in sqlite
            # but then again, we don't need to, the smallest square will do. Sort by this column in ascending order
            # and find the first row
            query = """
                    SELECT (Location_Easting - %d)*(Location_Easting - %d) + (Location_Northing - %d)*(Location_Northing - %d) AS dist_squared,
                          Sequence,
                          Heading,
                          Bus_Stop_Code,
                          Stop_Name
                    FROM routes
                    WHERE Route='%s' AND Run='%s'
                    ORDER BY dist_squared
                    LIMIT 1
                    """ % (easting, easting, northing, northing, route_number, run)
    
            # Note we fetch the Bus_Stop_Code not the Stop_Code_LBSL value out of this row - this is the ID used in TfL's system
            self.geodata.execute(query)
            stop_data = self.geodata.fetchone()
            # Some Runs are non-existent (e.g. Routes that have a Run 4 but not a Run 3) so check if this is the case
            if stop_data:
                relevant_stops[run] = BusStop(Distance=sqrt(stop_data['dist_squared']), **stop_data)
        
        self.log_debug("Have found stop numbers: %s", ', '.join([stop.number for stop in relevant_stops.values()]))
        return relevant_stops
            
    def get_stops_by_stop_number(self, route_number, stop_number):
        """
        Take a route_number and a stop with ID stop_number, returns a dictionary with a single value. Key is the Run this stop sits on,
        value is the corresponding BusStop object
        """
        # Pull the stop ID out of the routes database and see if it exists
        self.geodata.execute("SELECT * FROM routes WHERE Bus_Stop_Code=?", (stop_number, ))
        stop = self.geodata.fetchone()
        if not stop:
            raise WhensMyTransportException('bad_stop_id', stop_number)

        # Try and get a match on it
        self.log_debug("Attempting to get an exact match on stop SMS ID %s", stop_number)
        self.geodata.execute("SELECT Run, Sequence, Heading, Bus_Stop_Code, Stop_Name FROM routes WHERE Bus_Stop_Code=? AND Route=?",
                             (stop_number, route_number))
        stop_data = self.geodata.fetchone()
        if stop_data:
            return { stop_data['Run'] : BusStop(**stop_data) }
        else:
            return {}
            
    def get_stops_by_stop_name(self, route_number, origin):
        """
        Take a route number and name of the origin, and work out closest bus stops in each direction
        
        Returns a dictionary. Keys are numbers of the Run (usually 1 or 2, sometimes 3 and 4). Values are BusStop objects
        """
        # First check to see if the name is actually an ID number - if so, then use the more precise numeric method above
        match = re.match('^[0-9]{5}$', origin)
        if match:
            return self.get_stops_by_stop_number(route_number, origin)

        # First off, try to get a match against bus stop names in database
        # Users may not give exact details, so we try to match fuzzily
        self.log_debug("Attempting to get a match on placename %s", origin)
        relevant_stops = {}
                     
        # A route typically has two "runs" (e.g. one eastbound, one west) but some have more than that, so work out how many we have to check
        self.geodata.execute("SELECT MAX(Run) FROM routes WHERE Route=?", (route_number,))
        max_runs = int(self.geodata.fetchone()[0])
        
        for run in range(1, max_runs+1):
            self.geodata.execute("""
                                 SELECT Stop_Name, Bus_Stop_Code, Heading, Sequence, Run FROM routes WHERE Route=? AND Run=?
                                 """, (route_number, run))
            rows = self.geodata.fetchall()
            # Some Runs are non-existent (e.g. Routes that have a Run 4 but not a Run 3) so check if this is the case
            if rows:
                best_match = get_best_fuzzy_match(origin, rows, 'Stop_Name', get_bus_stop_name_similarity)
                if best_match:
                    self.log_info("Found stop name %s for Run %s via fuzzy matching", best_match['Stop_Name'], best_match['Run'])
                    relevant_stops[run] = BusStop(**best_match)

        # If we can't find a location for either Run 1 or 2, use the geocoder to find a location on that Run matching our name
        for run in (1, 2):
            if run not in relevant_stops and self.geocoder:
                self.log_debug("No match found for run %s, attempting to get geocode placename %s", run, origin)
                geocode_url = self.geocoder.get_geocode_url(origin)
                geodata = self.browser.fetch_json(geocode_url)
                points = self.geocoder.parse_geodata(geodata)
                if not points:
                    self.log_debug("Could not find any matching location for %s", origin)
                    continue

                # For each of the places found, get the nearest stop that serves this run
                possible_stops = [self.get_stops_by_geolocation(route_number, point).get(run, None) for point in points]
                possible_stops = [stop for stop in possible_stops if stop]
                if possible_stops:
                    relevant_stops[run] = sorted(possible_stops)[0]
                    self.log_debug("Have found stop named: %s", relevant_stops[run].name)
                else:
                    self.log_debug("Found a location, but could not find a nearby stop for %s", origin)
            
        return relevant_stops
            
    def get_departure_data(self, relevant_stops, route_number):
        """
        Fetch the JSON data from the TfL website, for a list of relevant_stops (each a BusStop object)
        and a particular route_number, and returns the time(s) of buses on that route serving
        that stop(s)
        """
        time_info = []

        # Values in tuple correspond to what was added in relevant_stops.append() above
        for stop in relevant_stops.values():

            stop_name = cleanup_stop_name(stop.name)
            tfl_url = "http://countdown.tfl.gov.uk/stopBoard/%s" % stop.number
            bus_data = self.browser.fetch_json(tfl_url)
            arrivals = bus_data.get('arrivals', [])
            
            # Handle TfL's JSON-encoded error message
            if not arrivals and bus_data.get('stopBoardMessage', '') == "noPredictionsDueToSystemError":
                raise WhensMyTransportException('tfl_server_down')

            # Do the user a favour - check for both number and possible Night Bus version of the bus
            relevant_arrivals = [a for a in arrivals if (a['routeName'] == route_number or a['routeName'] == 'N' + route_number)
                                                        and a['isRealTime'] and not a['isCancelled']]
            if relevant_arrivals:
                arrival = relevant_arrivals[0]
                scheduled_time =  arrival['scheduledTime'].replace(':', '')
                # Short hack to get BST working
                if localtime().tm_isdst:
                    hour = (int(scheduled_time[0:2]) + 1) % 24
                    scheduled_time = '%02d%s' % (hour, scheduled_time[2:4])
                    
                time_info.append("%s to %s %s" % (stop_name, arrival['destination'], scheduled_time))
            else:
                time_info.append("%s: None shown going %s" % (stop_name, heading_to_direction(stop.heading)))

        # If the number of runs is 3 or 4, get rid of any "None shown"
        if len(time_info) > 2:
            self.log_debug("Number of runs is %s, removing any non-existent entries" , len(time_info))
            time_info = [t for t in time_info if t.find("None shown") == -1]

        return time_info


def cleanup_stop_name(stop_name):
    """
    Get rid of TfL's ASCII symbols for Tube, National Rail, DLR & Tram from a string, and capitalise all words
    """
    return cleanup_name_from_undesirables(stop_name, ('<>', '#', r'\[DLR\]', '>T<'))

# If this script is called directly, check our Tweets and Followers, and reply/follow as appropriate
if __name__ == "__main__":
    WMB = WhensMyBus()
    WMB.check_tweets()
    WMB.check_followers()
