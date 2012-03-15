#!/usr/bin/env python
"""
Data parsers for Whens My Transport?
"""
import logging
import re
from datetime import datetime, timedelta
from time import localtime

from lib.exceptions import WhensMyTransportException
from lib.listutils import unique_values
from lib.locations import WMTLocations
from lib.models import RailStation, TubeTrain, Bus, Train as DLRTrain
from lib.stringutils import capwords


def parse_bus_data(bus_data, stop, route_number):
    """
    Take a parsed json object bus_data from a single stop, BusStop object and strings representing the route and run
    Returns an array of Bus objects
    """
    arrivals = bus_data.get('arrivals', [])

    # Handle TfL's JSON-encoded error message
    if not arrivals and bus_data.get('stopBoardMessage', '') == "noPredictionsDueToSystemError":
        raise WhensMyTransportException('tfl_server_down')

    # Do the user a favour - check for both number and possible Night Bus version of the bus
    relevant_arrivals = [a for a in arrivals if (a['routeName'] == route_number or a['routeName'] == 'N' + route_number)
                                                and a['isRealTime'] and not a['isCancelled']]
    relevant_buses = []
    if relevant_arrivals:
        for arrival in relevant_arrivals[:3]:
            scheduled_time = arrival['scheduledTime'].replace(':', '')
            # Short hack to get BST working
            if localtime().tm_isdst:
                hour = (int(scheduled_time[0:2]) + 1) % 24
                scheduled_time = '%02d%s' % (hour, scheduled_time[2:4])
            logging.debug("Stop %s produced bus to %s %s", stop.get_clean_name(), arrival['destination'], scheduled_time)
            relevant_buses.append(Bus(stop.get_clean_name(), arrival['destination'], scheduled_time))
    else:
        logging.debug("Stop %s produced no buses", stop.get_clean_name())

    return relevant_buses


def parse_dlr_data(dlr_data, station):
    """
    Take a parsed elementTree dlr_data, RailStation object and string representing a line code
    Returns a dictionary; keys are platform names, values lists of DLRTrain objects
    """
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
                departure_delta = timedelta(minutes=(result.group(3) and int(result.group(3)) or 0))
                departure_time = datetime.strftime(publication_time + departure_delta, "%H%M")
                trains_by_platform[platform_name].append(DLRTrain(destination, departure_time))
                logging.debug("Found a train going to %s at %s", destination, departure_time)
            else:
                logging.debug("Error - could not parse this line: %s", train)

        # If there are no trains in this platform to our specified stop, or it is a platform that can be ignored when it is empty
        # e.g. it is the "spare" platform at a terminus, then delete this platform entirely
        if not trains_by_platform[platform_name] and (station.code, platform_name) in platforms_to_ignore_if_empty:
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

    return trains_by_platform


def parse_tube_data(tube_data, station, line_code):
    """
    Take a parsed elementTree tube_data, RailStation object and string representing a line code
    Returns a dictionary; keys are platform names, values lists of TubeTrain objects
    """
    # Go through each platform and get data about every train arriving, including which direction it's headed
    locations = WMTLocations('whensmytube')
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

            # Try and work out direction from destination. By luck, all the stations that have bidirectional
            # platforms are on an East-West line, so we just inspect the position of the destination's easting
            # and compare it to this station's
            if train_obj.direction == "Unknown":
                if train_obj.destination == "Unknown":
                    continue
                destination_station = locations.find_fuzzy_match({'Line': line_code}, train_obj.destination, RailStation)
                if not destination_station:
                    continue
                if destination_station.location_easting < station.location_easting:
                    train_obj.direction = "Westbound"
                else:
                    train_obj.direction = "Eastbound"

            trains_by_direction[direction] = trains_by_direction.get(direction, []) + [train_obj]

    return trains_by_direction


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
