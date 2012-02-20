#!/usr/bin/env python
#pylint: disable=W0703,W0107
"""
Data importing tools for WhensMyTransport - import TfL's data into an easier format for us to use
"""
# Standard Python libraries
import csv
import os
import re
import sys
import subprocess
import tempfile

from xml.dom.minidom import parse
from pprint import pprint

# Local files
from geotools import convertWGS84toOSGB36, LatLongToOSGrid
from utils import WMBBrowser, load_database
from whensmytube import cleanup_destination_name, cleanup_via_from_destination_name
from fuzzy_matching import get_best_fuzzy_match, get_rail_station_name_similarity

def parse_stations_from_kml(filter_function=lambda a, b: True):
    """
    Parses KML file of stations & associated data, and returns them as a dictionary
    """
    stations = {}
    dom = parse(open('./sourcedata/tube-locations.kml'))
    station_geodata = dom.getElementsByTagName('Placemark')    
    for station in station_geodata:
        name = station.getElementsByTagName('name')[0].firstChild.data.strip().replace(' Station', '')
        style = station.getElementsByTagName('styleUrl')[0].firstChild.data.strip()
        if filter_function(name, style):
            coordinates = station.getElementsByTagName('coordinates')[0].firstChild.data.strip()
            (lon, lat) = tuple([float(c) for c in coordinates.split(',')[0:2]])
            (lat, lon) = convertWGS84toOSGB36(lat, lon)[:2]
            (easting, northing) = LatLongToOSGrid(lat, lon)
            stations[name.lower()] = { 'Name' : name, 'Location_Easting' : str(easting), 'Location_Northing' : str(northing),
                                       'Code' : '', 'Lines' : '', 'Inner' : '', 'Outer' : '' }
    return stations

def export_rows_to_db(db_filename, tablename, fieldnames, rows, indices=()):
    """
    Generic database SQL composing & export function
    """
    sql = ""
    sql += "drop table if exists %s;\r\n" % tablename
    sql += "create table %s(%s);\r\n" % (tablename, ", ".join(fieldnames))

    for field_data in rows:
        sql += "insert into locations values "
        sql += "(\"%s\");\r\n" % '", "'.join(field_data)

    for index in indices:
        sql += "CREATE INDEX %s_index ON %s (%s);\r\n" % (index, tablename, index)
    export_sql_to_db(db_filename, sql)

def export_sql_to_db(db_filename, sql):
    """
    Generic database SQL export function
    """
    tempf = tempfile.NamedTemporaryFile('w')
    tempf.write(sql)
    tempf.flush()
    print subprocess.check_output(["sqlite3", db_filename], stdin=open(tempf.name))

def import_bus_csv_to_db():
    """
    Utility script that produces the script for converting TfL's bus data CSV into sqlite
    
    If you are updating the database, you first have to download the CSV file
    from the TfL website. Signup as a developer here: http://www.tfl.gov.uk/businessandpartners/syndication/
    
    Save the the routes as ./sourcedata/bus-routes.csv
    
    It takes the original file from TfL, fixes them to use semicolons (because sqlite's
    CSV parser is really dumb and can't deal with quoted values) and then converts it to
    the database file ./db/whensmybus.geodata.db
    """ 
    # Fix CSV - replace commas with semi-colons, allow sqlite to import without cocking it all up
    inputpath = './sourcedata/bus-routes.csv'
    inputfile = open(inputpath)
    reader = csv.reader(inputfile)
    fieldnames = reader.next()  # Skip first line (fieldnames)

    outputpath = inputpath.replace('.csv', '.ssv')
    outputfile = open(outputpath, 'w')
    writer = csv.writer(outputfile, delimiter=";")
    
    for line in reader:
        writer.writerow(line)
    outputfile.flush()
    outputfile.close()

    tablename = 'routes'

    integer_values = ('Location_Easting',
                    'Location_Northing',
                    'Heading',
                    'Virtual_Bus_Stop',
                    'Run',
                    'Sequence',)
                    
    fieldnames = ['%s%s' % (f, f in integer_values and ' INT' or '') for f in fieldnames]
    
    # Produce SQL for this table
    sql = "drop table if exists %s;\r\n" % tablename
    sql += "create table %s(%s);\r\n" % (tablename, ", ".join(fieldnames))
    sql += '.separator ";"\r\n'
    sql += ".import %s %s\r\n" % (outputpath, tablename)
    sql += "delete from %s WHERE Virtual_Bus_Stop;\r\n" % tablename
    sql += "\r\n"
    
    sql += "CREATE INDEX route_index ON routes (Route);\r\n"
    sql += "CREATE INDEX route_run_index ON routes (Route, Run);\r\n"
    sql += "CREATE INDEX route_stop_index ON routes (Route, Bus_Stop_Code);\r\n"
    
    export_sql_to_db("./db/whensmybus.geodata.db", sql)    
    # Drop SSV file now we don't need it
    os.unlink(outputpath)

