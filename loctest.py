from lib.locations import WMTLocations
from pprint import pprint

loc = WMTLocations('whensmytube')

print loc.describe_route("Victoria", "Mile End")
print loc.describe_route("Stockwell", "Euston")
print loc.describe_route("Stockwell", "Euston", line="Northern")
print loc.describe_route("Stockwell", "Euston", line="Northern", via="Bank")
