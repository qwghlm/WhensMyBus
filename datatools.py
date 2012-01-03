#!/usr/bin/env python
"""
Data importing tools for WhensMyTransport - import TfL's data into an easier format for us to use
"""
# Standard Python libraries
import csv
import tempfile
import subprocess

from xml.dom.minidom import parse

# Local files
from geotools import convertWGS84toOSGB36, LatLongToOSGrid, gridrefNumToLet

def import_bus_csv_to_db():
    """
    Utility script that produces the script for converting TfL's bus data CSV into sqlite
    
    If you are updating the database, you first have to download the CSV file
    from the TfL website. Signup as a developer here: http://www.tfl.gov.uk/businessandpartners/syndication/
    
    Save the the routes as ./sourcedata/routes.csv
    
    It takes the original file from TfL, fixes them to use semicolons (because sqlite's
    CSV parser is really dumb and can't deal with quoted values) and then converts it to
    the database file ./db/whensmybus.geodata.db
    
    The data used to be in two separate tables, one for locations and one for routes, but TfL
    have de-normalised the data and now all the relevant data is in the routes table. The locations
    table, sourced from a file called locations.csv, is thus deprecated
    
    """ 
    sql = ""

    for inputpath in ('routes.csv',):   # Used to be ('routes.csv', 'locations.csv',)
    
        # Fix CSV - replace commas with semi-colons, allow sqlite to import without cocking it all up
        inputfile = open('./sourcedata/' + inputpath)
        reader = csv.reader(inputfile)
        fieldnames = reader.next()  # Skip first line (fieldnames)
    
        outputpath = inputpath.replace('.csv', '.ssv')
        outputfile = open('./sourcedata/' + outputpath, 'w')
        writer = csv.writer(outputfile, delimiter=";")
        
        for line in reader:
            writer.writerow(line)
        outputfile.flush()
        outputfile.close()
    
        tablename = inputpath.split('.')[0]
    
        integer_values = ('Location_Easting',
                        'Location_Northing',
                        'Heading',
                        'Virtual_Bus_Stop',
                        'Run',
                        'Sequence',)
                        
        fieldnames = ['%s%s' % (f, integer_values.count(f) and ' INT' or '') for f in fieldnames]
        
        # Produce SQL for this table
        sql += "drop table if exists %s;\r\n" % tablename
        sql += "create table %s(%s);\r\n" % (tablename, ", ".join(fieldnames))
        sql += '.separator ";"\r\n'
        sql += ".import %s %s\r\n" % ('./sourcedata/' + outputpath, tablename)
        sql += "delete from %s WHERE Virtual_Bus_Stop;\r\n" % tablename
        sql += "\r\n"
    
    sql += "CREATE INDEX route_index ON routes (Route);\r\n"
    sql += "CREATE INDEX route_run_index ON routes (Route, Run);\r\n"
    sql += "CREATE INDEX route_stop_index ON routes (Route, Bus_Stop_Code);\r\n"
    
    tempf = tempfile.NamedTemporaryFile('w')
    tempf.write(sql)
    tempf.flush()
    print subprocess.check_output(["sqlite3", "./db/whensmybus.geodata.db"], stdin=open(tempf.name))

def import_tube_xml_to_db():
    """
    Utility script that produces the script for converting TfL's Tube data KML into a sqlite database
        
    Pulls together data from two files:
    
    1. The data for Tube station codes & line details, from:
    https://raw.github.com/blech/gae-fakesubwayapis-data/d365a8b56d7b5abfec378816e3d91fb901f0cc59/data/tfl/stops.txt
    corrected for station names, and saved as tube-references.csv
    
    2. The data for Tube station locations, originally from TfL but augmented with new data (Heathrow Terminal 5) 
    corrected for station names (e.g. Shepherd's Bush Market), and saved as tube-locations.kml
    
    """
    tablename = 'locations'
    
    fieldnames = ('Name', 'Code', 'Line', 'Location_Easting INT', 'Location_Northing INT')
    
    sql = ""
    sql += "drop table if exists %s;\r\n" % tablename
    sql += "create table %s(%s);\r\n" % (tablename, ", ".join(fieldnames))

    stations = {}
    
    dom = parse(open('./sourcedata/tube-locations.kml'))
    station_geodata = dom.getElementsByTagName('Placemark')    
    for station in station_geodata:
    
        name = station.getElementsByTagName('name')[0].firstChild.data.strip().replace(' Station', '')
        style = station.getElementsByTagName('styleUrl')[0].firstChild.data.strip()
        # Ignore non-Tube stations
        if style != "#tubeStyle" or name in ('Shadwell', 'Wapping', 'Rotherhithe', 'Surrey Quays', 'New Cross', 'New Cross Gate'):
            continue

        coordinates = station.getElementsByTagName('coordinates')[0].firstChild.data.strip()
        (lon, lat) = tuple([float(c) for c in coordinates.split(',')[0:2]])
        (lat, lon) = convertWGS84toOSGB36(lat, lon)[:2]
        (easting, northing) = LatLongToOSGrid(lat, lon)
        gridref = gridrefNumToLet(easting, northing)
        stations[name.lower()] = { 'Name' : name, 'Location_Easting' : easting, 'Location_Northing' : northing, 'Code' : '', 'Lines' : '' }

    tube_data = open('./sourcedata/tube-references.csv')
    reader = csv.reader(tube_data)
    fieldnames = reader.next()
    for line in reader:
        code = line[0]
        name = line[1]
        lines = line[-1].split(";")
        if name.lower() in stations:
            stations[name.lower()]['Code'] = code
            stations[name.lower()]['Lines'] = lines            
        else:
            print "Cannot find %s in geodata!" % name
        
    for station in stations.values():
        if not station['Code']:
            print "Could not find a code for %s!" % station['Name']
            sql += "insert into locations values (\"%s\");\r\n" % '", "'.join((station['Name'], '', '', str(station['Location_Easting']), str(station['Location_Northing'])))
            
        else:
            for line in station['Lines']:
                if line != 'O': 
                    sql += "insert into locations values (\"%s\");\r\n" % '", "'.join((station['Name'], station['Code'], line, str(station['Location_Easting']), str(station['Location_Northing'])))

    sql += "CREATE INDEX code_index ON locations (code);\r\n"

    tempf = tempfile.NamedTemporaryFile('w')
    tempf.write(sql)
    tempf.flush()
    print subprocess.check_output(["sqlite3", "./db/whensmytube.geodata.db"], stdin=open(tempf.name))


if __name__ == "__main__":
    #import_bus_csv_to_db()
    import_tube_xml_to_db()
    pass