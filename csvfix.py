#!/usr/bin/env python
"""
Utility script that produces the script for converting TfL's CSV into sqlite

If you are updating the database, you first have to download the CSV file
from the TfL website: http://www.tfl.gov.uk/businessandpartners/syndication/

Save the the routes as ./sourcedata/routes.csv

It takes the original file from TfL, fixes them to use semicolons (because sqlite's
CSV parser is really dumb and can't deal with quoted values) and then converts it to
the database file ./db/whensmybus.geodata.db

The data used to be in two separate tables, one for locations and one for routes, but TfL
have de-normalised the data and now all the relevant data is in the routes table. The locations
table, sourced from a file called locations.csv, is thus deprecated

""" 
import csv
import subprocess
import tempfile

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

f = tempfile.NamedTemporaryFile('w')
f.write(sql)
f.flush()
print subprocess.check_output(["sqlite3", "./db/whensmybus.geodata.db"], stdin=open(f.name))
