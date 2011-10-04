#!/usr/bin/env python
"""
Utility script that produces the script for converting TfL's CSV into sqlite

If you are updating the database, you first have to download the CSV files
from the TfL website: http://www.tfl.gov.uk/businessandpartners/syndication/

Save the bus stop locations as ./sourcedata/locations.csv
And save the routes as ./sourcedata/routes.csv

It takes the original files from TfL, fixes them to use semicolons (because sqlite's
CSV parser is really dumb and can't deal with quoted values) and then outputs a
script to import it on the command line in sqlite

""" 
import csv

print ""
print "# All done!"
print "# After running this script to fix the files you will need to "
print "# import them into sqlite. First you run this command:"
print ""
print "sqlite3 whensmybus.sqlite.db"
print ""
print "# And then run the following commands inside the sqlite console:"
print ""

for inputpath in ('locations.csv','routes.csv'):

    # Fix CSV - replace commas with semi-colons, allow sqlite to import without cocking it all up
    inputfile = open('./sourcedata/' + inputpath)
    reader = csv.reader(inputfile)
    reader.next()  # Skip first line (fieldnames)

    outputpath = inputpath.replace('.csv', '.ssv')
    outputfile = open('./sourcedata/' + outputpath, 'w')
    writer = csv.writer(outputfile, delimiter=";")
    
    for line in reader:
        writer.writerow(line)
    outputfile.flush()
    outputfile.close()
    
    # Get fieldnames from original file
    inputfile = open('./sourcedata/' + inputpath)
    reader = csv.reader(inputfile)

    tablename = inputpath.split('.')[0]
    fieldnames = reader.next()
    
    # Produce SQL for this table
    print "drop table %s;" % tablename
    print "create table %s(%s);" % (tablename, ", ".join(fieldnames))
    print '.separator ";"'
    print ".import %s %s" % ('./sourcedata/' + outputpath, tablename)
    print ""
