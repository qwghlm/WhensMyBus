#!/usr/bin/env python
# -*- coding: utf-8 -*-
#pylint: disable=W0142,R0201
"""

When's My DLR?
(c) 2011-12 Chris Applegate (chris AT qwghlm DOT co DOT uk)
Released under the MIT License

A Twitter bot that takes requests for a Docklands Light Railway train, and replies with the real-time data from TfL on Twitter

Inherits many methods and data structures from WhensMyTransport and WhensMyRailTransport, including: loading the databases, config, connecting to Twitter,
reading @ replies, replying to them, checking new followers, following them back

This module just does work specific to DLR trains: Parsing & interpreting a DLR-specific message, and checking the DLR XML API and
formatting an appropriate reply to be sent back
"""
# Standard libraries of Python 2.6
import logging
import re
from datetime import datetime, timedelta
from pprint import pprint # For debugging

# From other modules in this package
from whensmytransport import WhensMyRailTransport
from lib.models import Train as DLRTrain, NullDeparture
#from lib.exceptions import WhensMyTransportException
from lib.listutils import unique_values
from lib.stringutils import capwords


class WhensMyDLR(WhensMyRailTransport):
    """
    Main class devoted to checking for DLR-related Tweets and replying to them. Instantiate with no variables
    (all config is done in the file whensmytransport.cfg) and then call check_tweets()
    """
    def __init__(self, testing=None, silent=False):
        WhensMyRailTransport.__init__(self, 'whensmydlr', testing, silent)
        # As there is only one DLR, we can theoretically have blank tweets sent to this
        self.allow_blank_tweets = True
        self.line_lookup = {'DLR': 'DLR', }

    def parse_message(self, message):
        """
        Parse a Tweet - tokenize it, and get the line, origin and destination specified by the user
        """
        (_line_name, origin, destination) = self.tokenize_message(message, 'DLR', True)

        origin = origin and re.sub(" Station", "", origin, flags=re.I)
        destination = destination and re.sub(" Station", "", destination, flags=re.I)
        return (('DLR',), origin, destination)

    def get_departure_data(self, station, line_code, must_stop_at=None):
        """
        Take a station object and a line ID, and get departure data for that station
        Returns a dictionary; keys are platform names, values lists of DLRTrain objects
        """
        # Check if the station is open and if so (it will throw an exception if not), summon the data
        tfl_url = "http://www.dlrlondon.co.uk/xml/mobile/%s.xml" % station.code
        dlr_data = self.browser.fetch_xml_tree(tfl_url)
        train_info_regex = re.compile(r"[1-4] (\D+)(([0-9]+) mins?)?", flags=re.I)

        # Go through each platform and get data about every train arriving, including which direction it's headed
        trains_by_platform = {}
        platforms_to_ignore = [('tog', 'P1'),
                               ('wiq', 'P1')]
        platforms_to_ignore_if_empty = [('ban', 'P10'),
                                        ('str', 'P4B'),
                                        ('lew', 'P5')]
        for platform in dlr_data.findall("div[@id='ttbox']"):
            # Get the platform number from image attached and the time published
            img = platform.find("div[@id='platformleft']/img")
            platform_name = img.attrib['src'].split('.')[0][:-1].upper()
            if (station.code, platform_name) in platforms_to_ignore:
                continue
            trains_by_platform[platform_name] = []

            # Get trains for this platform
            info = platform.find("div[@id='platformmiddle']")
            publication_time = info.find("div[@id='time']").text.strip()
            publication_time = datetime.strptime(publication_time, "%H:%M")
            line1 = info.find("div[@id='line1']")
            line2 = info.find("div[@id='line23']/p")
            line3 = info.find("div[@id='line23']/p/br")
            trains = [line for line in (line1.text, line2.text, line3.tail) if line]

            # Go through trains, parse out the relevant data
            for train in trains:
                result = train_info_regex.search(train)
                if result:
                    destination = capwords(result.group(1).strip())
                    if destination == 'Terminates Here':
                        continue
                    # Filter out any trains where they do not directly call at the intermediate station requested
                    if must_stop_at:
                        destination_station = self.get_station_by_station_name(line_code, destination)
                        if destination_station and not self.geodata.direct_route_exists(station.name, destination_station.name, via=must_stop_at):
                            continue
                    departure_delta = timedelta(minutes=(result.group(3) and int(result.group(3)) or 0))
                    departure_time = datetime.strftime(publication_time + departure_delta, "%H%M")
                    trains_by_platform[platform_name].append(DLRTrain(destination, departure_time))
                    logging.debug("Found a train going to %s at %s", destination, departure_time)
                else:
                    logging.debug("Error - could not parse this line: %s", train)

            # If there are no trains in this platform to our specified stop, or it is a platform that can be ignored when it is empty
            # e.g. it is the "spare" platform at a terminus, then delete this platform entirely
            if not trains_by_platform[platform_name] and must_stop_at or (station.code, platform_name) in platforms_to_ignore_if_empty:
                del trains_by_platform[platform_name]

        # Some platforms run trains the same way (e.g. at termini). DLR doesn't tell us if this is the case, so we look at the destinations
        # on each pair of platforms and see if there is any overlap, using the set object and its intersection function. Any such
        # overlapping platforms, we merge their data together (only for the first pair though, to be safe)
        platform_pairs = [(plat1, plat2) for plat1 in trains_by_platform.keys() for plat2 in trains_by_platform.keys() if plat1 < plat2]
        common_platforms = [(plat1, plat2) for (plat1, plat2) in platform_pairs
                             if set([t.destination for t in trains_by_platform[plat1]]).intersection([t.destination for t in trains_by_platform[plat2]])]
        for (plat1, plat2) in common_platforms[:1]:
            logging.debug("Merging platforms %s and %s", plat1, plat2)
            trains_by_platform[plat1 + ' & ' + plat2] = unique_values(trains_by_platform[plat1] + trains_by_platform[plat2])
            del trains_by_platform[plat1], trains_by_platform[plat2]

        return self.cleanup_departure_data(trains_by_platform, lambda a: NullDeparture("from " + a))

if __name__ == "__main__":
    WMD = WhensMyDLR()
    WMD.check_tweets()
