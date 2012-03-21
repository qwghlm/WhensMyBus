#!/usr/bin/env python
#pylint: disable=R0903,W0231,R0201
"""
Text parsing class for When's My Transport?
"""
import cPickle as pickle
import logging
import nltk
import os
from pprint import pprint

DB_PATH = os.path.normpath(os.path.dirname(os.path.abspath(__file__)) + '/../db/')


class WMTTextParser():
    """
    Base parser object
    """
    def __init__(self):
        self.tagger = None
        self.parser = None

    def parse_message(self, text):
        """
        Parses the text and returns a tuple of (routes, origin, destination)
        """
        # Get tokens, tag them and remove any tagged with None
        logging.debug("Parsing message: '%s'", text)
        if not text:
            logging.debug("Message is empty, returning nothing")
            return (None, None, None)
        tokens = nltk.word_tokenize(text)
        tagged_tokens = [(word, tag) for (word, tag) in self.tagger.tag(tokens) if tag]
        tagged_tokens = self.fix_unknown_tokens(tagged_tokens)

        # Parse the tree. If we cannot parse a legitimate request then return nothing
        parsed_tokens = self.parser.parse(tagged_tokens)
        if not subtree_exists(parsed_tokens, 'REQUEST'):
            logging.debug("Message did not conform to message format, returning nothing")
            return (None, None, None)

        # Else extract the right tagged words from the parsed tree
        routes, origin, destination = (None, None, None)
        for subtree in parsed_tokens.subtrees():
            if subtree.node == 'LINE_NAME':
                routes = [' '.join(extract_words(subtree, ('TUBE_LINE', 'DLR_LINE_NAME')))] or None
            elif subtree.node == 'ROUTES':
                routes = extract_words(subtree, ('ROUTE_NUMBER',)) or None
            elif subtree.node == 'ORIGIN':
                origin = ' '.join(extract_words(subtree, ('STATION_WORD', 'BUS_STOP_WORD', 'BUS_STOP_NUMBER'))) or None
            elif subtree.node == 'DESTINATION':
                destination = ' '.join(extract_words(subtree, ('STATION_WORD', 'BUS_STOP_WORD', 'BUS_STOP_NUMBER'))) or None

        logging.debug("Found routes %s from origin '%s' to destination '%s'", routes, origin, destination)
        return (routes, origin, destination)

    def fix_unknown_tokens(self, tagged_tokens):
        """
        Fix tagged tokens that are tagged "UKNOWN"
        """
        return tagged_tokens


class WMTBusParser(WMTTextParser):
    """
    Parser for bus requests
    """
    def __init__(self):
        tagging_regexes = [
            (r"^[0-9]{5}$", 'BUS_STOP_NUMBER'),
            (r"^[A-Za-z]{0,2}[0-9]{1,3}$", 'ROUTE_NUMBER'),
            (r'^from$', 'FROM'),
            (r'^to(wards)?$', 'TO'),
            (r'^(please|thanks|thank|you)$', None),
            (r'.*', 'UNKNOWN'),
        ]
        grammar = r"""
            ROUTES: {<ROUTE_NUMBER>+}
            BUS_STOP_PHRASE: {<BUS_STOP_WORD>+}
            BUS_STOP: {<BUS_STOP_PHRASE|BUS_STOP_NUMBER>}
            DESTINATION: {<TO><BUS_STOP>}
            ORIGIN: {<FROM>?<BUS_STOP>}
            REQUEST: {^<ROUTES><ORIGIN>?<DESTINATION>?$}
                     {^<ROUTES><DESTINATION><ORIGIN>$}
        """
        self.tagger = nltk.RegexpTagger(tagging_regexes)
        self.parser = nltk.RegexpParser(grammar)

    def fix_unknown_tokens(self, tagged_tokens):
        """
        Fix tagged tokens that are tagged "UKNOWN"
        """
        # Any tokens that are unknown or a bus number, after the last bus number, become BUS_STOP_WORDs
        for i in range(last_occurrence_of_tag(tagged_tokens, 'ROUTE_NUMBER') + 1, len(tagged_tokens)):
            if tagged_tokens[i][1] in ('UNKNOWN', 'ROUTE_NUMBER'):
                tagged_tokens[i] = (tagged_tokens[i][0], 'BUS_STOP_WORD')
        return tagged_tokens


class WMTTrainParser(WMTTextParser):
    """
    Parser for train requests
    """
    def __init__(self):
        grammar = r"""
            TUBE_LINE_NAME: {<TUBE_LINE>+<LINE>?}
            LINE_NAME: {<DLR_LINE_NAME|TUBE_LINE_NAME>}
            STATION: {<STATION_WORD>+}
            DESTINATION: {<TO><STATION>}
            ORIGIN: {<FROM>?<STATION>}
            REQUEST: {^<LINE_NAME>?<ORIGIN>?<DESTINATION>?$}
                     {^<LINE_NAME>?<DESTINATION><ORIGIN>$}
        """
        self.tagger = pickle.load(open(DB_PATH + '/whensmytrain.tagger.obj'))
        self.parser = nltk.RegexpParser(grammar)

    def fix_unknown_tokens(self, tagged_tokens):
        """
        Fix tagged tokens that are tagged "UKNOWN"
        """
        for i in range(last_occurrence_of_tag(tagged_tokens, 'TUBE_LINE') + 1, len(tagged_tokens)):
            if tagged_tokens[i][1] in ('UNKNOWN', 'TUBE_LINE'):
                tagged_tokens[i] = (tagged_tokens[i][0], 'STATION_WORD')
        return tagged_tokens


def first_occurrence_of_tag(sequence, tag_name_or_names):
    """
    Returns the position of the first with tag_name in the sequence
    """
    for i in range(0, len(sequence)):
        if isinstance(tag_name_or_names, tuple) and sequence[i][1] in tag_name_or_names:
            return i
        elif isinstance(tag_name_or_names, str) and sequence[i][1] == tag_name_or_names:
            return i
    return -1


def last_occurrence_of_tag(sequence, tag_name):
    """
    Returns the position of the last on in the chain of tags with tag_name in the sequence
    Assums that the first element(s) of the sequence are tagged so (else it will return -1)
    """
    for i in range(0, len(sequence)):
        if sequence[i][1] != tag_name:
            return i - 1
    return len(sequence)


def subtree_exists(tree, subtree_node_name):
    """
    Checks to see if a subtree or node exists within the tree
    """
    try:
        tree.node
    except AttributeError:
        return tree[1] == subtree_node_name
    else:
        return tree.node == subtree_node_name or reduce(lambda a, b: a or b, [subtree_exists(child, subtree_node_name) for child in tree])


def extract_words(tree, word_types_to_return):
    """
    Extracts words of certain types from a parsed tree. Types to return are expressed as a list or tuple
    """
    try:
        tree.node
    except AttributeError:
        if tree[1] in word_types_to_return:
            return [tree[0]]
        else:
            return []
    else:
        return reduce(lambda a, b: a + b, [extract_words(child, word_types_to_return) for child in tree])
