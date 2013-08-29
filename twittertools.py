#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Whens My Transport Install Tool - gets a Twitter OAuth Key & Secret for your client
"""
from lib.twitterclient import make_oauth_key

# Change this to the instance you want to set up!
# FIXME Make this run off the command line rather than hardcoded
instance_name = 'whensmybus'
make_oauth_key(instance_name)