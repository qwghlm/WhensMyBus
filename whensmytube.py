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

Things to do:
 - Review all logging and make sure consistent with WhensMyBus
"""
# Standard libraries of Python 2.6
import re
from pprint import pprint # For debugging

# From other modules in this package
from whensmytransport import WhensMyRailTransport
from exception_handling import WhensMyTransportException
from utils import capwords, unique_values, cleanup_name_from_undesirables
from fuzzy_matching import get_best_fuzzy_match

class TubeTrain():
    """
    Class representing a Tube train
    """
    def __init__(self, destination, direction, departure_time, set_number, line_code, destination_code):
        self.destination = destination
        self.direction = direction
        self.departure_time = departure_time
        self.set_number = set_number
        self.line_code = line_code
        self.destination_code = destination_code

    def __cmp__(self, other):
        """
        Return comparison value to enable sort by departure time
        """
        return cmp(self.departure_time, other.departure_time)
        
    def __hash__(self):
        """
        Return hash value to enable ability to use as dictionary key
        """
        return hash('-'.join([self.set_number, self.destination_code, str(self.departure_time)]))

    def __repr__(self):
        """
        Return representation value for this Train for debugging
        """
        return '(%s)' % ', '.join((self.destination, self.direction, str(self.departure_time), self.set_number, self.line_code, self.destination_code))
        
    def get_departure_time(self):
        """
        Return this train's departure time in human format
        """
        departure_time = self.departure_time and ("%smin" % self.departure_time) or "due"
        return departure_time
        
    def get_destination(self):
        """
        Return this train's destination in suitably shortened format
        """
        if self.destination == "Unknown":
            destination = "%s Train" % self.direction
        else:
            destination = self.destination
        destination = abbreviate_station_name(destination)
        return destination

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
            'District',
            'Hammersmith & Circle',
            'Jubilee',
            'Metropolitan',
            'Northern',
            'Piccadilly',
            'Victoria',
            'Waterloo & City',
        )
        line_tuples = [(name, name) for name in line_names] + [('Circle', 'Hammersmith & Circle'), ('Hammersmith & City', 'Hammersmith & Circle')]
        # Handle abbreviated three-letter versions and sort out ampersands
        line_tuples += [(name[:3], name) for name in line_names]
        line_tuples += [(name.replace("&", "and"), name) for name in line_names]
        line_tuples += [('W&C', 'Waterloo & City'), ('H&C', 'Hammersmith & Circle',)]
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
        if line_name.lower().startswith('thank'):
            self.log_debug("This looks like a thank-you, skipping")
            return (None, None, None)

        line_name = line_name and re.sub(" Line", "", line_name, flags=re.I)
        origin = origin and re.sub(" Station", "", origin, flags=re.I)
        destination = destination and re.sub(" Station", "", destination, flags=re.I)

        return ((line_name,), origin, destination) 
        
    def process_individual_request(self, line_name, origin, destination, position):
        """
        Take an individual line, with either origin or position, and work out which station the user is
        referring to, and then get times for it
        """
        if line_name not in self.line_lookup:
            line = get_best_fuzzy_match(line_name, self.line_lookup.values())
            if line is None:
                raise WhensMyTransportException('nonexistent_line', line_name)
        else:
            line = self.line_lookup[line_name]
        line_code = line[0]
        
        # Dig out relevant station for this line from the geotag, if provided
        if position:
            station = self.get_station_by_geolocation(line_code, position)
        # Else there will be an origin (either a number or a placename), so try parsing it properly
        else:
            station = self.get_station_by_station_name(line_code, origin)
        
        # Dummy code - what do we do with destination data (?)
        if destination:
            pass
            
        # If we have a station code, go get the data for it
        if station:
            # XXX is the code for a station that does not have data given to it
            if station.code == "XXX":
                raise WhensMyTransportException('tube_station_not_in_system', station.name)

            time_info = self.get_departure_data(line_code, station)
            if time_info:
                return "%s to %s" % (abbreviate_station_name(station.name), time_info)
            else:
                raise WhensMyTransportException('no_tube_arrival_data', line_name, station.name)
        else:
            raise WhensMyTransportException('tube_station_name_not_found', origin, line_name)
        
    def get_departure_data(self, line_code, station):
        """
        Take a station ID and a line ID, and get departure data for that station
        """
        # Check if the station is open and if so (it will throw an exception if not), summon the data
        self.check_station_is_open(station)
        tfl_url = "http://cloud.tfl.gov.uk/TrackerNet/PredictionDetailed/%s/%s" % (line_code, station.code)
        tube_data = self.browser.fetch_xml(tfl_url)

        # Go through each platform and get data about every train arriving, including which direction it's headed
        trains_by_direction = {}
        for platform in tube_data.getElementsByTagName('P'):
            
            platform_name = platform.getAttribute('N')
            direction = re.search("(North|East|South|West)bound", platform_name, re.I)
            rail = re.search("(Inner|Outer) Rail", platform_name, re.I)
            
            # Most stations tell us whether they are -bound in a certain direction
            if direction:
                direction = capwords(direction.group(0))
            # Some Circle/Central Line platforms called "Inner" and "Outer" Rail, which make no sense to customers, so I've manually
            # entered Inner and Outer columns in the database which translate from these into North/South/East/West bearings
            elif rail:
                self.geodata.execute("SELECT %s FROM locations WHERE Line=? AND Code=?" % rail.group(1), (line_code, station.code))
                bearing = self.geodata.fetchone()[0]
                direction = bearing + 'bound'
            else:
                # Some odd cases. Chesham and Chalfont & Latimer don't say anything at all for the platforms on the Chesham branch of the Met Line
                if station.code == "CHM":
                    direction = "Southbound"
                elif station.code == "CLF" and platform.getAttribute('Num') == '3':
                    direction = "Northbound"
                else:
                    # The following stations will have "issues" with bidrectional platforms: North Acton, Edgware Road, Loughton, White City
                    # These are dealt with the below
                    direction = "Unknown"
                    self.log_debug("Have encountered a platform without direction specified (%s)", platform_name)

            # Use the filter function to filter out trains that are out of service, specials or National Rail first
            platform_trains = [t for t in platform.getElementsByTagName('T') if t.getAttribute('LN') == line_code and filter_tube_trains(t)]
            for train in platform_trains:
                destination = cleanup_destination_name(train.getAttribute('Destination'))
                # Ignore any trains terminating at this station
                if self.get_station_by_station_name(line_code, destination):
                    if self.get_station_by_station_name(line_code, destination).name == station.name:
                        continue

                # FIXME Departure times should be times to be consistent with WMB
                departure_time = train.getAttribute('TimeTo')
                if departure_time == '-' or departure_time.startswith('0'):
                    departure_time = 0
                else:
                    departure_time = int(departure_time.split(":")[0])
                
                if direction == "Unknown":
                    if destination == "Unknown":
                        continue
                    destination_obj = self.get_station_by_station_name(line_code, destination)
                    if not destination_obj:
                        continue
                    else:
                        # FIXME Get the co-ordinates of this station, and the destination, and work out if the train
                        # is east or westbound from this!
                        continue

                # SetNo identifies a unique train. For stations like Earls Court this is duplicated across two platforms and can mean the same train is
                # "scheduled" to come into both (obviously impossible), so we add this to our train so our hashing function knows to score as unique
                set_number = train.getAttribute('SetNo')
                destination_code = train.getAttribute('DestCode')
                train_obj = TubeTrain(destination, direction, departure_time, set_number, line_code, destination_code)
                trains_by_direction[direction] = trains_by_direction.get(direction, []) + [train_obj]

        # For each direction, display the first three unique trains, sorted in time order
        # Dictionaries alone do not preserve order, hence a list of the correct order for destinations as well
        destinations_correct_order = []
        train_times = {}
        for trains in trains_by_direction.values():
            for train in unique_values(sorted(trains))[:3]:
                destination = train.get_destination()
                self.log_debug("Adding a train to %s at %s to the output", train.destination, train.departure_time)
                if destination in destinations_correct_order:
                    train_times[destination].append(train.get_departure_time())
                else:
                    train_times[destination] = [train.get_departure_time()]
                    destinations_correct_order.append(destination)

        # This returns an empty string if no trains are due, btw
        return '; '.join([destination + ' ' + ', '.join(train_times[destination]) for destination in destinations_correct_order])

    def check_station_is_open(self, station):
        """
        Check to see if a station is open, return True if so, throw an exception if not
        """
        status_url = "http://cloud.tfl.gov.uk/TrackerNet/StationStatus/IncidentsOnly"
        status_data = self.browser.fetch_xml(status_url)
        for station_status in status_data.getElementsByTagName('StationStatus'):
            station_node = station_status.getElementsByTagName('Station')[0]
            status_node = station_status.getElementsByTagName('Status')[0]
            if station_node.getAttribute('Name') == station.name and status_node.getAttribute('Description') == 'Closed':
                raise WhensMyTransportException('tube_station_closed', station.name, station_status.getAttribute('StatusDetails').strip().lower())
        return True

def cleanup_destination_name(station_name):
    """
    Get rid of TfL's odd designations in the Destination field to make it compatible with our list of stations in the database
    
    Destination names are full of garbage. What I would like is a database mapping codes to canonical names, but this is currently pending
    an FoI request. Once I get that, this code will be a lot neater :)
    """
    station_name = re.sub(r"\band\b", "&", station_name, flags=re.I)
    # Destinations that are line names or Unknown get boiled down to Unknown
    if station_name in ("Unknown", "Circle & Hammersmith & City") or station_name.startswith("Circle Line") or station_name.endswith("Train") or station_name.endswith("Line"):
        station_name = "Unknown"
    else:
        # Regular expressions of instructions, depot names (presumably instructions for shunting after arrival), or platform numbers
        undesirables = ('\(rev to .*\)',
                        'sidings?',
                        '(then )?depot',
                        'ex (barnet|edgware) branch',
                        '\(ex .*\)',
                        '/ london road',
                        '27 Road',
                        '\(plat\. [0-9]+\)',
                        ' loop',
                        '\(circle\)')
        station_name = cleanup_name_from_undesirables(station_name, undesirables)
    return station_name
    
def cleanup_via_from_destination_name(station_name):
    """
    Get rid of "via" from a destination name to make
    it match easier to a canonical station name
    """
    #pylint: disable=C0103
    return re.sub(" \(?via .*$", "", station_name, flags=re.I)

def abbreviate_station_name(station_name):
    """
    Take an official station name and abbreviate it to make it fit on Twitter better
    """
    # Stations we just have to cut down by hand
    translations = {
        "High Street Kensington" : "High St Ken",
        "King's Cross St. Pancras" : "Kings X St P",
        "Kensington (Olympia)" : "Olympia",
    }
    station_name = translations.get(station_name, station_name)

    # Punctuation marks can be cut down  
    punctuation_to_remove = (r'\.', ', ', r'\(', r'\)', "'",)
    station_name = cleanup_name_from_undesirables(station_name, punctuation_to_remove)

    # Words like Road and Park can be slimmed down as well
    abbreviations = {
        'Bridge' : 'Br',
        'Broadway' : 'Bdwy',
        'Central' : 'Ctrl',
        'Court' : 'Ct',
        'Cross' : 'X',
        'Crescent' : 'Cresc',
        'East' : 'E',
        'Gardens' : 'Gdns',
        'Green' : 'Grn',
        'Heathway' : 'Hthwy',
        'Junction' : 'Jct',
        'Market' : 'Mkt',
        'North' : 'N',
        'Park' : 'Pk',
        'Road' : 'Rd',
        'South' : 'S',
        'Square' : 'Sq',
        'Street' : 'St',
        'Terminal' : 'T',
        'Terminals' : 'T',
        'West' : 'W',
    }   
    station_name = ' '.join([abbreviations.get(word, word) for word in station_name.split(' ')])
    
    # Any station with & in it gets only the initial of the second word - e.g. Elephant & C
    if station_name.find('&') > -1:
        station_name = station_name[:station_name.find('&')+2]
    return station_name

def filter_tube_trains(tube_xml_node):
    """
    Filter function for TrackerNet's XML nodes, to get rid of misleading, out of service or downright bogus trains
    """
    destination = tube_xml_node.getAttribute('Destination')
    destination_code = tube_xml_node.getAttribute('DestCode')
    location = tube_xml_node.getAttribute('Location')
    
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
    WMT = WhensMyTube(testing=True) # FIXME :)
    WMT.check_tweets()
    WMT.check_followers()
