#!/usr/bin/env python
"""
Data parsers for Whens My Transport?
"""
import logging
import re
from datetime import datetime, timedelta

from lib.exceptions import WhensMyTransportException
from lib.models import TubeTrain, Bus, DLRTrain, DepartureCollection
from lib.stringutils import capwords, gmt_to_localtime


def parse_bus_data(bus_data, route_number):
    """
    Take a parsed JSON object bus_data from a single bus stop and a specified route_number
    Returns a list of Bus objects for that bus stop and route
    """
    arrivals = bus_data.get('arrivals', [])

    # Handle TfL's JSON-encoded error message
    if not arrivals and bus_data.get('stopBoardMessage', '') == "noPredictionsDueToSystemError":
        raise WhensMyTransportException('tfl_server_down')

    # Do the user a favour - check for both number and possible Night Bus version of the bus
    relevant_arrivals = [a for a in arrivals if (a['routeName'] == route_number or a['routeName'] == 'N' + route_number)
                                                and a.get('isRealTime', True)
                                                and not a.get('isCancelled', False)]

    # FIXME Temporary logging code
    for a in relevant_arrivals[:3]:
        logging.debug("Found bus %s going to %s at %s" % (a['routeName'], a['destination'], a['scheduledTime']))

    relevant_buses = [Bus(a['destination'], gmt_to_localtime(a['scheduledTime'])) for a in relevant_arrivals[:3]]
    return relevant_buses


def parse_dlr_data(dlr_data, station):
    """
    Takes a parsed XML elementTree dlr_data and the RailStation object for the station whose departures we are querying
    Returns a DepartureCollection object of all departures from the station in question, classified by platform
    """
    train_info_regex = re.compile(r"[1-4] (\D+)(([0-9]+) mins?)?", flags=re.I)
    platforms_to_ignore = [('tog', 'P1'),
                           ('wiq', 'P1')]
    platforms_to_ignore_if_empty = [('ban', 'P10'),
                                    ('str', 'P4B'),
                                    ('lew', 'P5')]

    # Go through each platform and get data about every train arriving, including which direction it's headed
    trains_by_platform = DepartureCollection()
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
                trains_by_platform.add_to_slot(platform_name, DLRTrain(destination, departure_time))
                logging.debug("Found a train going to %s at %s", destination, departure_time)
            else:
                logging.debug("Error - could not parse this line: %s", train)

        # If there are no trains in this platform to our specified stop, or it is a platform that can be ignored when it is empty
        # e.g. it is the "spare" platform at a terminus, then delete this platform entirely
        if not trains_by_platform[platform_name] and (station.code, platform_name) in platforms_to_ignore_if_empty:
            del trains_by_platform[platform_name]

    # If two platforms have exact same set of destinations, treat them as one by merging
    trains_by_platform.merge_common_slots()
    return trains_by_platform


def parse_tube_data(tube_data, station, line_code):
    """
    Takes a parsed XML elementTree tube_data, the RailStation object for the station whose departures we are querying,
    and a string representing the one-character code for the line we want trains for

    Returns a DepartureCollection object of all departures from the station in question, classified by direction
    """
    # Go through each platform and get data about every train arriving, including which direction it's headed
    trains_by_direction = DepartureCollection()
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
        # entered Inner and Outer attributes in the object (taken from the database) in the attribute circular_directions,
        # which translate from these into North/South/East/West
        elif rail:
            direction = station.circular_directions[rail.group(1).lower()] + 'bound'
        else:
            # Some odd cases. Chesham and Chalfont & Latimer don't say anything at all for the platforms on the Chesham branch of the Met Line
            if station.code == "CHM":
                direction = "Southbound"
            elif station.code == "CLF" and platform.attrib['Num'] == '3':
                direction = "Northbound"
            else:
                # The following stations will have "issues" with bidrectional platforms: North Acton, Edgware Road, Loughton, White City
                # These are dealt with by analysing the location of the destination by the calling WhensMyTrain object
                direction = "Unknown"
                logging.debug("Have encountered a platform without direction specified (%s)", platform_name)

        # Use the filter function to filter out trains that are out of service, specials or National Rail first
        platform_trains = platform.findall("T[@LN='%s']" % line_code)
        platform_trains = [train for train in platform_trains if filter_tube_train(train)]
        for train in platform_trains:
            # Create a TubeTrain object
            destination = train.attrib['Destination']
            departure_delta = timedelta(seconds=int(train.attrib['SecondsTo']))
            departure_time = datetime.strftime(publication_time + departure_delta, "%H%M")
            set_number = train.attrib['SetNo']
            train_obj = TubeTrain(destination, direction, departure_time, line_code, set_number)
            trains_by_direction.add_to_slot(direction, train_obj)

    return trains_by_direction


def filter_tube_train(train_tag):
    """
    XML tag filter function for whether to include trains, to get rid of misleading, out of service or downright bogus trains
    """
    destination = train_tag.attrib['Destination']
    destination_code = train_tag.attrib['DestCode']
    location = train_tag.attrib.get('Location', '')
    # 341 & 342 are codes for Northumberland Park depot
    # 433 is code for Triangle sidings depot (only used at night?)
    # 546 and 749 appear to be codes for Out of Service http://wiki.opentfl.co.uk/TrackerNet_predictions_detailed
    # 775 is code for an Empty Neasden depot train
    if destination_code in ('261', '341', '342', '433', '546', '749', '775'):
        return False
    # Trains in sidings are not much use to us
    if destination_code == '0' and location.find('Sidings') > -1:
        return False
    # No Specials or other Out of Service trains
    if destination in ('Special', 'Out Of Service'):
        return False
    # National Rail trains on Bakerloo & Metropolitan lines not that useful in this case
    if destination.startswith('BR') or destination in ('Network Rail', 'Chiltern TOC', 'Chiltern Goods', 'TOC'):
        return False
    return True
