#!/usr/bin/env python
"""
Data importing tools for WhensMyTransport - import TfL's data into an easier format for us to use
"""
# Standard Python libraries
import csv
import os
import cPickle as pickle
import re
import sys
import subprocess
import tempfile
from math import sqrt
from pprint import pprint

# Library available from http://code.google.com/p/python-graph/
from pygraph.classes.digraph import digraph

import nltk

# Local files
from lib.browser import WMTBrowser
from lib.database import WMTDatabase
from lib.geo import convertWGS84toOSGB36, LatLongToOSGrid
from lib.listutils import unique_values
from whensmytrain import get_line_code, LINE_NAMES


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
    reader = csv.DictReader(inputfile)
    fieldnames = reader.fieldnames
    fields_to_delete = ('Stop_Code_LBSL', 'Naptan_Atco')

    outputpath = inputpath.replace('.csv', '.ssv')
    outputfile = open(outputpath, 'w')
    output_fieldnames = [field for field in fieldnames if field not in fields_to_delete]
    writer = csv.DictWriter(outputfile, output_fieldnames, delimiter=";")

    for line in reader:
        for field in fields_to_delete:
            del line[field]
        writer.writerow(line)
    outputfile.flush()
    outputfile.close()

    tablename = 'locations'

    integer_values = ('Location_Easting',
                      'Location_Northing',
                      'Heading',
                      'Virtual_Bus_Stop',
                      'Run',
                      'Sequence',)
    output_fieldnames[output_fieldnames.index('Stop_Name')] = 'Name'
    output_fieldnames = ['%s%s' % (f.lower(), f in integer_values and ' INT' or '') for f in output_fieldnames]

    # Produce SQL for this table
    sql = "drop table if exists %s;\r\n" % tablename
    sql += "drop table if exists routes;\r\n"
    sql += "create table %s(%s);\r\n" % (tablename, ", ".join(output_fieldnames))
    sql += '.separator ";"\r\n'
    sql += ".import %s %s\r\n" % (outputpath, tablename)
    sql += "delete from %s WHERE virtual_bus_stop;\r\n" % tablename
    sql += "\r\n"

    sql += "CREATE INDEX route_index ON locations (route);\r\n"
    sql += "CREATE INDEX route_run_index ON locations (route, run);\r\n"
    sql += "CREATE INDEX route_stop_index ON locations (route, bus_stop_code);\r\n"

    export_sql_to_db("./db/whensmybus.geodata.db", sql)
    # Drop SSV file now we don't need it
    os.unlink(outputpath)


def import_dlr_xml_to_db():
    """
    Utility script that produces the script for converting TfL's DLR data KML into a sqlite database

    Pulls together data from two files:

    1. The data for Tube & DLR station locations, originally from TfL but augmented with new data (Heathrow Terminal 5)
    corrected for station names (e.g. Shepherd's Bush Market), and saved as tube-locations.kml

    2. Data for station codes and station names, scraped from the DLR website (sorry guys), saved as dlr-references.csv
    """
    fieldnames = ('name', 'code', 'line', 'location_easting INT', 'location_northing INT', 'inner', 'outer')

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
            stations[name.lower()]['code'] = code
            stations[name.lower()]['line'] = 'DLR'
            stations[name.lower()]['inner'] = ''
            stations[name.lower()]['outer'] = ''
        else:
            print "Cannot find %s from dlr-references in geodata!" % name

    for name in stations:
        if not stations[name]['code']:
            print "Cannot find %s from geodata in dlr-references!" % name

    rows = [[station[fieldname.split(' ')[0]] for fieldname in fieldnames] for station in stations.values()]
    export_rows_to_db("./db/whensmytrain.geodata.db", "locations", fieldnames, rows)


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
    fieldnames = ('name', 'code', 'line', 'location_easting INT', 'location_northing INT', 'inner', 'outer')

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
            stations[name.lower()]['code'] = code
            stations[name.lower()]['lines'] = lines
        else:
            print "Cannot find %s from tube-references in geodata!" % name

    # Parse CSV file of what direction the "Inner" and "Outer" rails are for stations on circular loops
    circle_data = open('./sourcedata/circle_platform_data.csv')
    reader = csv.reader(circle_data)
    reader.next()
    for line in reader:
        name = line[1]
        if name.lower() in stations:
            stations[name.lower()]['inner'] = line[3]
            stations[name.lower()]['outer'] = line[4]
        else:
            print "Cannot find %s from circle_platform_data in geodata!" % name

    rows = []
    for station in stations.values():
        station_name = station['name']
        # Shorten stations such as Hammersmith/Edgware Road which are disambiguated by brackets, get rid of them
        if station_name and station_name.find('(') > -1 and station_name != "Kensington (Olympia)":
            station_name = station_name[:station_name.find('(') - 1]
            station['name'] = station_name

        if not station['code']:
            print "Could not find a station code for %s!" % station['name']
        else:
            for line in station['lines']:
                field_data = (station['name'], station['code'], line,
                              station['location_easting'], station['location_northing'],
                              station['inner'], station['outer'])
                rows.append(field_data)

    export_rows_to_db("./db/whensmytrain.geodata.db", "locations", fieldnames, rows, ('name', 'line'), delete_existing=True)