def import_dlr_xml_to_db():
    """
    Utility script that produces the script for converting TfL's Tube data KML into a sqlite database
        
    Pulls together data from two files:

    1. The data for Tube & DLR station locations, originally from TfL but augmented with new data (Heathrow Terminal 5) 
    corrected for station names (e.g. Shepherd's Bush Market), and saved as tube-locations.kml
    
    2. Data for station codes and station names, scraped from the DLR website (sorry guys), saved as dlr-references.csv
    """
    fieldnames = ('Name', 'Code', 'Lines', 'Location_Easting INT', 'Location_Northing INT')

    dlr_station_filter = lambda name, style: style.find("#dlrStyle") > -1
    stations = parse_stations_from_kml(dlr_station_filter)
    # Parse CSV file of what stations are on what lines
    dlr_data = open('./sourcedata/dlr-references.csv')
    reader = csv.reader(dlr_data)
    reader.next()
    for line in reader:
        code = line[0]
        name = line[1]
        if name.lower() in stations:
            stations[name.lower()]['Code'] = code
            stations[name.lower()]['Lines'] = 'DLR'      
        else:
            print "Cannot find %s from dlr-references in geodata!" % name
            
    for name in stations:
        if not stations[name]['Code']:
            print "Cannot find %s from geodata in dlr-references!" % name

    rows = [[station[fieldname.split(' ')[0]] for fieldname in fieldnames] for station in stations.values()]
    export_rows_to_db("./db/whensmydlr.geodata.db", "locations", fieldnames, rows, ('Name',))

def import_tube_xml_to_db():
    """
    Utility script that produces the script for converting TfL's Tube data KML into a sqlite database
        
    Pulls together data from three files:

    1. The data for Tube station locations, originally from TfL but augmented with new data (Heathrow Terminal 5) 
    corrected for station names (e.g. Shepherd's Bush Market), and saved as tube-locations.kml
    
    2. The data for Tube station codes & line details, from:
    https://raw.github.com/blech/gae-fakesubwayapis-data/d365a8b56d7b5abfec378816e3d91fb901f0cc59/data/tfl/stops.txt
    corrected for station names, and saved as tube-references.csv
    
    3. Translations from "Outer" and "Inner" Rail (used for the Circle Line and Hainault Loop on the Central Line) to
    the more standard East or Westbound terms. This was generated by scrape_tfl_destination_codes() and then filled
    in by hand
    """
    fieldnames = ('Name', 'Code', 'Line', 'Location_Easting INT', 'Location_Northing INT', 'Inner', 'Outer')

    # Parse our XML file of locations, and only extract Tube stations
    tube_station_filter = lambda name, style: style.find("#tubeStyle") > -1
    stations = parse_stations_from_kml(tube_station_filter)
    
    # Parse CSV file of what stations are on what lines
    tube_data = open('./sourcedata/tube-references.csv')
    reader = csv.reader(tube_data)
    reader.next()
    for line in reader:
        code = line[0]
        name = line[1]
        lines = line[-1].split(";")
        if name.lower() in stations:
            stations[name.lower()]['Code'] = code
            stations[name.lower()]['Lines'] = lines      
        else:
            print "Cannot find %s from tube-references in geodata!" % name

    # Parse CSV file of what direction the "Inner" and "Outer" rails are for stations on circular loops
    circle_data = open('./sourcedata/circle_platform_data.csv')
    reader = csv.reader(circle_data)
    reader.next()
    for line in reader:
        name = line[1]
        if name.lower() in stations:
            stations[name.lower()]['Inner'] = line[3]
            stations[name.lower()]['Outer'] = line[4]            
        else:
            print "Cannot find %s from circle_platform_data in geodata!" % name
        
    rows = []
    for station in stations.values():
        station_name = station['Name']
        # Shorten stations such as Hammersmith/Edgware Road which are disambiguated by brackets, get rid of them
        if station_name and station_name.find('(') > -1 and station_name != "Kensington (Olympia)":
            station_name = station_name[:station_name.find('(') - 1]
            station['Name'] = station_name

        if not station['Code']:
            print "Could not find a station code for %s!" % station['Name']
        else:
            for line in station['Lines']:
                if line != 'O': 
                    field_data = (station['Name'], station['Code'], line,
                                  station['Location_Easting'], station['Location_Northing'],
                                  station['Inner'], station['Outer'])
                    rows.append(field_data)

    export_rows_to_db("./db/whensmytube.geodata.db", "locations", fieldnames, rows, ('Name',))

