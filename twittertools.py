#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Whens My Transport Install Tool - gets a Twitter OAuth Key & Secret for your client
"""
from lib.twitterclient import make_oauth_key

# Change this to the instance you want to set up!
instance_name = 'whensmybus'
make_oauth_key(instance_name)