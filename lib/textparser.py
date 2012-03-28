#!/usr/bin/env python
#pylint: disable=R0903,W0231,R0201
"""
Text parsing class for When's My Transport?
"""
import cPickle as pickle
import logging
import nltk
import os

from lib.stringutils import capwords

DB_PATH = os.path.normpath(os.path.dirname(os.path.abspath(__file__)) + '/../db/')


class WMTTextParser():
    """
    Base parser object
    """
    def __init__(self):
        # Parsing split into two roles: tagger (that identifies words and classifies them as a part of speech) and parser (that takes
        # those tagged words and works out a parse tree for them). This gets overridden
        self.tagger = None
        self.parser = None

    def parse_message(self, text):
        """
        Parses the text and returns a tuple of (routes, origin, destination). routes is a list of strings; origin and destination strings
        """
        # Get tokens, tag them and remove any tagged with None
        logging.debug("Parsing message: '%s'", text)
        if not text:
            logging.debug("Message is empty, returning nothing")
            return (None, None, None)
        tokenizer = nltk.tokenize.regexp.WhitespaceTokenizer()
        tokens = tokenizer.tokenize(text.lower())
        tagged_tokens = [(word, tag) for (word, tag) in self.tagger.tag(tokens) if tag]

        # Some tags may be unknown type so we run a method on them to resolve such unknowns
        tagged_tokens = self.fix_unknown_tokens(tagged_tokens)

        # Parse the tree. If we cannot parse a legitimate request then return nothing
        parsed_tokens = self.parser.parse(tagged_tokens)
        if not subtree_exists(parsed_tokens, 'REQUEST'):
            logging.debug("Message did not conform to message format, returning nothing")
            return (None, None, None)

        # Else extract the right tagged words from the parsed tree, applying capitalisation appropriately
        routes, origin, destination = (None, None, None)
        for subtree in parsed_tokens.subtrees():
            if subtree.node == 'LINE_NAME':
                routes = extract_words(subtree, ('TUBE_LINE_WORD', 'DLR_LINE_NAME', 'AND', 'CITY'))
                routes = ' '.join(routes) or None
                if routes == 'dlr':
                    routes = [routes.upper()]
                elif routes:
                    routes = [capwords(routes)]
            elif subtree.node == 'BUS_ROUTES':
                routes = extract_words(subtree, ('ROUTE_NUMBER',))
                routes = routes and [route.upper() for route in routes] or None
            elif subtree.node == 'ORIGIN':
                origin = extract_words(subtree, ('STATION_WORD', 'BUS_STOP_WORD', 'BUS_STOP_NUMBER'))
            elif subtree.node == 'DESTINATION':
                destination = extract_words(subtree, ('STATION_WORD', 'BUS_STOP_WORD', 'BUS_STOP_NUMBER'))

        origin = origin and capwords(' '.join(origin)) or None
        destination = destination and capwords(' '.join(destination)) or None
        logging.debug("Found routes %s from origin '%s' to destination '%s'", routes, origin, destination)
        return (routes, origin, destination)

    def fix_unknown_tokens(self, tagged_tokens):
        """
        Fix tagged tokens that are tagged "UNKNOWN"
        """
        # Simplest version of this is to do nothing
        return tagged_tokens


class WMTBusParser(WMTTextParser):
    """
    Parser for bus requests
    """
    def __init__(self):
        # Regexes for tagging parts of speech. Platitudes are ignored, and any word not matching is initially classified as Unknown
        tagging_regexes = [
            (r"^[0-9]{5}$", 'BUS_STOP_NUMBER'),
            (r"^[A-Za-z]{0,2}[0-9]{1,3}$", 'ROUTE_NUMBER'),
            (r'^from$', 'FROM'),
            (r'^to(wards)?$', 'TO'),
            (r'^(please|thanks|thank|you)$', None),
            (r'.*', 'UNKNOWN'),
        ]
        self.tagger = nltk.RegexpTagger(tagging_regexes)

        # Grammar for user requests - a route must be specified, followed by optional origin then optional destination
        # Alternatively, we can have destination then origin but in which case the destination must be specified with a "to" prefix
        grammar = r"""
            BUS_ROUTES: {<ROUTE_NUMBER>+}
            BUS_STOP_PHRASE: {<BUS_STOP_WORD>+}
            BUS_STOP: {<BUS_STOP_PHRASE|BUS_STOP_NUMBER>}
            DESTINATION: {<TO><BUS_STOP>}
            ORIGIN: {<FROM>?<BUS_STOP>}
            REQUEST: {^<BUS_ROUTES><ORIGIN>?<DESTINATION>?$}
                     {^<BUS_ROUTES><DESTINATION><ORIGIN>$}
        """
        self.parser = nltk.RegexpParser(grammar)

    def fix_unknown_tokens(self, tagged_tokens):
        """
        Fix tagged tokens that are tagged "UNKNOWN"
        """
        # Any tokens that are unknown or a bus number, after the chain of route numbers at the start, must be Bus Stop words
        for i in range(last_occurence_of_tag_chain(tagged_tokens, 'ROUTE_NUMBER') + 1, len(tagged_tokens)):
            if tagged_tokens[i][1] in ('UNKNOWN', 'ROUTE_NUMBER'):
                tagged_tokens[i] = (tagged_tokens[i][0], 'BUS_STOP_WORD')
        return tagged_tokens


