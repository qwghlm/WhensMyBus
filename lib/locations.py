#!/usr/bin/env python
#pylint: disable=W0142
"""
Location-finding service for WhensMyTransport
"""
import cPickle as pickle
import logging
from math import sqrt, ceil
import os.path
from pprint import pprint

# http://code.google.com/p/python-graph/
from pygraph.algorithms.minmax import shortest_path

from lib.models import Location, BusStop, RailStation
from lib.stringutils import get_best_fuzzy_match
from lib.database import WMTDatabase
from lib.geo import convertWGS84toOSEastingNorthing


DB_PATH = os.path.normpath(os.path.dirname(os.path.abspath(__file__)) + '/../db/')


class WMTLocations():
    """
    Service object used to find stops or stations (locations) - given a position, exact match or fuzzy match,
    will return the best matching stop. Subclassed and not called directly
    """
    def __init__(self, instance_name):
        self.database = WMTDatabase('%s.geodata.db' % instance_name)
        self.network = None
        self.returned_object = Location

    def find_closest(self, position, params):
        """
        Find the closest location to the (lat, long) position specified, querying the database with dictionary params, of the format
        { Column Name : value }. Returns an object of class returned_object, or None if none found nearby
        """
        # GPSes use WGS84 model of Globe, but Easting/Northing based on OSGB36, so convert to an easting/northing
        logging.debug("Position in WGS84 determined as lat/long: %s %s", position[0], position[1])
        easting, northing = convertWGS84toOSEastingNorthing(*position)
        logging.debug("Translated into OS Easting %s, Northing %s", easting, northing)

        # Do a funny bit of Pythagoras to work out closest stop. We can't find square root of a number in sqlite
        # but then again, we don't need to, the smallest square will do. Sort by this column in ascending order
        # and find the first row
        (where_statement, where_values) = self.database.make_where_statement('locations', params)
        query = """
                SELECT (location_easting - %d)*(location_easting - %d) + (location_northing - %d)*(location_northing - %d) AS dist_squared,
                      *
                FROM locations
                WHERE %s
                ORDER BY dist_squared
                LIMIT 1
                """ % (easting, easting, northing, northing, where_statement)
        row = self.database.get_row(query, where_values)
        if row:
            obj = self.returned_object(Distance=sqrt(row['dist_squared']), **row)
            logging.debug("Have found nearest location %s", obj)
            return obj
        else:
            logging.debug("No location found near %s, sorry", position)
            return None

    def find_fuzzy_match(self, stop_or_station_name, params):
        """
        Find the best fuzzy match to the query_string, querying the database with dictionary params, of the format
        { Column Name : value, }. Returns an object of class returned_object, or None if no fuzzy match found
        """
        if not stop_or_station_name or stop_or_station_name == "Unknown":
            return None
        # Try to get an exact match first against station names in database
        exact_params = params.copy()
        exact_params.update({'name': stop_or_station_name})
        exact_match = self.find_exact_match(exact_params)
        if exact_match:
            return exact_match

        # Users may not give exact details, so we try to match fuzzily
        (where_statement, where_values) = self.database.make_where_statement('locations', params)
        rows = self.database.get_rows("SELECT * FROM locations WHERE %s" % where_statement, where_values)
        possible_matches = [self.returned_object(**row) for row in rows]
        best_match = get_best_fuzzy_match(stop_or_station_name, possible_matches)
        if best_match:
            return best_match
        else:
            return None

    def find_exact_match(self, params):
        """
        Find the exact match for an item matching params. Returns an object of class returned_object, or None if no
        fuzzy match found
        """
        (where_statement, where_values) = self.database.make_where_statement('locations', params)
        row = self.database.get_row("SELECT * FROM locations WHERE %s LIMIT 1" % where_statement, where_values)
        if row:
            return self.returned_object(**row)
        else:
            return None


class BusStopLocations(WMTLocations):
    """
    Service object used to find bus stop - given a position, exact match or fuzzy match, will return the best matching BusStop
    """
    def __init__(self):
        WMTLocations.__init__(self, 'whensmybus')
        self.returned_object = BusStop


