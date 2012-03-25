#!/usr/bin/env python
"""
An experimental script that takes current Tube data from TfL, scrapes it to find every possible existing
platform, destination code and destination name, and puts it into a database to help with us producing
better output for users
"""
from pprint import pprint

from datatools import get_tfl_prediction_summaries
from lib.database import WMTDatabase
from lib.dataparsers import filter_tube_train
from lib.locations import WMTLocations
from lib.models import TubeTrain, RailStation


def scrape_tfl_destination_codes():
    """
    Scrape codes from TfL's TrackerNet and save to a database
    """
    database = WMTDatabase("whensmytube.destinationcodes.db")
    destination_summary = {}
    all_train_data = get_tfl_prediction_summaries()
    for (line_code, train_data) in all_train_data.items():
        for train in train_data.findall('.//T'):
            destination = train.attrib['DE']
            destination_code = train.attrib['D']
            if destination_summary.get(destination_code, destination) != destination and destination_code != '0':
                print "Error - mismatching destinations: %s (existing) and %s (new) with code %s" \
                      % (destination_summary[destination_code], destination, destination_code)

            database.write_query("INSERT OR IGNORE INTO destination_codes VALUES (?, ?, ?)", (destination_code, line_code, destination))
            destination_summary[destination_code] = destination
    pprint(destination_summary)


def check_tfl_destination_codes():
    """
    Audit codes we have recorded and make sure that they are all fine
    """
    # Check to see if destination is in our database
    geodata = WMTLocations('whensmytube')
    database = WMTDatabase("whensmytube.destinationcodes.db")

    rows = database.get_rows("SELECT destination_name, destination_code, line_code FROM destination_codes")
    for (destination_name, destination_code, line_code) in rows:
        if not filter_tube_train(destination_name, str(destination_code)):
            continue
        train = TubeTrain(destination_name, "", "1200", "", "")
        destination = train.get_destination_no_via()
        if destination != "Unknown" and not geodata.find_fuzzy_match({}, destination, RailStation):
            print "Destination %s (%s) on %s not found in locations database" % (destination_name, destination_code, line_code)
        via = train.get_via()
        if via and not geodata.find_fuzzy_match({}, via, RailStation):
            print "Via %s (from %s) on %s not found in locations database" % (via, destination_name, line_code)

if __name__ == "__main__":
    scrape_tfl_destination_codes()
    check_tfl_destination_codes()
