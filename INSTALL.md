#When's My Bus/Tube/DLR
#Installation instructions

##Requirements

Python 2.6 or greater is required to run the bot. Python 2.7 required for unit testing. Not yet tested with Python 3 and will almost certainly not work

Before starting, the bot needs the following supporting libraries:

 * nltk (v2.0): http://nltk.github.com/install.html
 * pygraph (v1.8.2): http://code.google.com/p/python-graph/
 * tweepy (v2.1): http://code.google.com/p/tweepy/

##Installation


Make sure you have installed the above libraries first. Assuming you have `easy_install` and `pip` already installed:

	$ sudo pip install -U pyyaml nltk
	$ sudo easy_install python-graph-core
    $ sudo pip install tweepy

Create a Twitter account for your application by visiting https://dev.twitter.com/ and signing up an account for your bot if you have not already.

Go to the [My Applications](https://dev.twitter.com/apps) tab and click create a new Application. Fill in the details: Name, Description and Website should suffice. You don't need to fill in a Callback URL. Agree to the terms and create the application.

Once your App is set up, create an access token for your own account to get an access token and access token secret.

Download the code & data for WhensMyBus (despite the name this contains code for all three bots) from Github into a working directory:

    $ git clone git://github.com/qwghlm/WhensMyBus.git
    $ cd WhensMyBus

All the geodata is there, you just need to opy config.cfg.sample to config.cfg and edit it:

	$ cp config.cfg.sample config.cfg
	$ nano config.cfg

Go the relevant section (`[whensmybus]`, `[whensmytube]` or `[whensmydlr]`) that you want to activate. Fill in the Twitter username, consumer key & secret, user key & secret within this section and save

You can also optionally change the `debug_level` to `DEBUG` (more messages) and `silent_mode` to 1 (in which case it will read Tweets and create mock replies, but not post them to Twitter)

You now have a working bot! To test it, try the following test depending on which bots you activated

    $ python run_tests.py WhensMyBus --remote-apis
    $ python run_tests.py WhensMyTube --remote-apis
    $ python run_tests.py WhensMyDLR --remote-apis

All tests should clear if Twitter OAuth is correctly set up; if you don't care about remote connection, try running without the `--remote-apis` flags

To get started, on the command line run whichever command you fancy:

    $ ./whensmybus.py
    $ ./whensmytrain.py whensmytube
    $ ./whensmytrain.py whensmydlr

To update regularly, set a cronjob to call your script every minute or so

## Other tools

If you ever want to update the CSV file(s) in `sourcedata/` and update the database, after updating the CSV run:

	$ python datatools.py

If you ever want to add the app to more Twitter accounts, and need to generate more access tokens, run:

	$ python twittertools.py

Although only the Google geocoder is used, there is Bing's as well in `lib/geo.py`