class RailStationLocations(WMTLocations):
    """
    Service object used to find rail stations - given a position, exact match or fuzzy match, will return the best matching RailStation
    """
    def __init__(self):
        WMTLocations.__init__(self, 'whensmytrain')
        network_file = DB_PATH + '/whensmytrain.network.gr'
        logging.debug("Opening network node data %s", os.path.basename(network_file))
        self.network = pickle.load(open(network_file))
        self.returned_object = RailStation

    def get_lines_serving(self, origin, destination=None):
        """
        Return a list of line codes that the RailStation origin is served by. If RailStation destination is specified, then
        only the quickest line that directly goes from origin to destination is returned as a single element of that list
        """
        rows = self.database.get_rows("SELECT name,line FROM locations WHERE code=?", (origin.code,))
        stations = [(RailStation(name), line) for (name, line) in rows]
        # If a destination exists, filter using it. If multiple ways of getting to destination,
        # sort by quickest and return line code for that
        if stations and destination:
            stations = [(station, line_code, self.length_of_route(station, destination, line_code)) for (station, line_code) in stations if self.direct_route_exists(station, destination, line_code)]
            stations.sort(lambda (a, b, c), (d, e, f): cmp(c, f))
            return [line_code for (station, line_code, time_taken) in stations][:1]
        else:
            return [line_code for (station, line_code) in stations]

    def length_of_route(self, origin, destination, line_code='All'):
        """
        Return the amount of time (in minutes) it is estimated to take to get from RailStation origin to RailStation destination
        via the specified line_code (if any)
        Returns -1 if there is no route between the two
        """
        origin_name = origin.name + ":entrance"
        destination_name = destination.name + ":exit"
        network = self.network[line_code]
        shortest_path_times = shortest_path(network, origin_name)[1]
        return int(ceil(shortest_path_times.get(destination_name, -1)))

    def describe_route(self, origin, destination, line_code='All', via=None):
        """
        Return the shortest route between origin and destination. Returns an list describing the route from start to finish
        Each element of the list is a tuple of form (station_name, direction, line_code)
        """
        if not self.network:
            return []
        if via:
            first_half = self.describe_route(origin, via, line_code)
            second_half = self.describe_route(via, destination, line_code)
            if first_half and second_half and second_half[0] == first_half[-1]:
                del second_half[0]
            return first_half + second_half

        origin_name = origin.name + ":entrance"
        destination_name = destination.name + ":exit"

        network = self.network[line_code]
        shortest_path_values = shortest_path(network, origin_name)
        shortest_path_dictionary = shortest_path_values[0]

        if origin_name not in shortest_path_dictionary or destination_name not in shortest_path_dictionary:
            return []
        # Shortest path dictionary consists of a dictionary of node names as keys, with the values
        # being the name of the node that preceded it in the shortest path
        # Count back from our destinaton, to the origin point
        path_taken = []
        while destination_name:
            path_taken.append(tuple(destination_name.split(":")))
            destination_name = shortest_path_dictionary[destination_name]

        # Trim off the entrance & exit nodes and reverse the list to get it in the right order
        path_taken = path_taken[1:-1][::-1]
        return path_taken

    def direct_route_exists(self, origin, destination, line_code, via=None, must_stop_at=None):
        """
        Return whether there is a direct route (i.e. one that does work without changing) between origin and destination on the line
        with code line_code (going via via if specified). If must_stop_at is specified, must also check that it stops at must_stop_at

        via and must_stop_at are subtly different - we force the route to go via via first, but then we check to see if it stops at must_stop_at
        """
        # Non-existent origin or direction must mean no route possible
        if not origin or not destination:
            return False
        # Trivial case - origin and destination being the same obviously True
        if origin == destination:
            return True

        path_taken = [stop[0] for stop in self.describe_route(origin, destination, line_code, via)]
        # If no path possible, then of course return False
        if not path_taken:
            return False
        # If must_stop_at not in the list, then return False
        if must_stop_at and must_stop_at.name not in path_taken:
            return False

        for i in range(1, len(path_taken)):
            # If same station twice in a row, then we must have a change
            if path_taken[i] == path_taken[i - 1]:
                return False
            # If visiting same station with one in between, then we must have visited a station & doubled back
            if i > 1 and path_taken[i] == path_taken[i - 2]:
                return False
        return True

    def is_correct_direction(self, direction, origin, destination, line_code):
        """
        Return True if a train going in this direction will directly reach the destination from the origin
        """
        if not direction:
            return False
        # If we can't find a match, or there doesn't exist direct route between the two, then can't be correct direction
        if not origin or not destination or not self.direct_route_exists(origin, destination, line_code):
            return False

        if direction.endswith("bound"):
            direction = direction[:-len("bound")]

        # Work out what direction we are going in via difference in east and west, and whether the
        # change in easting or northing is significant (in this case, it has to be at least half the change
        # in the other)
        east_diff = destination.location_easting - origin.location_easting
        north_diff = destination.location_northing - origin.location_northing
        east_diff_significant = abs(east_diff) > abs(0.5 * north_diff)
        north_diff_significant = abs(north_diff) > abs(0.5 * east_diff)
        if (direction == "East" and east_diff > 0 and east_diff_significant) or \
           (direction == "West" and east_diff < 0 and east_diff_significant) or \
           (direction == "North" and north_diff > 0 and north_diff_significant) or \
           (direction == "South" and north_diff < 0 and north_diff_significant):
            return True
        else:
            return False

    def does_train_stop_at(self, train, origin, desired_station):
        """
        Return True if a Train train from RailStation origin will stop at RailStation desired_station on the way
        """
        if train.destination:
            return self.direct_route_exists(origin, train.destination, train.line_code, via=train.via, must_stop_at=desired_station)
        elif train.direction:
            return self.is_correct_direction(train.direction, origin, desired_station, train.line_code)
        else:
            return False
