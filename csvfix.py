# Utility script that produces the right code for converting TfL's CSV into sqllite
import csv
import sqlite3

print ""
print "sqlite3 whensmybus.sqlite.db"
print ""

for inputpath in ('locations.csv','routes.csv'):

    # Fix CSV - replace commas with semi-colons, allow sqlite to import without cocking it all up
    inputfile = open(inputpath)
    reader = csv.reader(inputfile)
    reader.next()  # Skip first line (fieldnames)

    outputpath = inputpath.replace('.csv', '.ssv')
    outputfile = open(outputpath, 'w')
    writer = csv.writer(outputfile, delimiter=";")
    
    for line in reader:
        writer.writerow(line)
    outputfile.flush()
    outputfile.close()
    
    # Get fieldnames from original file
    inputfile = open(inputpath)
    reader = csv.reader(inputfile)

    tablename = inputpath.split('.')[0]
    fieldnames = reader.next()
    
    # Produce SQL for this table
    print "drop table %s;" % tablename
    print "create table %s(%s);" % (tablename, ", ".join(fieldnames))
    print '.separator ";"'
    print ".import %s %s" % (outputpath, tablename)
    print ""
    
    

