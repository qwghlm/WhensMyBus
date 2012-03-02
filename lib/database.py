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
    Class representing a database client for When's My Transport
    """
    def __init__(self, dbfilename):
        """
        Initialise & load a database from file
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
        Returns a list of sqlite3.Row objects, representing all the rows from the query's results
        """
        self.cursor.execute(sql, args)
        rows = self.cursor.fetchall()
        return rows

    def get_row(self, sql, args=()):
        """
        Returns the first row from the query's results, as a sqlite3.Row object. Returns None if no result
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
