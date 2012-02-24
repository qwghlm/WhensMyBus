#!/usr/bin/env python
#pylint: disable=W0107
"""
Utilities for WhensMyTransport
"""
from pprint import pprint

# List utils

def unique_values(seq):
    """
    Return unique values of sequence seq, according to ID function idfun. From http://www.peterbe.com/plog/uniqifiers-benchmark
    and modified. Values in seq must be hashable for this to work
    """
    seen = {} 
    result = [] 
    for item in seq: 
        if item in seen:
            continue 
        seen[item] = 1 
        result.append(item) 
    return result

