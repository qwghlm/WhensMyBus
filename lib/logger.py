#!/usr/bin/env python
"""
Logging handler for When's My Transport
"""
import logging
import logging.handlers
import os
import sys

LOG_PATH = os.path.normpath(os.path.dirname(os.path.abspath(__file__)) + '/../logs/')
def setup_logging(instance_name, silent_mode, debug_level):
    """
    Set up some logging for this instance
    """
    if len(logging.getLogger('').handlers) == 0:
        logging.basicConfig(level=logging.DEBUG, filename=os.devnull)

        # Logging to stdout shows info or debug level depending on user config file. Setting silent to True will override either
        if silent_mode:
            console_output = open(os.devnull, 'w')
        else:
            console_output = sys.stdout
        console = logging.StreamHandler(console_output)
        console.setLevel(logging.__dict__[debug_level])
        console.setFormatter(logging.Formatter('%(message)s'))

        # Set up some proper logging to file that catches debugs
        logfile = os.path.abspath('%s/%s.log' % (LOG_PATH, instance_name))
        rotator = logging.handlers.RotatingFileHandler(logfile, maxBytes=256 * 1024, backupCount=99)
        rotator.setLevel(logging.DEBUG)
        rotator.setFormatter(logging.Formatter('%(asctime)s %(levelname)-8s %(message)s'))
        logging.getLogger('').addHandler(console)
        logging.getLogger('').addHandler(rotator)
        logging.debug("Initializing...")
