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
        self.db_connection = sqlite3.connect(DB_PATH + '/' + dbfilename)
        self.db_connection.row_factory = sqlite3.Row
        self.cursor = self.db_connection.cursor()

    def write_query(self, sql, args=()):
        """
        Performs an insert or update query on the database
        """
        self.cursor.execute(sql, args)
        self.db_connection.commit()

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

    def check_existence_of(self, table_name, column, value):
        """
        Check to see if any row in the table has the value in column; returns True if exists, False if not
        """
        (where_statement, where_values) = self.make_where_statement(table_name, {column: value})
        rows = self.get_rows("SELECT * FROM %s WHERE %s" % (table_name, where_statement), where_values)
        return bool(rows)

    def get_max_value(self, table_name, column, params):
        """
        Return the maximum value of integer column out of the table given the params given
        """
        (where_statement, where_values) = self.make_where_statement(table_name, params)
        return int(self.get_value("SELECT MAX(\"%s\") FROM %s WHERE %s" % (column, table_name, where_statement), where_values))

    def make_where_statement(self, table_name, params):
        """
        Convert a dictionary of params, checks it against the table, and returns a tuple of those params for use in sqlite
            First eleemnt of tuple is statement containing statement that can go after a WHERE
            Second elements of tuple is a tuple, containing the values for sqlite to safely inject into the statement
        """
        if not params:
            return (" 1 ", ())
        column_names = [row[1] for row in self.get_rows("PRAGMA table_info(%s)" % table_name)]
        for column in params.keys():
            if column not in column_names:
                raise KeyError("Error: Database column %s not in our database" % column)
        # Construct our SQL statement
        where_statement = ' AND '.join(['"%s" = ?' % column for (column, value) in sorted(params.items())])
        where_values = tuple([value for (column, value) in sorted(params.items())])
        return (where_statement, where_values)
