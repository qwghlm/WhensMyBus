#!/usr/bin/env python
"""
String utilities, including fuzzy string matching
"""
import difflib
import re


def capwords(phrase):
    """
    Capitalize each word in a string. A word is defined as anything with a space separating it from the next word
    """
    lowercase_only = ('via',)
    uppercase_only = ('CX',)
    capitalized = [word.capitalize() for word in phrase.split(' ')]
    capitalized = [word.lower() in lowercase_only and word.lower() or word for word in capitalized]
    capitalized = [word.upper() in uppercase_only and word.upper() or word for word in capitalized]
    return ' '.join(capitalized)


def cleanup_name_from_undesirables(name, undesirables):
    """
    Clean out every regular expression in the iterable undesirables from the name supplied, and capitalize
    """
    for undesirable in undesirables:
        name = re.sub(undesirable, '', name, flags=re.I)
    name = re.sub(r' +', ' ', name.strip())
    return capwords(name)


def get_name_similarity(origin, stop):
    """
    Return a score between 0 and 100 of the strings' similarity, based on difflib's string similarity algorithm returning an integer
    between 0 (no match) and 100 (perfect). 70 or more seems to be a confident enough match
    """
    # Based on https://github.com/seatgeek/fuzzywuzzy/blob/master/fuzzywuzzy/fuzz.py
    return int(100 * difflib.SequenceMatcher(None, origin, stop).ratio())


def get_best_fuzzy_match(search_term, possible_items, minimum_confidence=70):
    """
    Get the best matching item in a list of possible_values that matches search_term

    Search terms are strings. Items must have a get_similarity() method, or be strings
    """
    # Get tuples of matches, each a (value, confidence) pair : confidence is between 0 and 100 and reflects
    # how confident we are that that value (or its property) matches the term we have asked for
    if not possible_items:
        return None

    if hasattr(possible_items[0], "get_similarity"):
        fuzzy_matches = [(item, item.get_similarity(search_term)) for item in possible_items]
    else:
        fuzzy_matches = [(item, get_name_similarity(search_term, item)) for item in possible_items]

    # Sort in order of confidence (with length as a tiebreaker)
    fuzzy_matches.sort(lambda a, b: cmp(a[1], b[1]) or cmp(len(b[0]), len(a[0])))
    (best_value, confidence) = fuzzy_matches[-1]
    if confidence >= minimum_confidence:
        return best_value
    else:
        return None
