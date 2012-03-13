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
"""
# Standard libraries of Python 2.6
import logging
import re
from time import localtime
from pprint import pprint  # For debugging

# From other modules in this package
from whensmytransport import WhensMyTransport
from lib.geo import heading_to_direction
from lib.exceptions import WhensMyTransportException
from lib.models import BusStop, Bus, NullDeparture


class WhensMyBus(WhensMyTransport):
    """
    Main class devoted to checking for bus-related Tweets and replying to them.
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
            logging.debug("@ reply didn't contain a valid-looking bus number, skipping")
            return (None, None, None)

        return (route_numbers, origin, destination)

    def process_individual_request(self, route_number, origin, destination, position=None):
        """
        Take an individual route number, with either origin or position, and optional destination, and work out
        the stops and thus the appropriate times for the user, and return an appropriate reply to that user
        """
        # Not all valid-looking bus numbers are real bus numbers (e.g. 214, RV11) so we check database to make sure
        if not self.geodata.check_existence_of('Route', route_number):
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
                    logging.debug("Successfully found a match for destination %s, filtering down to runs: %s", destination, relevant_stops.keys())

            # We may not be able to find a destination, in which case - don't worry about this bit, and stick to unfiltered
            except WhensMyTransportException:
                logging.debug("Could not find a destination matching %s this route, skipping and not filtering results", destination)

        # If the above has found stops on this route, get data for each
        if relevant_stops:
            departure_data = self.get_departure_data(relevant_stops, route_number)
            if departure_data:
                return "%s %s" % (route_number, self.format_departure_data(departure_data))
            else:
                if destination:
                    raise WhensMyTransportException('no_buses_shown_to', route_number, destination)
                else:
                    raise WhensMyTransportException('no_buses_shown', route_number)
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
        # A route typically has two "runs" (e.g. one eastbound, one west) but some have more than that, so work out how many we have to check
        max_runs = self.geodata.get_max_value('Run', {'Route': route_number})
        relevant_stops = {}
        for run in range(1, max_runs + 1):
            stop = self.geodata.find_closest(position, {'Route': route_number, 'Run': run}, BusStop)
            if stop:
                relevant_stops[run] = stop
        logging.debug("Have found stop numbers: %s", ', '.join([stop.number for stop in relevant_stops.values()]))
        return relevant_stops

    def get_stops_by_stop_number(self, route_number, stop_number):
        """
        Take a route_number and a stop with ID stop_number, returns a dictionary with a single value. Key is the Run this stop sits on,
        value is the corresponding BusStop object
        """
        # Pull the stop ID out of the routes database and see if it exists
        if not self.geodata.check_existence_of('Bus_Stop_Code', stop_number):
            raise WhensMyTransportException('bad_stop_id', stop_number)

        # Try and get a match on it
        logging.debug("Attempting to get an exact match on stop SMS ID %s", stop_number)
        stop = self.geodata.find_exact_match({'Bus_Stop_Code': stop_number, 'Route': route_number}, BusStop)
        if stop:
            return {stop.run: stop}
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
        logging.debug("Attempting to get a match on placename %s", origin)
        relevant_stops = {}

        # A route typically has two "runs" (e.g. one eastbound, one west) but some have more than that, so work out how many we have to check
        max_runs = self.geodata.get_max_value('Run', {'Route': route_number})
        for run in range(1, max_runs + 1):
            best_match = self.geodata.find_fuzzy_match({'Route': route_number, 'Run': run}, origin, BusStop)
            if best_match:
                logging.info("Found stop name %s for Run %s via fuzzy matching", best_match.name, best_match.run)
                relevant_stops[run] = best_match

        # If we can't find a location for either Run 1 or 2, use the geocoder to find a location on that Run matching our name
        for run in (1, 2):
            if run not in relevant_stops and self.geocoder:
                logging.debug("No match found for run %s, attempting to get geocode placename %s", run, origin)
                geocode_url = self.geocoder.get_geocode_url(origin)
                try:
                    geodata = self.browser.fetch_json(geocode_url)
                except WhensMyTransportException:
                    logging.debug("Error connecting to geocoder, skipping")
                    continue

                points = self.geocoder.parse_geodata(geodata)
                if not points:
                    logging.debug("Could not find any matching location for %s", origin)
                    continue

                # For each of the places found, get the nearest stop that serves this run
                possible_stops = [self.get_stops_by_geolocation(route_number, point).get(run, None) for point in points]
                possible_stops = [stop for stop in possible_stops if stop]
                if possible_stops:
                    relevant_stops[run] = sorted(possible_stops)[0]
                    logging.debug("Have found stop named: %s", relevant_stops[run].name)
                else:
                    logging.debug("Found a location, but could not find a nearby stop for %s", origin)

        return relevant_stops

    def get_departure_data(self, relevant_stops, route_number, via=None):
        """
        Fetch the JSON data from the TfL website, for a dictionary of relevant_stops (each a BusStop object)
        and a particular route_number, and returns a dictionary of runs mapping to Bus objects
        """
        relevant_buses = {}
        stop_directions = {}
        for (run, stop) in relevant_stops.items():

            relevant_buses[run] = []
            stop_directions[run] = heading_to_direction(stop.heading)

            stop_name = stop.get_clean_name()
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
                for arrival in relevant_arrivals[:3]:
                    scheduled_time = arrival['scheduledTime'].replace(':', '')
                    # Short hack to get BST working
                    if localtime().tm_isdst:
                        hour = (int(scheduled_time[0:2]) + 1) % 24
                        scheduled_time = '%02d%s' % (hour, scheduled_time[2:4])

                    logging.debug("Run %s, stop %s produced bus to %s %s", run, stop_name, arrival['destination'], scheduled_time)
                    relevant_buses[run].append(Bus(stop_name, arrival['destination'], scheduled_time))
            else:
                logging.debug("Run %s, stop %s produced no buses", run, stop_name)

        # If the number of runs is 3 or 4, get rid of any without buses shown
        if len(relevant_buses) > 2:
            logging.debug("Number of runs is %s, removing any non-existent entries", len(relevant_buses))
            for (run, bus_list) in relevant_buses.items():
                if run > 2 and not bus_list:
                    del relevant_buses[run]

        return self.cleanup_departure_data(relevant_buses, lambda run: NullDeparture(stop_directions[run]))

# If this script is called directly, check our Tweets and Followers, and reply/follow as appropriate
if __name__ == "__main__":
    # Instantiate with no variables (all config is done in the file config.cfg) and then call check_tweets()
    WMB = WhensMyBus()
    WMB.check_tweets()