def import_network_data_to_graph():
    """
    Import data from a file describing the edges of the Tube network and turn it into a graph object which we pickle and save
    """
    database = WMTDatabase("whensmytrain.geodata.db")

    # Adapted from https://github.com/smly/hubigraph/blob/fa23adc07c87dd2a310a20d04f428f819d43cbdb/test/LondonUnderground.txt
    # which is a CSV of all edges in the network
    reader = csv.reader(open('./sourcedata/tube-connections.csv'))
    reader.next()

    # First we organise our data so that each station knows which lines it is on, and which stations it connects to
    stations_neighbours = {}
    interchanges_by_foot = []
    for (station1, station2, line) in reader:
        if line in ("National Rail", "East London"):
            continue
        if line == "Walk":
            interchanges_by_foot.append((station1, station2))
        else:
            # When a line splits into two branches, we don't want people being able to travel from one branch to another without
            # changing. So for these special cases, we mark the transitions as being in a particular direction in the CSV, with the
            # direction coming after a colon (e.g. "Leytonstone:Northbound","Wanstead","Central" and "Snaresbrook","Leytonstone:Southbound","Central"
            # Effectively the station has become two nodes, and now you cannot go directly from Snaresbrook to Wanstead.
            direction = station1.partition(':')[2]  # Blank for most
            station1 = station1.partition(':')[0]  # So station name becomes just e.g. Leytonstone

            station_data = stations_neighbours.get(station1, [])
            if (station2, direction, line) not in station_data:
                station_data += [(station2, direction, line)]
            stations_neighbours[station1] = station_data

    # Sanity-check our data and make sure it matches database
    canonical_data = database.get_rows("SELECT * FROM locations")
    canonical_station_names = unique_values([canonical['name'] for canonical in canonical_data])
    for station in sorted(stations_neighbours.keys()):
        if station not in canonical_station_names:
            print "Error! %s is not in the canonical database of station names" % station
        for (neighbour, direction, line) in stations_neighbours[station]:
            line_code = get_line_code(line)
            if not database.get_value("SELECT name FROM locations WHERE name=? AND line=?", (station, line_code)):
                print "Error! %s is mistakenly labelled as being on the %s line in list of nodes" % (station, line)
    for station in sorted(canonical_station_names):
        if station not in stations_neighbours.keys():
            print "Error! %s is not in the list of station nodes" % station
            continue
        database_lines = database.get_rows("SELECT line FROM locations WHERE name=?", (station,))
        for row in database_lines:
            if row['line'] not in [get_line_code(line) for (neighbour, direction, line) in stations_neighbours[station]]:
                print "Error! %s is not shown as being on the %s line in the list of nodes" % (station, row['line'])

    # Produce versions of the graphs for unique lines
    graphs = {}
    lines = unique_values([line for station in stations_neighbours.values() for (neighbour, direction, line) in station])
    for line in lines:
        subset_of_stations = {}
        for (station_name, neighbours) in stations_neighbours.items():
            neighbours_for_this_line = [neighbour for neighbour in neighbours if neighbour[2] == line]
            if neighbours_for_this_line:
                subset_of_stations[station_name] = neighbours_for_this_line
        graphs[get_line_code(line)] = create_graph_from_dict(subset_of_stations, database, interchanges_by_foot)
    graphs['All'] = create_graph_from_dict(stations_neighbours, database, interchanges_by_foot)

    pickle.dump(graphs, open("./db/whensmytrain.network.gr", "w"))


