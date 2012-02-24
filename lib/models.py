#!/usr/bin/env python
"""
Models/abstractions of concepts such as stations, trains, bus stops etc.
"""
from lib.stringutils import cleanup_name_from_undesirables
import re

class RailStation():
    #pylint: disable=C0103,R0903,W0613
    """
    Class representing a railway station
    """
    def __init__(self, Name='', Code='', Location_Easting=0, Location_Northing=0, **kwargs):
        self.name = Name
        self.code = Code
        self.location_easting = Location_Easting
        self.location_northing = Location_Northing

    def get_abbreviated_name(self):
        """
        Take this station's name and abbreviate it to make it fit on Twitter better
        """
        # Stations we just have to cut down by hand
        translations = {
            "High Street Kensington" : "High St Ken",
            "King's Cross St. Pancras" : "Kings X St P",
            "Kensington (Olympia)" : "Olympia",
            "W'wich Arsenal" : "Woolwich A",
        }
        station_name = translations.get(self.name, self.name)
    
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

class BusStop():
    #pylint: disable=C0103,R0903,W0613
    """
    Class representing a bus stop
    """
    def __init__(self, Stop_Name='', Bus_Stop_Code='', Heading=0, Sequence=1, Distance=0.0, **kwargs):
        self.name = Stop_Name
        self.number = Bus_Stop_Code
        self.heading = Heading
        self.sequence = Sequence
        self.distance_away = Distance

    def __cmp__(self, other):
        """
        Comparator function - measure by distance away from the point the user is
        """
        return cmp(self.distance_away, other.distance_away)
        
    def get_clean_name(self):
        """
        Get rid of TfL's ASCII symbols for Tube, National Rail, DLR & Tram from this stop's name
        """
        return cleanup_name_from_undesirables(self.name, ('<>', '#', r'\[DLR\]', '>T<'))

class Train():
    """
    Class representing a train of any kind (Tube, DLR)
    """
    def __init__(self, destination=None, departure_time=None, direction=None):
        self.destination = destination
        self.departure_time = departure_time
        self.direction = direction
        
    def __cmp__(self, other):
        """
        Return comparison value to enable sort by departure time
        """
        return cmp(self.departure_time, other.departure_time)

    def __hash__(self):
        """
        Return hash value to enable ability to use as dictionary key
        """
        return hash('-'.join([self.destination, str(self.departure_time)]))

    def get_departure_time(self):
        """
        Return this train's departure time in human format
        """
        return str(self.departure_time)

    def get_destination(self):
        """
        Return this train's destination in suitably shortened format
        """
        if self.destination == "Unknown":
            destination = "%s Train" % self.direction
        else:
            destination = RailStation(self.destination).get_abbreviated_name()
        return destination

    def get_clean_destination_name(self):
        """
        Get rid of "via" from a destination name to make
        it match easier to a canonical station name
        """
        return re.sub(" \(?via .*$", "", self.destination, flags=re.I)
        
class TubeTrain(Train):
    """
    Class representing a Tube train
    """
    #pylint: disable=W0231
    def __init__(self, destination, direction, departure_time, set_number, line_code, destination_code):

        # Get rid of TfL's odd designations in the Destination field to make it compatible with our list of stations in the database
        # Destination names are full of garbage. What I would like is a database mapping codes to canonical names, but this is currently pending
        # an FoI request. Once I get that, this code will be a lot neater :)
    
        destination = re.sub(r"\band\b", "&", destination, flags=re.I)
        # Destinations that are line names or Unknown get boiled down to Unknown
        if destination in ("Unknown", "Circle & Hammersmith & City") or destination.startswith("Circle Line") \
            or destination.endswith("Train") or destination.endswith("Line"):
            destination = "Unknown"
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
            destination = cleanup_name_from_undesirables(destination, undesirables)

        self.destination = destination
        self.direction = direction
        self.departure_time = departure_time
        self.set_number = set_number
        self.line_code = line_code
        self.destination_code = destination_code

    def __hash__(self):
        """
        Return hash value to enable ability to use as dictionary key
        """
        return hash('-'.join([self.set_number, self.destination_code, str(self.departure_time)]))

class DLRTrain(Train):
    """
    Class representing a DLR train
    """
    #pylint: disable=W0231
    def __init__(self, destination, departure_time):
        Train.__init__(self, destination, departure_time)
