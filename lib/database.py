#!/usr/bin/env python
"""
Database client for When's My Transport
"""
import logging
import sqlite3
import os

DB_PATH = os.path.normpath(os.path.dirname(os.path.abspath(__file__)) + '/../db/')

class WMTDatabase():
    """
    Class representing database 
    """
    def __init__(self, dbfilename):
        """
        Load a database
        """
        logging.debug("Opening database %s", dbfilename)
        self.database = sqlite3.connect(DB_PATH + '/' + dbfilename)
        self.database.row_factory = sqlite3.Row
        self.cursor = self.database.cursor()
        
    def write_query(self, sql, args=()):
        """
        Performs an insert or update query on the database
        """
        self.cursor.execute(sql, args)
        self.database.commit()
    
    def get_rows(self, sql, args=()):
        """
        Returns an iterator representing all the rows from the query's results
        """
        self.cursor.execute(sql, args)
        rows = self.cursor.fetchall()
        return rows

    def get_row(self, sql, args=()):
        """
        Returns the first row from the query's results. Returns None if no result
        """
        self.cursor.execute(sql, args)
        row = self.cursor.fetchone()
        return row
        
    def get_value(self, sql, args=()):
        """
        Returns the first column of the first row as a single value from the query's results. Returns None if no result
        """
        row = self.get_row(sql, args)
        value = row and row[0]
        return value