class WMTTrainParser(WMTTextParser):
    """
    Parser for train requests
    """
    def __init__(self):
        # The tagger for WMT is so expensive to create, we prebuild it and load via pickle.
        # Thus tagging regexes for trains are created in dataparser.py
        self.tagger = pickle.load(open(DB_PATH + '/whensmytrain.tagger.obj'))

        # Grammar for train requests consist of a line name, followed by optional origin then optional destination
        # Alternatively, we can have destination then origin but in which case the destination must be specified with a "to" prefix
        grammar = r"""
            TUBE_LINE_NAME: {<TUBE_LINE_WORD><AND><CITY><LINE>?}
                            {<TUBE_LINE_WORD><LINE>?}
            LINE_NAME: {<DLR_LINE_NAME|TUBE_LINE_NAME>}
            STATION: {<STATION_WORD|CITY|AND>+}
            DESTINATION: {<TO><STATION>}
            ORIGIN: {<FROM>?<STATION>}
            REQUEST: {^<LINE_NAME>?<ORIGIN>?<DESTINATION>?$}
                     {^<LINE_NAME>?<DESTINATION><ORIGIN>$}
        """
        self.parser = nltk.RegexpParser(grammar)

    def fix_unknown_tokens(self, tagged_tokens):
        """
        Fix tagged tokens that are tagged "UNKNOWN"
        """
        # Any Unknown words before the occurrence of the word "Line" must be a Tube line word
        for i in range(0, first_occurrence_of_tag(tagged_tokens, 'LINE')):
            if tagged_tokens[i][1] in ('UNKNOWN',):
                tagged_tokens[i] = (tagged_tokens[i][0], 'TUBE_LINE_WORD')

        # Any Unknown words after the chain of Tube Line words at the start must be a Station word
        for i in range(last_occurence_of_tag_chain(tagged_tokens, 'TUBE_LINE_WORD') + 1, len(tagged_tokens)):
            if tagged_tokens[i][1] in ('UNKNOWN', 'TUBE_LINE_WORD'):
                tagged_tokens[i] = (tagged_tokens[i][0], 'STATION_WORD')
        return tagged_tokens


def first_occurrence_of_tag(sequence, tag_type_or_types):
    """
    Returns the position of the first tag with type tag_type_or_types in the sequence

    tag_type_or_types can be a string (exact match) or a list of strings (exact match any in the list)
    """
    for i in range(0, len(sequence)):
        if isinstance(tag_type_or_types, tuple) and sequence[i][1] in tag_type_or_types:
            return i
        elif isinstance(tag_type_or_types, str) and sequence[i][1] == tag_type_or_types:
            return i
    return -1


def last_occurence_of_tag_chain(sequence, tag_type):
    """
    Takes a sequence of tags. Assuming the first N tags of the sequence are all of the type tag_type, it will return
    the index of the last such tag in that chain, i.e. N-1

    If the first element of the sequence is not of type tag_type, it will return -1
    """
    for i in range(0, len(sequence)):
        if sequence[i][1] != tag_type:
            return i - 1
    return len(sequence)


def subtree_exists(tree, subtree_node_name):
    """
    Checks to see if a subtree or node exists within a parsed tree
    """
    try:
        tree.node
    except AttributeError:
        return tree[1] == subtree_node_name
    else:
        return tree.node == subtree_node_name or reduce(lambda a, b: a or b, [subtree_exists(child, subtree_node_name) for child in tree])


def extract_words(tree, word_types_to_return):
    """
    Extracts words of certain types from a parsed tree. Types to return is list or tuple of types
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
