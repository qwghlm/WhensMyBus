#!/usr/bin/env python
# -*- coding: utf-8 -*-
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
from pprint import pprint  # For debugging

# From other modules in this package
from whensmytransport import WhensMyTransport
from lib.dataparsers import parse_bus_data
from lib.geo import heading_to_direction
from lib.exceptions import WhensMyTransportException
from lib.models import BusStop, NullDeparture, DepartureCollection
from lib.textparser import WMTBusParser


class WhensMyBus(WhensMyTransport):
    """
    Class for the @WhensMyBus bot. This inherits from the WhensMyTransport and provides specialist functionality for when
    there is are a lot of stops, their names may now be known by users, and their location corresponds with streets
    """
    def __init__(self, testing=False):
        """
        Constructor for the WhensMyBus class
        """
        WhensMyTransport.__init__(self, 'whensmybus', testing)
        self.parser = WMTBusParser()

    def process_individual_request(self, route_number, origin, destination, direction, position=None):
        """
        Take an individual route number, with either origin or position, and optional destination, and work out
        the stops and thus the appropriate times for the user, and return an appropriate reply to that user

        NB direction is not used for this class
        """
        # Not all valid-looking bus numbers are real bus numbers (e.g. 214, RV11) so we check database to make sure
        route_number = route_number.upper()
        if not self.geodata.database.check_existence_of('locations', 'route', route_number):
            raise WhensMyTransportException('nonexistent_bus', route_number)

        # Dig out relevant bus stop for this route from the geotag, if provided, or else the stop name
        if position:
            relevant_stops = self.get_stops_by_geolocation(route_number, position)
        else:
            relevant_stops = self.get_stops_by_stop_name(route_number, origin)
        if not relevant_stops:
            if re.match('^[0-9]{5}$', origin):
                raise WhensMyTransportException('stop_id_not_found', route_number, origin)
            else:
                raise WhensMyTransportException('stop_name_not_found', route_number, origin)

        # See if we can narrow down the runs offered by destination
        if destination:
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
        departures = self.get_departure_data(relevant_stops, route_number)
        if departures:
            return "%s %s" % (route_number, str(departures))
        else:
            if destination:
                raise WhensMyTransportException('no_buses_shown_to', route_number, destination)
            else:
                raise WhensMyTransportException('no_buses_shown', route_number)

    def get_stops_by_geolocation(self, route_number, position):
        """
        Take a route number and a tuple specifying latitude & longitude, and works out closest bus stops in each direction

        Returns a dictionary:
            Keys are numbers of the Run (usually 1 or 2, sometimes 3 or 4).
            Values are BusStop objects
        """
        # A route typically has two "runs" (e.g. one eastbound, one west) but some have more than that, so work out how many we have to check
        logging.debug("Attempting to get a geomatch on location %s", position)
        max_runs = self.geodata.database.get_max_value('locations', 'run', {'route': route_number})
        logging.debug("Have found total of %s runs", max_runs)
        relevant_stops = {}
        for run in range(1, max_runs + 1):
            stop = self.geodata.find_closest(position, {'route': route_number, 'run': run}, BusStop)
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
        if not self.geodata.database.check_existence_of('locations', 'bus_stop_code', stop_number):
            raise WhensMyTransportException('bad_stop_id', stop_number)

        # Try and get a match on it
        logging.debug("Attempting to get an exact match on stop SMS ID %s", stop_number)
        stop = self.geodata.find_exact_match({'bus_stop_code': stop_number, 'route': route_number}, BusStop)
        if stop:
            logging.debug("Have found stop number: %s", stop.number)
            return {stop.run: stop}
        else:
            logging.debug("No such bus stop found")
            return {}

    def get_stops_by_stop_name(self, route_number, stop_name):
        """
        Take a route number and name of the origin, and work out closest bus stops in each direction

        Returns a dictionary. Keys are numbers of the Run (usually 1 or 2, sometimes 3 and 4). Values are BusStop objects
        """
        # First check to see if the name is actually an ID number - if so, then use the more precise numeric method above
        match = re.match('^[0-9]{5}$', stop_name)
        if match:
            return self.get_stops_by_stop_number(route_number, stop_name)

        # First off, try to get a match against bus stop names in database
        # Users may not give exact details, so we try to match fuzzily
        logging.debug("Attempting to get a match on placename %s", stop_name)
        relevant_stops = {}

        # A route typically has two "runs" (e.g. one eastbound, one west) but some have more than that, so work out how many we have to check
        max_runs = self.geodata.database.get_max_value('locations', 'run', {'route': route_number})
        for run in range(1, max_runs + 1):
            best_match = self.geodata.find_fuzzy_match(stop_name, {'route': route_number, 'run': run}, BusStop)
            if best_match:
                logging.info("Found stop name %s for Run %s by fuzzy matching", best_match.name, best_match.run)
                relevant_stops[run] = best_match

        # If we can't find a location for either Run 1 or 2, use the geocoder to find a location on that Run matching our name
        for run in (1, 2):
            if run not in relevant_stops and self.geocoder:
                logging.debug("No match found for run %s, attempting to get geocode placename %s", run, stop_name)
                geocode_url = self.geocoder.get_geocode_url(stop_name)
                try:
                    geodata = self.browser.fetch_json(geocode_url)
                except WhensMyTransportException:
                    logging.debug("Error connecting to geocoder, skipping")
                    continue

                points = self.geocoder.parse_geodata(geodata)
                if not points:
                    logging.debug("Could not find any matching location for %s", stop_name)
                    continue

                logging.debug("Have found %s matching points", len(points))
                # For each of the places found, get the nearest stop that serves this run
                possible_stops = [self.get_stops_by_geolocation(route_number, point).get(run, None) for point in points]
                possible_stops = [stop for stop in possible_stops if stop]
                if possible_stops:
                    relevant_stops[run] = sorted(possible_stops)[0]
                    logging.debug("Have found stop named: %s", relevant_stops[run].name)
                else:
                    logging.debug("Found a location, but could not find a nearby stop for %s", stop_name)

        return relevant_stops

    def get_departure_data(self, relevant_stops, route_number, must_stop_at=None):
        """
        Fetch the JSON data from the TfL website, for a dictionary of relevant_stops (each a BusStop object)
        and a particular route_number, and returns a DepartureCollection containing Bus objects

        must_stop_at is ignored; filtering by direction has already been done by process_individual_request()
        """
        stop_directions = dict([(run, heading_to_direction(stop.heading)) for (run, stop) in relevant_stops.items()])
        departures = DepartureCollection()
        for (run, stop) in relevant_stops.items():
            tfl_url = self.urls.BUS_URL % stop.number
            bus_data = self.browser.fetch_json(tfl_url)
            departures[stop] = parse_bus_data(bus_data, route_number)
            if departures[stop]:
                logging.debug("Stop %s produced buses: %s", stop.get_clean_name(), ', '.join([str(bus) for bus in departures[stop]]))
            else:
                logging.debug("Stop %s produced no buses", stop.get_clean_name())

        # If the number of runs is 3 or more, get rid of any without buses shown
        if len(departures) > 2:
            logging.debug("Number of runs is %s, removing any non-existent entries", len(departures))
            for run in range(3, max(relevant_stops.keys()) + 1):
                if run in relevant_stops.keys() and not departures[relevant_stops[run]]:
                    del departures[relevant_stops[run]]

        null_constructor = lambda stop: NullDeparture(stop_directions[stop.run])
        departures.cleanup(null_constructor)
        return departures

# If this script is called directly, check our Tweets and Followers, and reply/follow as appropriate
# Instantiate with no variables (all config is done in the file config.cfg
if __name__ == "__main__":
    try:
        WMB = WhensMyBus()
        WMB.check_tweets()
    except RuntimeError as err:
        print err