def parse_stations_from_kml(filter_function=lambda a, b: True):
    """
    Parses KML file of stations & associated data, and returns them as a dictionary
    """
    stations = {}
    kml = WMTBrowser().fetch_xml_tree('file:///%s/sourcedata/tube-locations.kml' % os.getcwd())
    for station in kml.findall('.//Placemark'):
        name = station.find('name').text.strip().replace(' Station', '')
        style = station.find('styleUrl').text
        if filter_function(name, style):
            coordinates = station.find('Point/coordinates').text
            (lon, lat) = tuple([float(c) for c in coordinates.split(',')[0:2]])
            (lat, lon) = convertWGS84toOSGB36(lat, lon)[:2]
            (easting, northing) = LatLongToOSGrid(lat, lon)
            stations[name.lower()] = {'name': name, 'location_easting': str(easting), 'location_northing': str(northing),
                                      'code': '', 'lines': '', 'inner': '', 'outer': ''}
    return stations


def export_rows_to_db(db_filename, tablename, fieldnames, rows, indices=(), delete_existing=False):
    """
    Generic database SQL composing & export function
    """
    sql = ""
    if delete_existing:
        sql += "drop table if exists %s;\r\n" % tablename
        sql += "create table %s(%s);\r\n" % (tablename, ", ".join(fieldnames))
        for index in indices:
            sql += "CREATE INDEX %s_index ON %s (%s);\r\n" % (index, tablename, index)

    for field_data in rows:
        sql += "insert into locations values "
        sql += "(\"%s\");\r\n" % '", "'.join(field_data)

    export_sql_to_db(db_filename, sql)


def export_sql_to_db(db_filename, sql):
    """
    Generic database SQL export function
    """
    tempf = tempfile.NamedTemporaryFile('w')
    tempf.write(sql)
    tempf.flush()
    print subprocess.check_output(["sqlite3", db_filename], stdin=open(tempf.name))


