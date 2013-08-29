#!/usr/bin/env python
# -*- coding: utf-8 -*-
#pylint: disable=R0913
"""
Twitter handling for When's My Transport
"""
import sys
import ConfigParser
import logging
import time
from pprint import pprint

# Tweepy is a Twitter API library available from https://github.com/tweepy/tweepy
import tweepy
from lib.settings import WMTSettings


class WMTTwitterClient():
    """
    A Twitter Client that fetches Tweets and manages follows for When's My Transport
    """
    def __init__(self, instance_name, consumer_key, consumer_secret, access_token, access_token_secret, testing=False):
        logging.debug("Authenticating with Twitter")
        auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
        auth.set_access_token(access_token, access_token_secret)
        self.api = tweepy.API(auth)
        self.settings = WMTSettings(instance_name)
        self.testing = testing
        if not self.testing:
            self.report_twitter_limit_status()

    def check_followers(self):
        """
        Check my followers. If any of them are not following me, try to follow them back
        """
        # Don't bother if we have checked in the last hour
        last_follower_check = self.settings.get_setting("last_follower_check") or 0
        if time.time() - last_follower_check < 3600:
            return
        logging.info("Checking to see if I have any new followers...")
        self.settings.update_setting("last_follower_check", time.time())

        # Get IDs of our friends (people we already follow), and our followers
        followers_ids = self.api.followers_ids()
        friends_ids = self.api.friends_ids()

        # Annoyingly, different versions of Tweepy implement the above; older versions return followers_ids() as a tuple and the list of
        # followers IDs is the first element of that tuple. Newer versions return just the followers' IDs (which is much more sensible)
        if isinstance(followers_ids, tuple):
            followers_ids = followers_ids[0]
            friends_ids = friends_ids[0]

        # Some users are protected and have been requested but not accepted - we need not continually ping them
        protected_users_to_ignore = self.settings.get_setting("protected_users_to_ignore") or []

        # Work out the difference between the two, and also ignore protected users we have already requested
        # Twitter gives us these in reverse order, so we pick the final ten (i.e the earliest to follow)
        # reverse these to give them in normal order, and follow each one back!
        twitter_ids_to_follow = [f for f in followers_ids if f not in friends_ids and f not in protected_users_to_ignore][-5:]
        for twitter_id in twitter_ids_to_follow[::-1]:
            try:
                person = self.api.create_friendship(twitter_id)
                logging.info("Following user %s", person.screen_name)
            except tweepy.error.TweepError:
                protected_users_to_ignore.append(twitter_id)
                logging.info("Error following user %s, most likely the account is protected", twitter_id)
                continue

        self.settings.update_setting("protected_users_to_ignore", protected_users_to_ignore)
        self.report_twitter_limit_status()

    def fetch_tweets(self):
        """
        Fetch Tweets that are replies & direct messages to us and return as a list
        """
        # Get the IDs of the Tweets and Direct Message we last answered
        last_answered_tweet = self.settings.get_setting('last_answered_tweet') or 1
        last_answered_direct_message = self.settings.get_setting('last_answered_direct_message') or 1

        # Fetch those Tweets and DMs. This is most likely to fail if OAuth is not correctly set up
        try:
            tweets = self.api.mentions_timeline(since_id=last_answered_tweet)
            direct_messages = self.api.direct_messages(since_id=last_answered_direct_message)

        except tweepy.error.TweepError, e:
            logging.error("Error: OAuth connection to Twitter failed, probably due to an invalid token")
            raise RuntimeError("Error: OAuth connection to Twitter failed, probably due to an invalid token")

        # Convert iterators to lists & reverse
        tweets = list(tweets)[::-1]
        direct_messages = list(direct_messages)[::-1]

        # No need to bother if no replies
        if not tweets and not direct_messages:
            logging.info("No new Tweets, exiting...")
        else:
            logging.info("%s replies and %s direct messages received!", len(tweets), len(direct_messages))

        return direct_messages + tweets

    def report_twitter_limit_status(self):
        """
        Log what our Twitter API hit count & limit is
        """
        try:
            limit_status = self.api.rate_limit_status()
        except tweepy.error.TweepError as e:
            default_error = "Unknown Tweepy error"
            error = e.message and e.message[0].get('message', default_error) or default_error
            logging.info("Error checking Twitter API: %s" % error)
            sys.exit(1)
        resources = limit_status.get('resources', {})

        # Check remaining resources
        application = resources.get('application', {}).get('/application/rate_limit_status', {})
        if application['remaining'] == 0:
            logging.info("No more API calls left until %s GMT, exiting application" % format_unix_time(application['reset']))
            sys.exit(1)
        logging.info("This application has %s out of %s API accesses remaining until %s GMT",
            application['remaining'], application['limit'], format_unix_time(application['reset']))

        #
        # TODO: Set flags so we don't bother checking exhausted endpoints
        #
        followers = resources.get('followers', {}).get('/followers/ids', {})
        logging.info("I have %s out of %s follow checks remaining until %s GMT",
            followers['remaining'], followers['limit'], format_unix_time(followers['reset']))

        direct_messages = resources.get('direct_messages', {}).get('/direct_messages', {})
        logging.info("This application has %s out of %s direct message checks remaining until %s GMT",
            direct_messages['remaining'], direct_messages['limit'], format_unix_time(direct_messages['reset']))

        replies = resources.get('statuses', {}).get('/statuses/home_timeline', {})
        logging.info("This application has %s out of %s @ reply checks remaining until %s GMT",
            replies['remaining'], replies['limit'], format_unix_time(replies['reset']))

    def send_reply_back(self, reply, username, send_direct_message, in_reply_to_status_id=None):
        """
        Send back a reply to username; this might be a DM or might be a public reply
        """
        messages = split_message_for_twitter(reply, username)
        # Send the reply/replies we have generated to the user
        for message in messages:
            try:
                if send_direct_message:
                    logging.info("Sending direct message to %s: '%s'", username, message)
                    if in_reply_to_status_id:
                        self.settings.update_setting('last_answered_direct_message', in_reply_to_status_id)
                    if not self.testing:
                        self.api.send_direct_message(user=username, text=message)
                else:
                    status = "@%s %s" % (username, message)
                    if in_reply_to_status_id:
                        self.settings.update_setting('last_answered_tweet', in_reply_to_status_id)
                    logging.info("Making status update: '%s'", status)
                    if not self.testing:
                        self.api.update_status(status=status, in_reply_to_status_id=in_reply_to_status_id)

            # This catches any errors, most typically if we send multiple Tweets to the same person with the same content
            # - typically if the use sends the same bad request again and again, we will reply with same error
            # In which case, not much we can do about it, so we just ignore
            except tweepy.error.TweepError:
                continue


