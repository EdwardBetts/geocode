from flask import current_app
from . import headers
import os
import json
import requests

OVERPASS_URL = "https://lz4.overpass-api.de"


def run_query(oql):
    return requests.post(
        OVERPASS_URL + "/api/interpreter", data=oql.encode("utf-8"), headers=headers
    )


def is_in_lat_lon(lat, lon):
    oql = f"""
[out:json][timeout:25];
is_in({lat},{lon})->.a;
(way(pivot.a); rel(pivot.a););
out bb tags qt;"""

    return run_query(oql)


def get_osm_elements(lat, lon):
    filename = f"cache/{lat}_{lon}.json"
    use_cache = current_app.config["USE_CACHE"]

    if use_cache and os.path.exists(filename):
        return json.load(open(filename))["elements"]

    r = is_in_lat_lon(lat, lon)
    if use_cache:
        open(filename, "wb").write(r.content)
    return r.json()["elements"]
