#!/usr/bin/env python
#pylint: disable=W0142
"""
Location-finding service for WhensMyTransport
"""
import logging
import cPickle as pickle
import os.path
from math import sqrt

from lib.stringutils import get_best_fuzzy_match
from lib.database import WMTDatabase
from lib.geo import convertWGS84toOSEastingNorthing
from pprint import pprint
from pygraph.algorithms.minmax import shortest_path

DB_PATH = os.path.normpath(os.path.dirname(os.path.abspath(__file__)) + '/../db/')


class WMTLocations():
    """
    Service object used to find stops or stations (locations) - given a position, exact match or fuzzy match,
    will return the best matching stop
    """
    def __init__(self, instance_name):
        self.database = WMTDatabase('%s.geodata.db' % instance_name)
        network_file = DB_PATH + '/%s.network.gr' % instance_name
        self.network = os.path.exists(network_file) and pickle.load(open(network_file))

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
        (where_statement, where_values) = self.make_where_statement(params)
        query = """
                SELECT (Location_Easting - %d)*(Location_Easting - %d) + (Location_Northing - %d)*(Location_Northing - %d) AS dist_squared,
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

    def find_fuzzy_match(self, params, fuzzy_match_query, returned_object):
        """
        Find the best fuzzy match to the query_string, querying the database with dictionary params, of the format
        { Column Name : value, }. Returns an object of class returned_object, or None if no fuzzy match found
        """
        # First off, try to get a match against station names in database
        # Users may not give exact details, so we try to match fuzzily
        (where_statement, where_values) = self.make_where_statement(params)
        rows = self.database.get_rows("SELECT * FROM locations WHERE %s" % where_statement, where_values)

        possible_matches = [returned_object(**row) for row in rows]
        best_match = get_best_fuzzy_match(fuzzy_match_query, possible_matches)
        if best_match:
            logging.debug("Fuzzy match found: %s", best_match.name)
            return best_match
        else:
            logging.debug("No match found for %s, sorry", fuzzy_match_query)
            return None

    def find_exact_match(self, params, returned_object):
        """
        Find the exact match for an item matching params. Returns an object of class returned_object, or None if no
        fuzzy match found
        """
        (where_statement, where_values) = self.make_where_statement(params)
        row = self.database.get_row("SELECT * FROM locations WHERE %s LIMIT 1" % where_statement, where_values)
        if row:
            return returned_object(**row)
        else:
            return None

    def describe_route(self, origin, destination, via=None, line=None):
        """
        Return the shortest route between origin and destination
        """
        if not self.network:
            raise ValueError("No network information available for these locations")
        if via:
            first_half = self.describe_route(origin, via, line=line)
            second_half = self.describe_route(via, destination, line=line)
            if first_half and second_half and second_half[0] == first_half[-1]:
                del second_half[0]
            return first_half + second_half

        origin += ":entrance"
        destination += ":exit"

        if line:
            network = self.network[line]
        else:
            network = self.network['All']
        shortest_path_dictionary = shortest_path(network, origin)[0]
        if origin not in shortest_path_dictionary:
            raise KeyError("Not found - no such node %s exists" % origin)
        if destination not in shortest_path_dictionary:
            raise KeyError("Not found - no such node %s exists" % destination)
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

    def direct_route_exists(self, origin, destination, via=None, line=None):
        """
        Return whether there is a direct route (i.e. one that does work without changing) on a list of stops
        """
        path_taken = self.describe_route(origin, destination, via=via, line=line)
        for i in range(1, len(path_taken)):
            # If same station twice in a row, then we must have a change
            if path_taken[i][0] == path_taken[i - 1][0]:
                return False
            # If visiting same station with one in between, then we must have visited a station & doubled back
            if i > 1 and path_taken[i][0] == path_taken[i - 2][0]:
                return False
        return True

    def check_existence_of(self, column, value):
        """
        Check to see if any row in the database has a value in column; returns True if exists, False if not
        """
        (where_statement, where_values) = self.make_where_statement({column: value})
        rows = self.database.get_rows("SELECT * FROM locations WHERE %s" % where_statement, where_values)
        return bool(rows)

    def get_max_value(self, column, params):
        """
        Return the maximum value of integer column out of the table given the params given
        """
        (where_statement, where_values) = self.make_where_statement(params)
        return int(self.database.get_value("SELECT MAX(\"%s\") FROM locations WHERE %s" % (column, where_statement), where_values))

    def make_where_statement(self, params):
        """
        Convert a dictionary of params and return a statement that can go after a WHERE
        """
        if not params:
            return (" 1 ", ())

        column_names = [row[1] for row in self.database.get_rows("PRAGMA table_info(locations)")]
        for column in params.keys():
            if column not in column_names:
                raise KeyError("Error: Database column %s not in our database" % column)
        # Construct our SQL statement
        where_statement = ' AND '.join(['"%s" = ?' % column for (column, value) in params.items()])
        where_values = tuple([value for (column, value) in params.items()])
        return (where_statement, where_values)
