#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Run tests from our library
"""
import argparse
import cProfile
import pstats
import tempfile
import sys
import unittest

from whensmytransport import TESTING_TEST_LIVE_DATA, TESTING_TEST_LOCAL_DATA
from tests.generic_tests import unit_tests, local_tests, remote_tests, format_errors, geotag_errors
from tests.bus_tests import WhensMyBusTestCase, bus_errors, stop_errors, bus_successes
from tests.train_tests import WhensMyTubeTestCase, WhensMyDLRTestCase, tube_errors, station_errors, tube_successes


def run_tests():
    """
    Run a suite of tests for When's My Transport
    """
    #pylint: disable=W0603
    parser = argparse.ArgumentParser(description="Unit testing for When's My Transport?")
    parser.add_argument("test_case_name", action="store", default="", help="Classname of the class to test (e.g. WhensMyBus, WhensMyTube, WhensMyDLR)")
    parser.add_argument("--remote-apis", dest="remote_apis", action="store_true", default=False, help="Test Twitter & Yahoo APIs as well")
    parser.add_argument("--live-data", dest="test_level", action="store_const", const=TESTING_TEST_LIVE_DATA, default=TESTING_TEST_LOCAL_DATA,
                        help="Test with live TfL data (may fail unpredictably!)")
    parser.add_argument("--units-only", dest="units_only", action="store_true", default=False, help="Unit tests only (overrides above)")
    test_case_name = parser.parse_args().test_case_name

    if test_case_name == "WhensMyBus":
        failures = format_errors + geotag_errors + bus_errors + stop_errors
        successes = bus_successes
    elif test_case_name == "WhensMyTube" or test_case_name == "WhensMyDLR":
        failures = format_errors + geotag_errors + tube_errors + station_errors
        successes = tube_successes
    else:
        print "Error - %s is not a valid Test Case Name" % test_case_name
        sys.exit(1)

    if parser.parse_args().units_only:
        test_names = unit_tests
    elif parser.parse_args().remote_apis:
        test_names = unit_tests + local_tests + remote_tests + failures + successes
    else:
        test_names = unit_tests + local_tests + failures + successes

    testing_level = parser.parse_args().test_level
    if testing_level == TESTING_TEST_LIVE_DATA:
        print "Testing with live TfL data"
        failfast_level = 0
    else:
        print "Testing with local test data"
        failfast_level = 1

    suite = unittest.TestSuite()
    test_case = eval(test_case_name + 'TestCase')
    for test_name in test_names:
        suite.addTest(test_case(methodName='test_%s' % test_name, testing_level=testing_level))
    runner = unittest.TextTestRunner(verbosity=2, failfast=failfast_level, buffer=True)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    # run cProfile, return performance stats but only if the tests completed without failure
    profile = cProfile.Profile()
    test_succeeded = profile.runcall(run_tests)
    if test_succeeded:
        statsfile = tempfile.NamedTemporaryFile('w')
        profile.dump_stats(statsfile.name)
        stats = pstats.Stats(statsfile.name)
        stats.strip_dirs().sort_stats('time', 'cum').print_stats(10)
        statsfile.close()
