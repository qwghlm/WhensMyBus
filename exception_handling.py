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
    
        # WhensMyBus Fatal errors
        'blank_tweet'     : "I need to have a bus number in order to find the times for it",
        'placeinfo_only'  : "The Place info on your Tweet isn't precise enough http://bit.ly/rCbVmP Please enable GPS on your device, or specify '%s from <place>'",
        'no_geotag'       : "Your Tweet wasn't geotagged. Please make sure you have GPS enabled, or say '%s from <placename>'",
        'dms_not_taggable': "Direct messages can't use geotagging. Please send your message in the format '%s from <placename>'",
        'not_in_uk'       : "You do not appear to be located in the United Kingdom",    
        'not_in_london'   : "You do not appear to be located in the London Buses area", 
        'bad_stop_id'     : "I couldn't recognise the number you gave me (%s) as a valid bus stop ID",
        'no_stops_nearby' : "I could not find any bus stops near you",
        'tfl_server_down' : "I can't access TfL's servers right now - they appear to be down :(", 
        
        # WhensMyBus Non-Fatal errors
        'nonexistent_bus' : "I couldn't recognise the number you gave me (%s) as a London bus",     
        'no_arrival_data' : "There's no data from TfL for the %s - most likely no bus is due",
        'stop_name_not_found' : "I couldn't find any bus stops on the %s route by that name (%s)",
        'stop_id_not_found'  : "The %s route doesn't call at the stop with ID %s",
                
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
        self.msgid = msgid
        self.value = value[:115]

    def __str__(self):
        """
        Return a string representation of this Exception
        """
        return repr(self.value)
