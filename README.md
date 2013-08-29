#When's My Bus & When's My Tube

A suite of three Twitter bots that tell you what time London's buses, Tube and DLR are arriving at a stop or station near you. It currently runs as three bots:

* [@whensmybus](http://twitter.com/#!/whensmybus)
* [@whensmytube](http://twitter.com/#!/whensmytube)
* [@whensmydlr](http://twitter.com/#!/whensmydlr)

Tweeting is easy:

> @whensmybus 135

Will check the Tweet for its geotag and work out the next bus

> @whensmybus 135 from Limehouse station

Will check the Tweet for the location and work out the next bus

> @whensmytube District Line from Tower Hill

Will check the Tweet for the station name and work out the next Tube

> @whensmytube DLR from Shadwell

Will check the Tweet for the station name and work out the next DLR

Thanks to some clever natural language processing, lots of variations on grammar and special directions are possible, including specifyin multiple buses and destinations, such as:

> @whensmybus 135 15 D3 from Limehouse<br/>
> @whensmybus 135 from Limehouse to Old Street<br/>
> @whensmytube Central Line to Bank from Bethnal Green<br/>

This also works with Direct Messages so you can message privately, although Direct Messages do not support geotagging

More info from a user perspective about how to use the bot is available here:

* http://whensmybus.tumblr.com/about/
* http://whensmytube.tumblr.com/about/
* http://whensmydlr.tumblr.com/about/

#Source Code

Available from https://github.com/qwghlm/WhensMyBus

#Requirements

Requires: Python 2.6 or greater to run the bot. Python 2.7 required for unit testing. Not yet tested with Python 3

See `INSTALL.md` for installation instructions and details of dependencies

#Credits & Thanks

- My thanks go to [Adrian Short](http://adrianshort.co.uk/2011/09/08/open-data-for-everyday-life/) for inspiring me to write this
- And Chris Veness for his [geographic co-ordinate translation scripts](http://www.movable-type.co.uk/scripts/latlong-gridref.html)