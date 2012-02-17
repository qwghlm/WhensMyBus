#!/usr/bin/env python
# -*- coding: utf-8 -*-
#pylint: disable=W0142,R0201

# Standard libraries of Python 2.6
import logging # FIXME Replace with own Logging?
import re
from pprint import pprint # For debugging

# From other modules in this package
from whensmytransport import WhensMyTransport
from geotools import convertWGS84toOSGrid
from exception_handling import WhensMyTransportException
from utils import capwords, unique_values, cleanup_station_name, filter_tube_trains, abbreviate_station_name # FIXME Put these last three here?
from fuzzy_matching import get_best_fuzzy_match, get_tube_station_name_similarity # FIXME Put last one here?

class TubeStation():
    #pylint: disable=C0103,R0903,W0613
    """
    Class representing a Tube station
    """
    def __init__(self, Name='', Code='', **kwargs):
        self.name = Name
        self.code = Code
        
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
        Return hash value to enable uniqueness
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


class WhensMyTube(WhensMyTransport):
    """
    Main class devoted to checking for Tube-related Tweets and replying to them. Instantiate with no variables
    (all config is done in the file whensmytransport.cfg) and then call check_tweets()
    """
    def __init__(self, testing=None, silent=False):
        WhensMyTransport.__init__(self, 'whensmytube', testing, silent)
        
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
        # Handle abbreviated three-letter versions (e.g. "Met") plus one-word versions
        line_tuples = [(name, name) for name in line_names] + [(name[:3], name) for name in line_names] + [(name.split(' ')[0], name) for name in line_names]
        self.line_lookup = dict(line_tuples)
        self.line_lookup['Circle'] = 'Hammersmith & Circle'
        self.line_lookup['Hammersmith & City'] = 'Hammersmith & Circle'
        
    def parse_message(self, message):
        """
        Parse a Tweet - tokenize it, and get the line(s) specified by the user
        """
        (line_name, origin, destination) = self.tokenize_message(message)
        if line_name.lower().startswith('thank'):
            return (None, None, None)

        line_name = line_name and capwords(line_name).replace(" Line", "")
        origin = origin and capwords(origin).replace(" Station", "")
        destination = destination and capwords(destination).replace(" Station", "")

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
        
    def get_station_by_geolocation(self, line_code, position):
        """
        Take a line and a tuple specifying latitude & longitude, and works out closest station        
        """
        #pylint: disable=W0613
        # GPSes use WGS84 model of Globe, but Easting/Northing based on OSGB36, so convert to an easting/northing
        logging.debug("Position in WGS84 determined as: %s %s", position[0], position[1])
        easting, northing, gridref = convertWGS84toOSGrid(position)
        logging.debug("Translated into OS Easting %s, Northing %s, Grid Reference %s", easting, northing, gridref)

        # Do a funny bit of Pythagoras to work out closest stop. We can't find square root of a number in sqlite
        # but then again, we don't need to, the smallest square will do. Sort by this column in ascending order
        # and find the first row
        query = """
                SELECT (Location_Easting - %d)*(Location_Easting - %d) + (Location_Northing - %d)*(Location_Northing - %d) AS dist_squared,
                      Name,
                      Code
                FROM locations
                WHERE Line='%s'
                ORDER BY dist_squared
                LIMIT 1
                """ % (easting, easting, northing, northing, line_code)
        self.geodata.execute(query)
        row = self.geodata.fetchone()
        if row:
            logging.debug("Have found %s station (%s)", row['Name'], row['Code'])
            return TubeStation(**row)
        else:
            return None

    def get_station_by_station_name(self, line_code, origin):
        """
        Take a line and a string specifying origin, and work out matching for that name      
        """
        # First off, try to get a match against bus stop names in database
        # Users may not give exact details, so we try to match fuzzily
        logging.debug("Attempting to get a match on placename %s", origin)
        self.geodata.execute("""
                             SELECT Name, Code FROM locations WHERE Line=? OR Line='X'
                             """, line_code)
        rows = self.geodata.fetchall()
        if rows:
            best_match = get_best_fuzzy_match(origin, rows, 'Name', get_tube_station_name_similarity)
            if best_match:
                logging.debug("Match found! Found: %s", best_match['Name'])
                return TubeStation(**best_match)

        logging.debug("No match found for %s, sorry", origin)
        return None
        
    def get_departure_data(self, line_code, station):
        """
        Take a station ID and a line ID, and get departure data for that station
        """
        self.check_station_is_open(station)
        tfl_url = "http://cloud.tfl.gov.uk/TrackerNet/PredictionDetailed/%s/%s" % (line_code, station.code)
        tube_data = self.browser.fetch_xml(tfl_url)

        trains = []
        # Go through each platform and get data about every train arriving
        for platform in tube_data.getElementsByTagName('P'):
            
            platform_name = platform.getAttribute('N')
            direction = re.search("(North|East|South|West)bound", platform_name, re.I)
            rail = re.search("(Inner|Outer) Rail", platform_name, re.I)
            
            # Deal with some Circle/Central Line platforms called "Inner" and "Outer" Rail
            if direction:
                direction = capwords(direction.group(0))
            elif rail:
                self.geodata.execute("SELECT %s FROM locations WHERE Line=? AND Code=?" % rail.group(1), (line_code, station.code))
                bearing = self.geodata.fetchone()[0]
                direction = bearing + 'bound'
            else:
                # Some odd cases. Chesham and Chalfont & Latimer have their own system
                if station.code == "CHM":
                    direction = "Southbound"
                elif station.code == "CLF" and platform.getAttribute('Num') == '3':
                    direction = "Northbound"
                else:
                    # The following stations will have "issues" with bidrectional platforms: North Acton, Edgware Road, Loughton, White City
                    direction = "Unknown"

            platform_trains = [t for t in platform.getElementsByTagName('T') if t.getAttribute('LN') == line_code and filter_tube_trains(t)]
            for train in platform_trains:
                destination = cleanup_station_name(train.getAttribute('Destination'))
                if self.get_station_by_station_name(line_code, destination):
                    if self.get_station_by_station_name(line_code, destination).name == station.name:
                        continue

                departure_time = train.getAttribute('TimeTo')
                if departure_time == '-' or departure_time.startswith('0'):
                    departure_time = 0
                else:
                    departure_time = int(departure_time.split(":")[0])
                
                # SetNo identifies a unique train. Sometimes this is duplicated across platforms
                set_number = train.getAttribute('SetNo')
                destination_code = train.getAttribute('DestCode')
                trains.append(TubeTrain(destination, direction, departure_time, set_number, line_code, destination_code))

        # For platforms that are bidirectional, need to assign direction on a train-by-train basis, so create a reverse mapping of destination code to direction 
        destination_to_direction = dict([(t.destination_code, t.direction) for t in trains if t.direction != "Unknown" and t.destination != "Unknown"])
        for train in trains:
            if train.direction == "Unknown" and train.destination_code in destination_to_direction:
                train.direction = destination_to_direction[train.destination_code]                

        # Once we have all trains, organise by direction
        trains_by_direction = {}
        for train in trains:
            if train.direction != "Unknown":
                trains_by_direction[train.direction] = trains_by_direction.get(train.direction, []) + [train]

        # For each direction, display the first three unique trains, sorted in time order
        # Dictionaries alone do not preserve order, hence a list of the correct order for destinations as well
        destinations_correct_order = []
        train_times = {}
        for trains in trains_by_direction.values():
            for train in unique_values(sorted(trains))[:3]:
                destination = train.get_destination()
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