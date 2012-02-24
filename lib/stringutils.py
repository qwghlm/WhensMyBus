#!/usr/bin/env python
"""
String utilities, including fuzzy string matching
"""
import difflib
import re
from pprint import pprint

# String utils

def capwords(phrase):
    """
    Capitalize each word in a string. A word is defined as anything with a space separating it from the next word.   
    """
    not_to_be_capitalized = ('via', 'CX')
    capitalized = ' '.join([s in not_to_be_capitalized and s or s.capitalize() for s in phrase.split(' ')])
    return capitalized
        
def cleanup_name_from_undesirables(name, undesirables):
    """
    Clean out every word in the iterable undesirables from the name supplied, and capitalize
    """
    for undesirable in undesirables:
        name = re.sub(undesirable, '', name, flags=re.I)
    name = re.sub(r' +', ' ', name.strip())
    return capwords(name)

def normalise_stop_name(name):
    """
    Normalise a bus stop name, sorting out punctuation, capitalisation, abbreviations & symbols
    """
    # Upper-case and abbreviate road names
    normalised_name = name.upper()
    for (word, abbreviation) in (('SQUARE', 'SQ'), ('AVENUE', 'AVE'), ('STREET', 'ST'), ('ROAD', 'RD'), ('STATION', 'STN'), ('PUBLIC HOUSE', 'PUB')):
        normalised_name = re.sub(r'\b' + word + r'\b', abbreviation, normalised_name)

    # Get rid of common words like 'The'
    for common_word in ('THE',):
        normalised_name = re.sub(r'\b' + common_word + r'\b', '', normalised_name)
        
    # Remove Tfl's ASCII symbols for Tube, rail, DLR & Tram
    for unwanted in ('<>', '#', '[DLR]', '>T<'):
        normalised_name = normalised_name.replace(unwanted, '')
    
    # Remove spaces and punctuation and return
    normalised_name = re.sub('[\W]', '', normalised_name)
    return normalised_name

def get_name_similarity(origin, stop):
    """
    Return a score between 0 and 100 of the strings' similarity, based on difflib's string similarity algorithm returning an integer
    between 0 (no match) and 100 (perfect). 70 or more seems to be a confident enough match 
    """
    # Based on https://github.com/seatgeek/fuzzywuzzy/blob/master/fuzzywuzzy/fuzz.py
    return int(100 * difflib.SequenceMatcher(None, origin, stop).ratio())

def get_bus_stop_name_similarity(origin, stop):
    """
    Custom similarity match for bus stops - takes into account many of them will be from train stations or bus stations
    """
    # Use the above function to normalise our names and facilitate easier comparison
    origin, stop = normalise_stop_name(origin), normalise_stop_name(stop)
    
    # Exact match is obviously best
    if origin == stop:
        return 100
        
    # If user has specified a station or bus station, then a partial match at start or end of string works for us
    # We prioritise, just slightly, names that have the match at the beginning
    if re.search("(BUS)?STN", origin):
        if stop.startswith(origin):
            return 95
        if stop.endswith(origin):
            return 94
            
    # If on the other hand, we add station or bus station to the origin name and it matches, that's also pretty good
    if re.search("^%s(BUS)?STN" % origin, stop):
        return 91
    if re.search("%s(BUS)?STN$" % origin, stop):
        return 90 
    
    # Else fall back on name similarity
    return get_name_similarity(origin, stop)

def get_rail_station_name_similarity(query, canonical):
    """
    Custom similarity for train stations - takes into account fact many people use abbreviated names
    """
    score = get_name_similarity(query, canonical)
    # For low-scoring matches, we try matching between a string the same size as the user query, if its shorter than the name
    # being tested against, so this works for e.g. Kings Cross matching King's Cross St Pancras
    if score < 70 and len(query) < len(canonical):
        abbreviated_score = get_name_similarity(query, canonical[:len(query)])
        if abbreviated_score >= 90:
            return abbreviated_score

    return score

def get_best_fuzzy_match(search_term, possible_values, lookup_key=None, comparison_function=get_name_similarity, minimum_confidence=70):
    """
    Get the best matching item in a list of possible_values that matches search_term
    If lookup_key is defined, assume each element of possible_values is a dict and lookup that key to do comparison
    Else will assume each element is same type as search_term (i.e. a string) and compare directly
    """
    # Get tuples of matches, each a (value, confidence) pair : confidence is between 0 and 100 and reflects 
    # how confident we are that that value (or its property) matches the term we have asked for
    if lookup_key:
        fuzzy_matches = [(value, comparison_function(search_term, value[lookup_key])) for value in possible_values]
    else:
        fuzzy_matches = [(value, comparison_function(search_term, value)) for value in possible_values]
        
    # Sort in order of confidence and pick the last one
    fuzzy_matches.sort(lambda a, b: cmp(a[1], b[1]))
    (best_value, confidence) = fuzzy_matches[-1]
    
    if confidence >= minimum_confidence:
        return best_value
    else:
        return None