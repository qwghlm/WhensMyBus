#!/usr/bin/env python
"""
Database client for When's My Transport
"""
import logging
import sqlite3
import os
import pickle

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

class WMTSettings():
    """
    Class representing settings database
    """
    def __init__(self, instance_name):
        self.instance_name = instance_name
        self.settingsdb = WMTDatabase('%s.settings.db' % self.instance_name)
        self.settingsdb.write_query("create table if not exists %s_settings (setting_name unique, setting_value)" % self.instance_name)

    def get_setting(self, setting_name):
        """
        Fetch value of setting from settings database
        """
        #pylint: disable=W0703
        setting_value = self.settingsdb.read_value("select setting_value from %s_settings where setting_name = ?" % self.instance_name, (setting_name,))
        # Try unpickling, if this doesn't work then return the raw value (to deal with legacy databases)
        if setting_value is not None:
            try:
                setting_value = pickle.loads(setting_value.encode('utf-8'))
            except Exception: # Pickle can throw loads of weird exceptions, gotta catch them all!
                pass
        return setting_value

    def update_setting(self, setting_name, setting_value):
        """
        Set value of named setting in settings database
        """
        setting_value = pickle.dumps(setting_value)
        self.settingsdb.write_query("insert or replace into %s_settings (setting_name, setting_value) values (?, ?)" % self.instance_name,
                                    (setting_name, setting_value))