def create_graph_from_dict(stations, database, interchanges_by_foot):
    """
    Take a dictionary of stations and their neighbours and return a digraph object
    """
    # Start creating our directed graph - first by adding all the nodes. Each station is represented by multiple nodes: one to represent
    # the entrance, and one the exit, and then at least one for every line the station serves (i.e. the platforms). This seems complicated, but is
    # designed so that we can accurately simulate the extra delay an interchange takes by adding weighted edges between the platforms
    #
    # If the station needs to have directional info handled (e.g. the line is splitting, or looping on itself), we have one node for each
    # direction on each line that needs to be split. Else the direction is an empty string and so both directions are handled by the same node
    graph = digraph()

    for (station, station_data) in stations.items():
        graph.add_node("%s:entrance" % station)
        graph.add_node("%s:exit" % station)
        directions_and_lines = unique_values([(direction, line) for (neighbour, direction, line) in station_data])
        for (direction, line) in directions_and_lines:
            graph.add_node(":".join((station, direction, line)))

    # Now we add the nodes for each line - connecting each set of platforms for each station to the neighbouring stations
    for (station, station_data) in stations.items():
        for (neighbour, direction, line) in station_data:
            neighbour_name = neighbour.partition(':')[0]
            departure = "%s:%s:%s" % (station, direction, line)
            arrival = "%s:%s:%s" % (neighbour_name, neighbour.partition(':')[2], line)

            sql = "SELECT location_easting, location_northing FROM locations WHERE name=?"
            station_position = database.get_row(sql, (station,))
            neighbour_position = database.get_row(sql, (neighbour_name,))
            distance = sqrt((station_position[0] - neighbour_position[0]) ** 2 + (station_position[1] - neighbour_position[1]) ** 2)
            time = 0.5 + distance / 600  # Assume 36km/h for tube trains, which is 36000 m/h or 600 m/min, plus 30 secs for stopping
            graph.add_edge((departure, arrival), wt=time)

            if (station, line) not in [(s.partition(':')[0], l) for (s, _d, l) in stations[neighbour_name]]:
                # Note, for Heathrow Terminal 4 (the only one-way station on the network), this is fine
                print "Warning! Connection from %s to %s but not %s to %s on %s line" % (station, neighbour_name, neighbour_name, station, line)

    # After that, we can add the interchanges between each line at each station, and the movements from entrance and to the exit.
    # Entrances and exits have zero travel time; because the graph is directed, it is not possible for us to change trains by
    # going to an exit and then back to a platform (or likewise with an entrance); we are forced to use the interchange edge,
    # which has an expensive travel time of 6 minutes
    for (station, station_data) in stations.items():
        graph.add_edge(("%s:entrance" % station, "%s:exit" % station), wt=0)
        directions_and_lines = unique_values([(direction, line) for (neighbour, direction, line) in station_data])
        for (direction, line) in directions_and_lines:
            graph.add_edge(("%s:entrance" % station, "%s:%s:%s" % (station, direction, line)), wt=2)
            graph.add_edge(("%s:%s:%s" % (station, direction, line), "%s:exit" % station), wt=0)
            for (other_direction, other_line) in directions_and_lines:
                if line != other_line or direction != other_direction:
                    graph.add_edge(("%s:%s:%s" % (station, direction, line), "%s:%s:%s" % (station, other_direction, other_line)), wt=6)

    # Add in interchanges by foot between different stations
    for (station1, station2) in interchanges_by_foot:
        if station1 in stations.keys() and station2 in stations.keys():
            graph.add_edge(("%s:exit" % station1, "%s:entrance" % station2), wt=10)

    #Remove altogether some expensive changes (Edgware Road, Paddington)
    expensive_interchanges = (
        ('Edgware Road', '', 'Bakerloo', None),
        ('Paddington', 'Hammersmith Branch', 'Hammersmith & City', 10),
        ('Paddington', 'Hammersmith Branch', 'Circle', 10)
    )
    for (station, direction, line, weight) in expensive_interchanges:
        node = "%s:%s:%s" % (station, direction, line)
        if not graph.has_node(node):
            continue
        for outbound_node in list(graph.neighbors(node)):
            if outbound_node.startswith(station) and not outbound_node.endswith('exit'):
                graph.del_edge((node, outbound_node))
                if weight:
                    graph.add_edge((node, outbound_node), wt=weight)
        for inbound_node in list(graph.incidents(node)):
            if inbound_node.startswith(station) and not inbound_node.endswith('entrance'):
                graph.del_edge((inbound_node, node))
                if weight:
                    graph.add_edge((inbound_node, node), wt=weight)
    return graph


