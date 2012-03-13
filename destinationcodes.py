"""
An experimental script that takes current Tube data from TfL, scrapes it to find every possible existing
platform, destination code and destination name, and puts it into a database to help with us producing
better output for users
"""
from pprint import pprint

from lib.browser import WMTBrowser
from lib.database import WMTDatabase
from lib.locations import WMTLocations
from lib.models import TubeTrain, RailStation


line_codes = ('B', 'C', 'D', 'H', 'J', 'M', 'N', 'P', 'V', 'W')


def scrape_tfl_destination_codes():
    """
    Scrape codes from TfL's TrackerNet and save to a database
    """
    database = WMTDatabase("whensmytube.destinationcodes.db")
    browser = WMTBrowser()
    destination_summary = {}
    for line_code in line_codes:
        tfl_url = "http://cloud.tfl.gov.uk/TrackerNet/PredictionSummary/%s" % line_code
        try:
            train_data = browser.fetch_xml_tree(tfl_url)
        except Exception:
            print "Couldn't get data for %s" % line_code
            continue

        for train in train_data.findall('T'):
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

    rows = database.get_rows("SELECT destination_name, line_code FROM destination_codes")
    for row in rows:
        destination = TubeTrain(row[0], "", "1200", "", "", "").get_clean_destination_name()
        if destination in ("Unknown", "Special", "Out Of Service"):
            continue
        if destination.startswith('Br To') or destination in ('Network Rail', 'Chiltern Toc'):
            continue
        if not geodata.find_fuzzy_match({}, destination, RailStation):
            print "Destination %s on %s not found in locations database" % (row[0], row[1])

if __name__ == "__main__":
    scrape_tfl_destination_codes()
    check_tfl_destination_codes()
