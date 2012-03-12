#!/usr/bin/env python
# -*- coding: utf-8 -*-
#pylint: disable=W0142,R0201
"""

When's My Tube?
(c) 2011-12 Chris Applegate (chris AT qwghlm DOT co DOT uk)
Released under the MIT License

A Twitter bot that takes requests for a London Underground train, and replies with the real-time data from TfL on Twitter

Inherits many methods and data structures from WhensMyTransport and WhensMyRailTransport, including: loading the databases, config, connecting to Twitter,
reading @ replies, replying to them, checking new followers, following them back

This module just does work specific to Tube trains: Parsing & interpreting a Tube-specific message, and checking the TfL TrackerNet API and
formatting an appropriate reply to be sent back
"""
# Standard libraries of Python 2.6
import logging
import re
from datetime import datetime, timedelta
from pprint import pprint # For debugging

# From other modules in this package
from whensmytransport import WhensMyRailTransport
from lib.models import TubeTrain, NullDeparture
from lib.exceptions import WhensMyTransportException
from lib.listutils import unique_values
from lib.stringutils import capwords


class WhensMyTube(WhensMyRailTransport):
    """
    Main class devoted to checking for Tube-related Tweets and replying to them. Instantiate with no variables
    (all config is done in the file whensmytransport.cfg) and then call check_tweets()
    """
    def __init__(self, testing=None, silent=False):
        WhensMyRailTransport.__init__(self, 'whensmytube', testing, silent)

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
        )
        line_tuples = [(name, name) for name in line_names]
        # Handle abbreviated three-letter versions and sort out ampersands
        line_tuples += [(name[:3], name) for name in line_names]
        line_tuples += [(name.replace("&", "and"), name) for name in line_names]
        line_tuples += [('W&C', 'Waterloo & City'), ('H&C', 'Hammersmith & City',)]
        self.line_lookup = dict(line_tuples)

        # Regex used by tokenize_message to work out what is the bit of a Tweet specifying a line - all the words used in the above
        # FIXME Hammersmith, Piccadilly, Victoria and Waterloo are all first words of tube station names and may cause confusion
        tube_line_words = unique_values([word for line_name in line_names for word in line_name.split(' ')]) + ["Line", "and"]
        self.tube_line_regex = "(%s)" % "|".join(tube_line_words)

    def parse_message(self, message):
        """
        Parse a Tweet - tokenize it, and get the line, origin and destination specified by the user
        """
        (line_name, origin, destination) = self.tokenize_message(message, self.tube_line_regex)
        line_name = line_name and re.sub(" Line", "", line_name, flags=re.I)
        origin = origin and re.sub(" Station", "", origin, flags=re.I)
        destination = destination and re.sub(" Station", "", destination, flags=re.I)
        return ((line_name,), origin, destination)

    def get_departure_data(self, station, line_code, must_stop_at=None):
        """
        Take a station ID and a line ID, and get departure data for that station
        Returns a dictionary; keys are direction names, values lists of TubeTrain objects
        """
        # Check if the station is open and if so (it will throw an exception if not), summon the data
        self.check_station_is_open(station)
        # Circle line these days is coded H as it shares with the Hammersmith & City
        if line_code == 'O':
            line_code = 'H'

        tfl_url = "http://cloud.tfl.gov.uk/TrackerNet/PredictionDetailed/%s/%s" % (line_code, station.code)
        tube_data = self.browser.fetch_xml_tree(tfl_url)

        # Go through each platform and get data about every train arriving, including which direction it's headed
        trains_by_direction = {}
        publication_time = tube_data.find('WhenCreated').text
        publication_time = datetime.strptime(publication_time, "%d %b %Y %H:%M:%S")
        for platform in tube_data.findall('.//P'):
            platform_name = platform.attrib['N']
            direction = re.search("(North|East|South|West)bound", platform_name, re.I)
            rail = re.search("(Inner|Outer) Rail", platform_name, re.I)

            # Most stations tell us whether they are -bound in a certain direction
            if direction:
                direction = capwords(direction.group(0))
            # Some Circle/Central Line platforms called "Inner" and "Outer" Rail, which make no sense to customers, so I've manually
            # entered Inner and Outer attributes in the object (taken from the database) which translate from these into North/South/East/West
            elif rail:
                direction = station.__dict__[rail.group(1).lower()] + 'bound'
            else:
                # Some odd cases. Chesham and Chalfont & Latimer don't say anything at all for the platforms on the Chesham branch of the Met Line
                if station.code == "CHM":
                    direction = "Southbound"
                elif station.code == "CLF" and platform.attrib['Num'] == '3':
                    direction = "Northbound"
                else:
                    # The following stations will have "issues" with bidrectional platforms: North Acton, Edgware Road, Loughton, White City
                    # These are dealt with the below
                    direction = "Unknown"
                    logging.debug("Have encountered a platform without direction specified (%s)", platform_name)

            if direction != "Unknown":
                trains_by_direction[direction] = []

            # Use the filter function to filter out trains that are out of service, specials or National Rail first
            platform_trains = [t for t in platform.findall("T[@LN='%s']" % line_code) if filter_tube_trains(t)]
            for train in platform_trains:

                # Create a TubeTrain object
                destination = train.attrib['Destination']
                departure_delta = timedelta(seconds=int(train.attrib['SecondsTo']))
                departure_time = datetime.strftime(publication_time + departure_delta, "%H%M")
                set_number = train.attrib['SetNo']
                destination_code = train.attrib['DestCode']

                train_obj = TubeTrain(destination, direction, departure_time, set_number, line_code, destination_code)

                # Ignore any trains terminating at this station
                if self.get_station_by_station_name(line_code, train_obj.destination):
                    if self.get_station_by_station_name(line_code, train_obj.destination).name == station.name:
                        continue

                # Try and work out direction from destination. By luck, all the stations that have bidirectional
                # platforms are on an East-West line, so we just inspect the position of the destination's easting
                # and compare it to this station's
                if train_obj.direction == "Unknown":
                    if train_obj.destination == "Unknown":
                        continue
                    destination_station = self.get_station_by_station_name(line_code, train_obj.destination)
                    if not destination_station:
                        continue
                    else:
                        if destination_station.location_easting < station.location_easting:
                            train_obj.direction = "Westbound"
                        else:
                            train_obj.direction = "Eastbound"

                trains_by_direction[direction] = trains_by_direction.get(direction, []) + [train_obj]

        return self.cleanup_departure_data(trains_by_direction, lambda a: NullDeparture(a))

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


def filter_tube_trains(tube_xml_element):
    """
    Filter function for TrackerNet's XML elements, to get rid of misleading, out of service or downright bogus trains
    """
    destination = tube_xml_element.attrib['Destination']
    destination_code = tube_xml_element.attrib['DestCode']
    location = tube_xml_element.attrib.get('Location', '')

    # 546 and 749 appear to be codes for Out of Service http://wiki.opentfl.co.uk/TrackerNet_predictions_detailed
    if destination_code in ('546', '749'):
        return False
    # Trains in sidings are not much use to us
    if destination_code == '0' and location.find('Sidings') > -1:
        return False
    # No Specials or other Out of Service trains
    if destination in ('Special', 'Out Of Service'):
        return False
    # National Rail trains on Bakerloo & Metropolitan lines not that useful in this case
    if destination.startswith('BR') or destination in ('Network Rail', 'Chiltern TOC'):
        return False
    return True



if __name__ == "__main__":
    WMT = WhensMyTube()
    WMT.check_tweets()