def scrape_odd_platform_directions(write_file=False):
    """
    Check Tfl Tube API for Underground platforms that are not designated with a *-bound direction, and (optionally)
    generates a blank CSV template for those stations with Inner/Outer Rail designations
    """
    database = WMTDatabase("whensmytrain.geodata.db")
    print "Platforms without a Inner/Outer Rail specification:"
    station_platforms = {}
    all_train_data = get_tfl_prediction_summaries()
    for (line_code, train_data) in all_train_data.items():
        for station in train_data.findall('S'):
            station_code = station.attrib['Code'][:3]
            station_name = station.attrib['N'][:-1]
            station_name = station_name.replace(" Circle", "")

            for platform in station.findall('P'):
                platform_name = platform.attrib['N']
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
        if not database.get_value("SELECT name FROM locations WHERE name=?", (station_name,)):
            errors.append("%s is not in the station database" % station_name)
    outputfile.flush()

    print ""
    for error in errors:
        print error

    outputfile.close()


def get_tfl_prediction_summaries():
    """
    Go through TfL's PredictionSummary API and return list of XML Trees for every single line
    """
    #pylint: disable=W0703
    browser = WMTBrowser()
    all_train_data = {}
    line_codes = ('B', 'C', 'D', 'H', 'J', 'M', 'N', 'P', 'V', 'W')
    for line_code in line_codes:
        tfl_url = "http://cloud.tfl.gov.uk/TrackerNet/PredictionSummary/%s" % line_code
        try:
            all_train_data[line_code] = browser.fetch_xml_tree(tfl_url)
        except Exception:
            print "Couldn't get data for %s" % line_code
            continue
    return all_train_data


def import_tube_xml_to_text_corpus():
    """
    Creates a corpus of text data for our parser to understand requests with
    """
    line_phrases = [nltk.word_tokenize(line_name) for line_name in LINE_NAMES]
    station_phrases = []
    for filename in ('tube-references.csv', 'dlr-references.csv'):
        station_phrases += [nltk.word_tokenize(line[1]) for line in csv.reader(open('./sourcedata/%s' % filename))][1:]

    # Organise bigram phrases - multiple wordings for stations and lines
    bigram_tokens = [[(token, 'TUBE_LINE') for token in phrase] for phrase in line_phrases]
    bigram_tokens += [[(token, 'TUBE_LINE') for token in phrase] + [('line', 'LINE')] for phrase in line_phrases]
    bigram_tokens += [[(token, 'STATION_WORD') for token in phrase] for phrase in station_phrases]
    bigram_tokens += [[('from', 'FROM')] + [(token, 'STATION_WORD') for token in phrase] for phrase in station_phrases]
    bigram_tokens += [[('to', 'TO')] + [(token, 'STATION_WORD') for token in phrase] for phrase in station_phrases]

    # Unigram phrases, as a fall-back - line words and any words that appear in stations but not line names
    line_tokens = set(reduce(lambda a, b: a + b, [phrase for phrase in LINE_NAMES]))
    station_tokens = set(reduce(lambda a, b: a + b, [phrase for phrase in station_phrases]))
    unigram_tokens = [[(token, 'TUBE_LINE') for token in line_tokens] + [(token, 'STATION_WORD') for token in station_tokens if token not in line_tokens]]

    tagging_regexes = [
        (r'^(from|From)$', 'FROM'),
        (r'^to(wards)?$', 'TO'),
        (r'^(line|Line)?$', 'LINE'),
        (r'^(please|thanks|thank|you)$', None),
        (r'^Docklands (Light Rail(way)?)?$', 'DLR_LINE_NAME'),
        (r'.*', 'UNKNOWN'),
    ]
    regex_tagger = nltk.RegexpTagger(tagging_regexes)
    unigram_tagger = nltk.UnigramTagger(unigram_tokens, backoff=regex_tagger)
    bigram_tagger = nltk.BigramTagger(bigram_tokens, backoff=unigram_tagger)
    pickle.dump(bigram_tagger, open("./db/whensmytrain.tagger.obj", "w"))

if __name__ == "__main__":
    #import_bus_csv_to_db()
    #import_tube_xml_to_db()
    #import_dlr_xml_to_db()
    #import_network_data_to_graph()
    #scrape_odd_platform_designations()
    import_tube_xml_to_text_corpus()