def scrape_tfl_destination_codes(write_file=False):
    """
    An experimental script that takes current Tube data from TfL, scrapes it to find every possible existing
    platform, destination code and destination name, and puts it into a database to help with us producing
    better output for users
    
    It also checks for platforms that are not designated -bound direction, and generates a blank CSV template
    for those stations with Inner/Outer Rail designations
    
    TODO Split these out into two separate functions
    """
    line_codes = ('B', 'C', 'D', 'H', 'J', 'M', 'N', 'P', 'V', 'W') # TODO Fix this
    (database, cursor) = load_database("whensmytube.geodata.db")
    browser = WMBBrowser()
    
    destination_summary = {}
    for line_code in line_codes:
        tfl_url = "http://cloud.tfl.gov.uk/TrackerNet/PredictionSummary/%s" % line_code
        try:
            train_data = browser.fetch_xml(tfl_url)
        except Exception:
            print "Couldn't get data for %s" % line_code
            continue
    
        for train in train_data.getElementsByTagName('T'):
            destination = train.getAttribute('DE')
            destination_code = train.getAttribute('D')
            
            if destination_summary.get(destination_code, destination) != destination and destination_code != '0':
                print "Error - mismatching destinations: %s (existing) and %s (new) with code %s" \
                      % (destination_summary[destination_code], destination, destination_code)
            
            cursor.execute("INSERT OR IGNORE INTO destination_codes VALUES (?, ?, ?)", (destination_code, line_code, destination))
            database.commit()
            destination_summary[destination_code] = destination

    # Check to see if destination is in our database
    cursor.execute("SELECT destination_name, line_code FROM destination_codes")
    for row in cursor.fetchall():
        destination = cleanup_via_from_destination_name(cleanup_destination_name(row[0]))
        if destination in ("Unknown", "Special", "Out Of Service"):
            continue
        if destination.startswith('Br To') or destination in ('Network Rail', 'Chiltern Toc'):
            continue            
        cursor.execute("SELECT Name FROM locations WHERE Name=? AND Line=?", (destination, row[1]))
        if not cursor.fetchone():
            cursor.execute("SELECT Name FROM locations WHERE Name=?", (destination,))
            station_is_on_other_line = cursor.fetchall()
            if not station_is_on_other_line:
                cursor.execute("SELECT Name FROM locations WHERE Line=?", (row[1],))
                all_stations = [station['Name'] for station in cursor.fetchall()]
                if not get_best_fuzzy_match(destination, all_stations, comparison_function=get_rail_station_name_similarity, minimum_confidence=70):
                    cursor.execute("SELECT Name FROM locations WHERE Line=?", (row[1],))
                    print "Destination %s on %s not found in locations database" % (row[0], row[1])
    
    print "Platforms without a Inner/Outer Rail specification:"
    station_platforms = {}
    for line_code in line_codes:
        for station in train_data.getElementsByTagName('S'):
            station_code = station.getAttribute('Code')[:3]
            station_name = station.getAttribute('N')[:-1]
            station_name = station_name.replace(" Circle", "")
            
            for platform in station.getElementsByTagName('P'):
                platform_name = platform.getAttribute('N')
                direction = re.search("(North|East|South|West)bound", platform_name, re.I)
                if direction is None:
                    rail = re.search("(Inner|Outer) Rail", platform_name, re.I)
                    if rail:
                        if (station_name, station_code) not in station_platforms:
                            station_platforms[(station_name, station_code)] = []
                        if line_code not in station_platforms[(station_name, station_code)]:
                            station_platforms[(station_name, station_code)].append(line_code)
                
                if direction is None and rail is None:
                    print "%s %s" % (station_name, platform_name)
        
    print ""
    if write_file:
        outputfile = open('./sourcedata/circle_platform_data.csv', 'w')
    else:
        outputfile = sys.stdout
        
    writer = csv.writer(outputfile)
    writer.writerow(['Station Code', 'Station Name', 'Line Code', 'Inner Rail', 'Outer Rail'])
    errors = []
    for (station_name, station_code) in sorted(station_platforms.keys()):
        for line_code in sorted(station_platforms[(station_name, station_code)]):
            writer.writerow([station_code, station_name, line_code, '', ''])
        cursor.execute("SELECT Name FROM locations WHERE Name=?", (station_name,))
        if not cursor.fetchone():
            errors.append("%s is not in the station database" % station_name)
    outputfile.flush()
    
    print ""
    for error in errors:
        print error

    outputfile.close()

if __name__ == "__main__":
    #import_bus_csv_to_db()
    #import_tube_xml_to_db()
    #import_dlr_xml_to_db()
    scrape_tfl_destination_codes()
    pass