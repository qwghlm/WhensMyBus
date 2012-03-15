#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""

When's My Rail?
(c) 2011-12 Chris Applegate (chris AT qwghlm DOT co DOT uk)
Released under the MIT License

A Twitter bot that takes requests for a Tube or DLR train, and replies with the real-time data from TfL on Twitter

Inherits many methods and data structures from WhensMyTransport, including: loading the databases, config, connecting to Twitter,
reading @ replies, replying to them, checking new followers, following them back

This module just does work specific to trains: Parsing & interpreting a train-specific message, and looking it up against the database of
stations and lines, checking the TfL Tube and DLR APIs and formatting an appropriate reply to be sent back
"""
from abc import ABCMeta
import logging
import re

from whensmytransport import WhensMyTransport
from lib.dataparsers import parse_dlr_data, parse_tube_data
from lib.exceptions import WhensMyTransportException
from lib.listutils import unique_values
from lib.models import RailStation, NullDeparture
from lib.stringutils import get_best_fuzzy_match


class WhensMyRailTransport(WhensMyTransport):
    """
    Parent class for the WhensMyDLR and WhensMyTube bots. This deals with common functionality between the two -
    namely looking up stations from a database given a position or name. This works best when there is a limited number of
    stations and they have well-known, universally agreed names, which is normally railways and not buses.
    """
    __metaclass__ = ABCMeta

    def __init__(self, instance_name, testing=False, silent=False):
        """
        Constructor
        """
        WhensMyTransport.__init__(self, instance_name, testing, silent)
        self.allow_blank_tweets = instance_name == 'whensmydlr'

        # Build internal lookup table of possible line name -> "official" line name
        line_names = (
            'Bakerloo',
            'Central',
            'Circle',
            'District',
            'Hammersmith & City',
            'Jubilee',
            'Metropolitan',
            'Northern',
            'Piccadilly',
            'Victoria',
            'Waterloo & City',
            'DLR',
        )
        line_tuples = [(name, name) for name in line_names]
        # Handle abbreviated three-letter versions and sort out ampersands
        line_tuples += [(name[:3], name) for name in line_names]
        line_tuples += [(name.replace("&", "and"), name) for name in line_names]
        line_tuples += [('W&C', 'Waterloo & City'), ('H&C', 'Hammersmith & City',), ('Docklands Light Railway', 'DLR')]
        self.line_lookup = dict(line_tuples)
        # Regex used by tokenize_message to work out what is the bit of a Tweet specifying a line - all the words used in the above
        # FIXME Hammersmith, Piccadilly, Victoria and Waterloo are all first words of tube station names and may cause confusion
        tube_line_words = unique_values([word for line_name in line_names for word in line_name.split(' ')]) + ["Line", "and"]
        self.tube_line_regex = "(%s)" % "|".join(tube_line_words)

    def process_individual_request(self, line_name, origin, destination, position):
        """
        Take an individual line, with either origin or position, and work out which station the user is
        referring to, and then get times for it
        """
        line = self.line_lookup.get(line_name, "") or get_best_fuzzy_match(line_name, self.line_lookup.values())
        if not line:
            raise WhensMyTransportException('nonexistent_line', line_name)
        line_code = get_line_code(line)
        if line != 'DLR':
            line_name += " Line"

        # Dig out relevant departure station for this line from the geotag, if provided, or else the station name
        if position:
            station = self.get_station_by_geolocation(line_code, position)
        else:
            station = self.get_station_by_station_name(line_code, origin)
        if not station:
            raise WhensMyTransportException('rail_station_name_not_found', origin, line_name)
        if station.code == "XXX":  # XXX is the code for a station that does not have TrackerNet data on the API
            raise WhensMyTransportException('rail_station_not_in_system', station.name)

        # If user has specified a destination, work out what it is, and check a direct route to it exists
        if destination:
            destination_name = self.get_canonical_station_name(line_code, destination) or None
        else:
            destination_name = None
        if destination_name and not self.geodata.direct_route_exists(station.name, destination_name, line=line):
            raise WhensMyTransportException('no_direct_route', station.name, destination_name, line_name)

        # All being well, we can now get the departure data for this station and return it
        departure_data = self.get_departure_data(station, line_code, via=destination_name)
        if departure_data:
            return "%s to %s" % (station.get_abbreviated_name(), self.format_departure_data(departure_data))
        else:
            if destination_name:
                raise WhensMyTransportException('no_trains_shown_to', line_name, station.name, destination_name)
            else:
                raise WhensMyTransportException('no_trains_shown', line_name, station.name)

    def get_station_by_geolocation(self, line_code, position):
        """
        Take a line and a tuple specifying latitude & longitude, and works out closest station
        """
        logging.debug("Attempting to get closest to position: %s", position)
        return self.geodata.find_closest(position, {'Line': line_code}, RailStation)

    def get_station_by_station_name(self, line_code, origin):
        """
        Take a line and a string specifying origin, and work out matching for that name
        """
        logging.debug("Attempting to get a fuzzy match on placename %s", origin)
        return self.geodata.find_fuzzy_match({'Line': line_code}, origin, RailStation)

    def get_canonical_station_name(self, line_code, origin):
        """
        Return just the string matching for a line code and origin name, or blank if none exists
        """
        station_obj = self.get_station_by_station_name(line_code, origin)
        return station_obj and station_obj.name or ""

    def parse_message(self, message):
        """
        Parse a Tweet - tokenize it, and get the line, origin and destination specified by the user
        """
        (line_name, origin, destination) = self.tokenize_message(message, self.tube_line_regex)
        line_name = line_name and re.sub(" Line", "", line_name, flags=re.I)
        origin = origin and re.sub(" Station", "", origin, flags=re.I)
        destination = destination and re.sub(" Station", "", destination, flags=re.I)

        if not line_name and self.instance_name == "whensmydlr":
            line_name = 'DLR'

        return ((line_name,), origin, destination)

    def get_departure_data(self, station, line_code, via=None):
        """
        Take a station object and a line ID, and get departure data for that station
        Returns a dictionary; keys are slot names (platform for DLR, direction for Tube), values lists of Train objects
        """
        #pylint: disable=W0108
        # Check if the station is open and if so (it will throw an exception if not), summon the data
        self.check_station_is_open(station)
        # Circle line these days is coded H as it shares with the Hammersmith & City
        if line_code == 'O':
            line_code = 'H'

        if line_code == 'DLR':
            dlr_url = "http://www.dlrlondon.co.uk/xml/mobile/%s.xml" % station.code
            dlr_data = self.browser.fetch_xml_tree(dlr_url)
            departure_data = parse_dlr_data(dlr_data, station)
            null_constructor = lambda platform: NullDeparture("from " + platform)
        else:
            tube_url = "http://cloud.tfl.gov.uk/TrackerNet/PredictionDetailed/%s/%s" % (line_code, station.code)
            tube_data = self.browser.fetch_xml_tree(tube_url)
            departure_data = parse_tube_data(tube_data, station, line_code)
            null_constructor = lambda direction: NullDeparture(direction)

        # Filter out trains terminating here, and any that do not serve our destination
        terminus = lambda departure: self.get_canonical_station_name(line_code, departure.destination)
        for (slot, departures) in departure_data.items():
            # For any non-empty list of departures, filter out any that terminate here. If as a result the list becomes empty, we mark the
            # slot as deletable by setting the value to None
            if departures:
                departure_data[slot] = [d for d in departures if terminus(d) != station.name] or None
            # If we've specified a station to go via, filter out any that do not stop at that station, or mark for deletion. Note that unlike
            # the above, this will turn all existing empty lists into Nones (and thus deletable) as well
            if via:
                departure_data[slot] = [d for d in departures if self.geodata.direct_route_exists(station.name, terminus(d), via=via)] or None
        departure_data = self.cleanup_departure_data(departure_data, null_constructor)
        return departure_data

    def check_station_is_open(self, station):
        """
        Check to see if a station is open, return True if so, throw an exception if not
        """
        status_url = "http://cloud.tfl.gov.uk/TrackerNet/StationStatus/IncidentsOnly"
        status_data = self.browser.fetch_xml_tree(status_url)
        for station_status in status_data.findall('StationStatus'):
            station_node = station_status.find('Station')
            status_node = station_status.find('Status')
            if station_node.attrib['Name'] == station.name and status_node.attrib['Description'] == 'Closed':
                raise WhensMyTransportException('tube_station_closed', station.name, station_status.attrib['StatusDetails'].strip().lower())
        return True


def get_line_code(line_name):
    """
    Return the TfL line code for the line requested
    """
    if line_name == 'DLR':
        return line_name
    elif line_name == 'Circle':
        return 'O'
    else:
        return line_name[0]

# FIXME Use command line options to specify instance name
if __name__ == "__main__":
    WMD = WhensMyRailTransport("whensmydlr")
    WMD.check_tweets()