def format_unix_time(timestamp):
    return time.asctime(time.gmtime(float(timestamp)))

def split_message_for_twitter(message, username):
    """
    Takes a message and returns a list of messages, split appropriately to fit on Twitter
    If message is short enough then we just return a list with one element into 
    """
    # 136 allows us breathing room for a letter D and spaces for a direct message & three dots at the end, so split this kind of reply
    max_message_length = 136 - len(username)
    if len(message) > max_message_length:
        clauses = message.split(';')
        messages = [u""]
        for clause in clauses:
            if len(clause) > max_message_length:
                continue
            if len(messages[-1]) + len(clause) < max_message_length:
                messages[-1] = messages[-1] + clause + ';'
            else:
                messages[-1] = messages[-1].strip()[:-1] + u"…"
                messages.append(u"…" + clause.lstrip())
    else:
        messages = [message]
    return messages


def is_direct_message(tweet):
    """
    Returns True if a Tweet object is that of Tweepy's Direct Message, False if any other kind
    """
    return isinstance(tweet, tweepy.models.DirectMessage)


def make_oauth_key(instance_name):
    """
    Adapted from
    http://talkfast.org/2010/05/31/twitter-from-the-command-line-in-python-using-oauth

    Helper script to produce an OAuth user key & secret for a Twitter app, given the consumer key & secret
    Log in as the user you want to authorise, visit the URL this script produces, then type in the PIN
    Twitter's OAuth servers provide you to get a key/secret pair
    """
    config = ConfigParser.SafeConfigParser()
    config.read('config.cfg')

    consumer_key = config.get(instance_name, 'consumer_key')
    consumer_secret = config.get(instance_name, 'consumer_secret')

    if not consumer_key or not consumer_secret:
        print "Could not find consumer key or secret, exiting"
        sys.exit(0)

    auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
    auth_url = auth.get_authorization_url()
    print 'Please authorize: ' + auth_url
    verifier = raw_input('PIN: ').strip()
    auth.get_access_token(verifier)
    print "key : %s" % auth.access_token.key
    print "secret : %s" % auth.access_token.secret

if __name__ == "__main__":
    make_oauth_key('whensmybus')
