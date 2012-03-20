#!/usr/bin/env python
"""
Text parsing class for When's My Transport?
"""
import logging
import nltk

BUS_GRAMMAR = {
    'patterns': [
        (r"^[0-9]{5}$", 'BUS_STOP_NUMBER'),
        (r"^[A-Za-z]{0,2}[0-9]{1,3}$", 'ROUTE_NUMBER'),
        (r'^(from|From)$', 'FROM'),
        (r'^(to|To)(wards)?$', 'TO'),
        (r'^(please|thanks|thank|you)$', None),
        (r'.*', 'BUS_STOP_WORD'),
    ],

    'grammar': r"""
        ROUTES: {<ROUTE_NUMBER>+}
        BUS_STOP_PHRASE: {<BUS_STOP_WORD>+}
        BUS_STOP: {<BUS_STOP_PHRASE|BUS_STOP_NUMBER>}
        DESTINATION: {<TO><BUS_STOP>}
        ORIGIN: {<FROM>?<BUS_STOP>}
        ORIGIN2: {<FROM><BUS_STOP>}
        REQUEST: {^<ROUTES><ORIGIN>?<DESTINATION>?$}
                 {^<ROUTES><DESTINATION><ORIGIN2>$}
    """
}

TUBE_AND_DLR_GRAMMAR = {
    'patterns': [
        (r'^(from|From)$', 'FROM'),
        (r'^(to|To)(wards)?$', 'TO'),
        (r'^(line|Line)?$', 'LINE'),
        (r'^(please|thanks|thank|you)$', None),
        (r'^DLR$', 'DLR_LINE_NAME'),
        (r'^Docklands (Light Rail(way)?)?$', 'DLR_LINE_NAME'),
        (r'.*', 'TUBE_WORD'),
    ],

    'grammar': r"""
        TUBE_LINE_NAME: {<TUBE_WORD>+<LINE>}
        LINE_NAME: {<DLR_LINE_NAME|TUBE_LINE_NAME>}
        TUBE_STATION: {<TUBE_WORD>+}
        DESTINATION: {<TO><TUBE_STATION>}
        ORIGIN: {<FROM>?<TUBE_STATION>}
        ORIGIN2: {<FROM><TUBE_STATION>}
        REQUEST: {^<LINE_NAME><ORIGIN>?<DESTINATION>?$}
                 {^<LINE_NAME>?<DESTINATION><ORIGIN2>$}
    """
}

GRAMMARS = {
    'whensmybus': BUS_GRAMMAR,
    'whensmytube': TUBE_AND_DLR_GRAMMAR,
    'whensmydlr': TUBE_AND_DLR_GRAMMAR,
}


class WMTTextParser:
    """
    Parser for When's My Transport
    """
    def __init__(self, instance_name):
        self.tagger = nltk.RegexpTagger(GRAMMARS[instance_name]['patterns'])
        self.parser = nltk.RegexpParser(GRAMMARS[instance_name]['grammar'])

    def parse_message(self, text):
        """
        Parses the text and returns a tuple of (routes, origin, destination)
        """
        # Get tokens, tag them and remove any tagged with None
        logging.debug("Parsing message: '%s'", text)
        tokens = nltk.word_tokenize(text)
        tagged_tokens = self.tagger.tag(tokens)
        tagged_tokens = [(word, tag) for (word, tag) in tagged_tokens if tag]
        # Route numbers can only come at the beginning of a request in sequence, so anything else route number-like is
        # converted to the more generic PLACE_WORD type
        for i in range(1, len(tagged_tokens)):
            if tagged_tokens[i][1] == 'ROUTE' and tagged_tokens[i - 1][1] != 'ROUTE':
                tagged_tokens[i] = (tagged_tokens[i][0], 'PLACE_WORD')

        # Parse the tree. If we cannot parse a legitimate request then return nothing
        parsed_tokens = self.parser.parse(tagged_tokens)
        if not subtree_exists(parsed_tokens, 'REQUEST'):
            logging.debug("Message did not conform to message format, returning nothing")
            return (None, None, None)

        # Else extract the right tagged words from the parsed tree
        routes, origin, destination = (None, None, None)
        for subtree in parsed_tokens.subtrees():
            if subtree.node == 'ROUTES':
                routes = extract_words(subtree, ('ROUTE_NUMBER',)) or None
            if subtree.node == 'LINE_NAME':
                routes = [' '.join(extract_words(subtree, ('TUBE_WORD', 'DLR_LINE_NAME')))] or None
            elif subtree.node == 'ORIGIN':
                origin = ' '.join(extract_words(subtree, ('TUBE_WORD', 'BUS_STOP_WORD', 'BUS_STOP_NUMBER'))) or None
            elif subtree.node == 'DESTINATION':
                destination = ' '.join(extract_words(subtree, ('TUBE_WORD', 'BUS_STOP_WORD', 'BUS_STOP_NUMBER'))) or None

        logging.debug("Found routes %s from origin '%s' to destination '%s'", ', '.join(routes), origin, destination)
        return (routes, origin, destination)


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
