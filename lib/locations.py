#!/usr/bin/env python
#pylint: disable=W0142
"""
Location-finding service for WhensMyTransport
"""
from math import sqrt
import logging
import os.path
import cPickle as pickle

from pygraph.algorithms.minmax import shortest_path

from lib.stringutils import get_best_fuzzy_match
from lib.database import WMTDatabase
from lib.geo import convertWGS84toOSEastingNorthing
from lib.models import RailStation


DB_PATH = os.path.normpath(os.path.dirname(os.path.abspath(__file__)) + '/../db/')


class WMTLocations():
    """
    Service object used to find stops or stations (locations) - given a position, exact match or fuzzy match,
    will return the best matching stop
    """
    def __init__(self, instance_name, load_network=True):

        if instance_name == 'whensmybus':
            filename = 'whensmybus'
        elif instance_name == 'whensmytube' or instance_name == 'whensmydlr':
            filename = 'whensmytrain'
        else:
            logging.error("No data files exist for instance name %s, aborting", instance_name)
            raise RuntimeError("No data files exist for instance name %s, aborting" % instance_name)

        self.database = WMTDatabase('%s.geodata.db' % filename)
        network_file = DB_PATH + '/%s.network.gr' % filename
        if load_network and os.path.exists(network_file):
            logging.debug("Opening network node data %s", os.path.basename(network_file))
            self.network = pickle.load(open(network_file))
        else:
            self.network = None

    def find_closest(self, position, params, returned_object):
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
            obj = returned_object(Distance=sqrt(row['dist_squared']), **row)
            logging.debug("Have found nearest location %s", obj)
            return obj
        else:
            logging.debug("No location found near %s, sorry", position)
            return None

    def find_fuzzy_match(self, stop_or_station_name, params, returned_object):
        """
        Find the best fuzzy match to the query_string, querying the database with dictionary params, of the format
        { Column Name : value, }. Returns an object of class returned_object, or None if no fuzzy match found
        """
        if not stop_or_station_name or stop_or_station_name == "Unknown":
            return None
        # Try to get an exact match first against station names in database
        exact_params = params.copy()
        exact_params.update({'name': stop_or_station_name})
        exact_match = self.find_exact_match(exact_params, returned_object)
        if exact_match:
            return exact_match

        # Users may not give exact details, so we try to match fuzzily
        (where_statement, where_values) = self.database.make_where_statement('locations', params)
        rows = self.database.get_rows("SELECT * FROM locations WHERE %s" % where_statement, where_values)
        possible_matches = [returned_object(**row) for row in rows]
        best_match = get_best_fuzzy_match(stop_or_station_name, possible_matches)
        if best_match:
            return best_match
        else:
            return None

    def find_exact_match(self, params, returned_object):
        """
        Find the exact match for an item matching params. Returns an object of class returned_object, or None if no
        fuzzy match found
        """
        (where_statement, where_values) = self.database.make_where_statement('locations', params)
        row = self.database.get_row("SELECT * FROM locations WHERE %s LIMIT 1" % where_statement, where_values)
        if row:
            return returned_object(**row)
        else:
            return None

    def get_lines_serving(self, station_code):
        """
        Return an array of line codes that the station described by station_code is served by
        """
        rows = self.database.get_rows("SELECT line FROM locations WHERE code=?", (station_code,))
        return [row[0] for row in rows]

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

        origin += ":entrance"
        destination += ":exit"

        network = self.network[line_code]
        shortest_path_dictionary = shortest_path(network, origin)[0]
        if origin not in shortest_path_dictionary or destination not in shortest_path_dictionary:
            return []
        # Shortest path dictionary consists of a dictionary of node names as keys, with the values
        # being the name of the node that preceded it in the shortest path
        # Count back from our destinaton, to the origin point
        path_taken = []
        while destination:
            path_taken.append(tuple(destination.split(":")))
            destination = shortest_path_dictionary[destination]

        # Trim off the entrance & exit nodes and reverse the list to get it in the right order
        path_taken = path_taken[1:-1][::-1]
        return path_taken

    def direct_route_exists(self, origin, destination, line_code, via=None, must_stop_at=None):
        """
        Return whether there is a direct route (i.e. one that does work without changing) between origin and destination on the line
        with code line_code (going via via if specified). If must_stop_at is specified, must also check that it stops at must_stop_at

        via and must_stop_at are basically the same thing, for what it's worth, and are interchangeable
        """
        if not origin or not destination:
            return False
        path_taken = [stop[0] for stop in self.describe_route(origin, destination, line_code, via)]
        if must_stop_at and must_stop_at not in path_taken:
            return False
        for i in range(1, len(path_taken)):
            # If same station twice in a row, then we must have a change
            if path_taken[i] == path_taken[i - 1]:
                return False
            # If visiting same station with one in between, then we must have visited a station & doubled back
            if i > 1 and path_taken[i] == path_taken[i - 2]:
                return False
        return True

    def is_correct_direction(self, origin, destination, direction, line_code):
        """
        Return True if a train going in this direction will directly reach the destination from the origin
        """
        if not direction:
            return False
        if direction.endswith("bound"):
            direction = direction[:-len("bound")]
        origin = self.find_fuzzy_match(origin, {'line': line_code}, RailStation)
        destination = self.find_fuzzy_match(destination, {'line': line_code}, RailStation)

        # If we can't find a match, or there doesn't exist direct route between the two, then can't be correct direction
        if not origin or not destination or not self.direct_route_exists(origin.name, destination.name, line_code):
            return False
        if direction == "East" and origin.location_easting < destination.location_easting or \
           direction == "West" and origin.location_easting > destination.location_easting or \
           direction == "North" and origin.location_northing < destination.location_northing or \
           direction == "South" and origin.location_northing > destination.location_northing:
            return True
        else:
            return False

    def does_train_stop_at(self, origin, desired_station, train):
        """
        Return True if a train from origin bound for destination and/or in direction on line will stop at
        desired_station on the way
        """
        if train.destination and train.destination != "Unknown":
            return self.direct_route_exists(origin, train.destination, train.line_code, via=train.via, must_stop_at=desired_station)
        elif train.direction:
            return self.is_correct_direction(origin, desired_station, train.direction, train.line_code)
        else:
            return False
