#!/usr/bin/env python
"""
Application settings handling for When's My Transport
"""
import cPickle as pickle
from lib.database import WMTDatabase


class WMTSettings():
    """
    Class representing a settings read/write handler (for remembering data between sessions" for When's My Transport

    """
    def __init__(self, instance_name):
        self.instance_name = instance_name
        self.settingsdb = WMTDatabase('%s.settings.db' % self.instance_name)
        self.settingsdb.write_query("create table if not exists %s_settings (setting_name unique, setting_value)" % self.instance_name)

    def get_setting(self, setting_name):
        """
        Fetch value of setting from settings database
        """
        # Generic Exception handling
        # pylint: disable=W0703
        setting_value = self.settingsdb.get_value("select setting_value from %s_settings where setting_name = ?" % self.instance_name, (setting_name,))
        # Try unpickling, if this doesn't work then return the raw value (to deal with legacy databases)
        if setting_value is not None:
            try:
                setting_value = pickle.loads(setting_value.encode('utf-8'))
            except Exception:  # Pickle can throw loads of weird exceptions, gotta catch them all!
                pass
        return setting_value

    def update_setting(self, setting_name, setting_value):
        """
        Set value of named setting in settings database
        """
        setting_value = pickle.dumps(setting_value)
        self.settingsdb.write_query("insert or replace into %s_settings (setting_name, setting_value) values (?, ?)" % self.instance_name,
                                    (setting_name, setting_value))
