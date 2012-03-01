#!/usr/bin/env python
#pylint: disable=W0142

import logging
from math import sqrt
from lib.stringutils import get_best_fuzzy_match
from lib.database import WMTDatabase
from lib.geo import convertWGS84toOSEastingNorthing

#FIXME Docstrings could be better

class WMTLocations():
    """
    Service object used to find stops or stations for our bots - given a position, exact match or fuzzy match, will return the best matching
    stop
    """
    def __init__(self, instance_name):
        self.database = WMTDatabase('%s.geodata.db' % instance_name)

    def find_closest(self, position, params, ReturnedObject):
        """
        Find the closest location to the (lat, long) position specified, querying the database with dictionary params, of the format
        { Column Name : value }. Returns an object of class ReturnedObject, or None if none found nearby
        """
        # GPSes use WGS84 model of Globe, but Easting/Northing based on OSGB36, so convert to an easting/northing
        logging.debug("Position in WGS84 determined as lat/long: %s %s", position[0], position[1])
        easting, northing = convertWGS84toOSEastingNorthing(position)
        logging.debug("Translated into OS Easting %s, Northing %s", easting, northing)
        
        # Do a funny bit of Pythagoras to work out closest stop. We can't find square root of a number in sqlite
        # but then again, we don't need to, the smallest square will do. Sort by this column in ascending order
        # and find the first row
        query = """
                SELECT (Location_Easting - %d)*(Location_Easting - %d) + (Location_Northing - %d)*(Location_Northing - %d) AS dist_squared,
                      *
                FROM locations
                WHERE %s
                ORDER BY dist_squared
                LIMIT 1
                """ % (easting, easting, northing, northing, self.make_where_statement(params))
        row = self.database.get_row(query)
        if row:
            row['Distance'] = sqrt(row['dist_squared'])
            obj = ReturnedObject(**row)
            logging.debug("Have found nearest location %s", obj)
            return obj
        else:
            logging.debug("No location found near %s, sorry", position)
            return None

    def find_fuzzy_match(self, params, fuzzy_match_query, ReturnedObject):
        """
        Find the best fuzzy match to the query_string, querying the database with dictionary params, of the format
        { Column Name : value, }. Returns an object of class ReturnedObject, or None if no fuzzy match found
        """
        # First off, try to get a match against station names in database
        # Users may not give exact details, so we try to match fuzzily
        rows = self.database.get_rows("""
                                     SELECT * FROM locations
                                     WHERE %s
                                     """, (self.make_where_statement(params),))

        possible_matches = [ReturnedObject(**row) for row in rows]
        best_match = get_best_fuzzy_match(fuzzy_match_query, possible_matches)
        if best_match:
            logging.debug("Fuzzy match found! Found: %s", best_match.name)
            return best_match
        else:
            logging.debug("No match found for %s, sorry", fuzzy_match_query)
            return None

    def find_exact_match(self, params, ReturnedObject):
        """
        Find the exact match for an item matching params
        """
        row = self.database.get_row("SELECT * FROM locations WHERE %s LIMIT 1" % self.make_where_statement(params))
        if row:
            return ReturnedObject(**row)
        else:
            return None

    def check_existence_of(self, column, value):
        """
        Check to see if any row in the database has a value in column; returns True if exists, False if not
        """
        rows = self.database.get_rows("SELECT * FROM locations WHERE %s='%s'" % (column, value))
        return bool(rows) 

    def get_max_value(self, column, params):
        """
        Get the maximum value of integer column out of the table given the params given
        """
        return int(self.database.get_value("SELECT MAX(%s) FROM locations WHERE %s" % (column, self.make_where_statement(params)))) 

    def make_where_statement(self, params):
        """
        Convert a dictionary of params and return a statement that can go after a WHERE
        """
        # FIXME Check columns exist & escape values
        # Construct our SQL statement
        params = ["%s = '%s'" % (column, value) for (column, value) in params.items()]
        where_statement = ' AND '.join(params)
        return where_statement