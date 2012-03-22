#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""

When's My Train?
(c) 2011-12 Chris Applegate (chris AT qwghlm DOT co DOT uk)
Released under the MIT License

A Twitter bot that takes requests for a Tube or DLR train, and replies with the real-time data from TfL on Twitter

Inherits many methods and data structures from WhensMyTransport, including: loading the databases, config, connecting to Twitter,
reading @ replies, replying to them, checking new followers, following them back

This module just does work specific to trains: Parsing & interpreting a train-specific message, and looking it up against the database of
stations and lines, checking the TfL Tube and DLR APIs and formatting an appropriate reply to be sent back
"""
from abc import ABCMeta
import argparse
import logging
from pprint import pprint

from whensmytransport import WhensMyTransport
from lib.dataparsers import parse_dlr_data, parse_tube_data
from lib.exceptions import WhensMyTransportException
from lib.models import RailStation, NullDeparture
from lib.stringutils import get_best_fuzzy_match
from lib.textparser import WMTTrainParser


LINE_NAMES = (
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

class WhensMyTrain(WhensMyTransport):
    """
    Class for the @WhensMyDLR and @WhensMyTube bots. This inherits from the WhensMyTransport and provides specialist functionality for when
    there is a limited number of stations and they have well-known, universally agreed names, which is normally railways and not buses.
    """
    __metaclass__ = ABCMeta

    def __init__(self, instance_name, testing=False):
        """
        Constructor
        """
        WhensMyTransport.__init__(self, instance_name, testing)
        self.allow_blank_tweets = instance_name == 'whensmydlr'
        self.parser = WMTTrainParser()

        # Build internal lookup table of possible line name -> "official" line name
        # Handle abbreviated three-letter versions and sort out ampersands
        line_tuples = [(name, name) for name in LINE_NAMES]
        line_tuples += [(name[:3], name) for name in LINE_NAMES]
        line_tuples += [(name.replace("&", "and"), name) for name in LINE_NAMES]
        line_tuples += [('W&C', 'Waterloo & City'), ('H&C', 'Hammersmith & City',), ('Docklands Light Railway', 'DLR')]
        self.line_lookup = dict(line_tuples)

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
            logging.debug("Attempting to get closest to position: %s", position)
            station = self.get_station_by_geolocation(line_code, position)
        else:
            logging.debug("Attempting to get a fuzzy match on placename %s", origin)
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
        if destination_name and not self.geodata.direct_route_exists(station.name, destination_name, line_code):
            raise WhensMyTransportException('no_direct_route', station.name, destination_name, line_name)

        # All being well, we can now get the departure data for this station and return it
        departure_data = self.get_departure_data(station, line_code, via=destination_name)
        if departure_data:
            return "%s to %s" % (station.get_abbreviated_name(), str(departure_data))
        else:
            if destination_name:
                raise WhensMyTransportException('no_trains_shown_to', line_name, station.name, destination_name)
            else:
                raise WhensMyTransportException('no_trains_shown', line_name, station.name)

    def get_station_by_geolocation(self, line_code, position):
        """
        Take a line and a tuple specifying latitude & longitude, and works out closest station
        """
        return self.geodata.find_closest(position, {'line': line_code}, RailStation)

    def get_station_by_station_name(self, line_code, origin):
        """
        Take a line and a string specifying origin, and work out matching for that name
        """
        if origin == "Unknown":
            return None
        else:
            return self.geodata.find_fuzzy_match({'line': line_code}, origin, RailStation)

    def get_canonical_station_name(self, line_code, origin):
        """
        Return just the string matching for a line code and origin name, or blank if none exists
        """
        station_obj = self.get_station_by_station_name(line_code, origin)
        return station_obj and station_obj.name or ""

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
            dlr_data = self.browser.fetch_xml_tree(self.urls.DLR_URL % station.code)
            departure_data = parse_dlr_data(dlr_data, station)
            null_constructor = lambda platform: NullDeparture("from " + platform)
        else:
            tube_data = self.browser.fetch_xml_tree(self.urls.TUBE_URL % (line_code, station.code))
            departure_data = parse_tube_data(tube_data, station, line_code, self.get_station_by_station_name)
            null_constructor = lambda direction: NullDeparture(direction)

        # Filter out trains terminating here, and any that do not serve our destination
        terminus = lambda departure: self.get_canonical_station_name(line_code, departure.get_clean_destination_name())
        # For any non-empty list of departures, filter out any that terminate here. Note that existing empty lists remain empty and are not deleted
        train_doesnt_terminate_here = lambda departure: terminus(departure) != station.name
        departure_data.filter(train_doesnt_terminate_here, delete_existing_empty_slots=False)
        # If we've specified a station to go via, filter out any that do not stop at that station, or mark for deletion. Note that unlike
        # the above, this will turn all existing empty lists into Nones (and thus deletable) as well
        if via:
            train_goes_via = lambda departure: self.geodata.direct_route_exists(station.name, terminus(departure), line_code, via)
            departure_data.filter(train_goes_via, delete_existing_empty_slots=True)
        departure_data.cleanup(null_constructor)
        return departure_data

    def check_station_is_open(self, station):
        """
        Check to see if a station is open, return True if so, throw an exception if not
        """
        try:
            status_data = self.browser.fetch_xml_tree(self.urls.STATUS_URL)
        # If we get an exception with fetching this data, don't worry about it
        except WhensMyTransportException:
            return True
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

if __name__ == "__main__":
    #pylint: disable=C0103
    parser = argparse.ArgumentParser(description="Run When's My Tube? or When's My DLR?")
    parser.add_argument("instance_name", action="store", help="Name of the instance to run (e.g. whensmytube, whensmydlr)")
    instance = parser.parse_args().instance_name
    if instance in ("whensmytube", "whensmydlr"):
        WMT = WhensMyTrain(instance)
        WMT.check_tweets()
    else:
        print "Error - %s is not a valid instance name" % instance
