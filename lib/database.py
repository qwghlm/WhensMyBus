#!/usr/bin/env python
"""
Database client for When's My Transport
"""
import logging
import sqlite3
import os

HOME_DIR = os.path.dirname(os.path.abspath(__file__))

def load_database(dbfilename):
    """
    Helper function to load a database and return links to it and its cursor
    """
    logging.debug("Opening database %s", dbfilename)
    dbs = sqlite3.connect(HOME_DIR + '/../db/' + dbfilename)
    dbs.row_factory = sqlite3.Row
    return (dbs, dbs.cursor())