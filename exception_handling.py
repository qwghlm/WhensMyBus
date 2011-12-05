"""
Module containing custom exceptions for WhensMyTransport
"""
import logging

class WhensMyTransportException(Exception):
    """
    Exception we use to signal send an error to the user
    """
    # Possible id => message pairings, so we can use a shortcode to summon a much more explanatory message
    # Why do we not just send the full string as a parameter to the Exception? Mainly so we can unit test (see testing.py)
    # but also as it saves duplicating string for similar errors (e.g. when TfL service is down)
    #
    # Error message should be no longer than 115 chars so we can put a username and the word Sorry and still be under 140
    exception_values = {
        # Bus stuff
        'blank_tweet'     : "I need to have a bus number in order to find the times for it",
        'nonexistent_bus' : "I couldn't recognise the number you gave me (%s) as a London bus",
        'placeinfo_only'  : "The Place info on your Tweet isn't precise enough. Please make sure you have GPS enabled, or say '%s from <place>'",
        'no_geotag'       : "Your Tweet wasn't geotagged. Please make sure you have GPS enabled on your Tweet, or say '%s from <place>'",
        'dms_not_taggable': "Direct messages can't use geotagging. Please send your message in the format '%s from <place>'",
        'bad_stop_id'     : "I couldn't recognise the number you gave me (%s) as a valid bus stop ID",
        'stop_id_mismatch': "That bus (%s) does not appear to stop at that stop (%s)",
        'stop_not_found'  : "I couldn't find any bus stops on your route by that name (%s)",
        'not_in_uk'       : "You do not appear to be located in the United Kingdom",
        'not_in_london'   : "You do not appear to be located in the London Buses area",
        'no_stops_nearby' : "I could not find any stops near you",
        'tfl_server_down' : "I can't access TfL's servers right now - they appear to be down :(",
        'no_arrival_data' : "There is no arrival data on the TfL website for your stop - most likely no buses are due",
        
        # Tube stuff
        'nonexistent_line' : "I couldn't recognise that line (%s) as a London Underground line",
    }
    
    def __init__(self, msgid, *string_params):
        """
        Fetch a message with the ID from the dictionary above
        String formatting params optional, only needed if there is C string formatting in the error message
        e.g. WhensMyBusException('nonexistent_bus', '214')
        """
        value = WhensMyTransportException.exception_values.get(msgid, '') % string_params
        super(WhensMyTransportException, self).__init__(value)
        logging.debug("Application exception encountered: %s", value)
        self.value = value[:115]

    def __str__(self):
        """
        Return a string representation of this Exception
        """
        return repr(self.value)
