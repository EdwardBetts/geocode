#!/usr/bin/python3

from flask import Flask, render_template, request, jsonify, redirect, url_for
import requests
import os
import json
import urllib.parse
import random
import simplejson
import psycopg2
from geopy.distance import distance

# select gid, code, name from scotland where st_contains(geom, ST_Transform(ST_SetSRID(ST_MakePoint(-4.177, 55.7644), 4326), 27700));

commons_cat_start = "https://commons.wikimedia.org/wiki/Category:"
use_cache = False

headers = {
    "User-Agent": "UK gecode/0.1 (edward@4angle.com)",
}

OVERPASS_URL = "https://lz4.overpass-api.de"
wikidata_query_api_url = "https://query.wikidata.org/bigdata/namespace/wdq/sparql"
wd_entity = "http://www.wikidata.org/entity/Q"
city_of_london_qid = "Q23311"

samples = [
    (50.8326, -0.2689, "Adur"),
    (52.4914, -0.69645, "Corby"),
    (50.893, -4.265, "Newton St Petrock"),
    (51.779, 0.128, "Harlow"),
    (52.387, 0.294, "Ely"),
    (50.9, -1.6, "Minstead"),
    (52.43, -1.11, "South Kilworth"),
    (53.117, -0.202, "Tattershall Thorpe"),
    (53.351, -2.701, "Halton"),
    (52.421, -0.651, "Warkton"),
    (51.51, -1.547, "Lambourn"),
    (52.62, -1.884, "Shenstone"),
    (53.309, -1.539, "Sheffield"),
    (53.322, 0.032, "Haugham"),
    (51.05, -2.598, "Babcary"),
    (51.158, -1.906, "Berwick St James"),
    (51.867, -1.204, "Weston-on-the-Green"),
    (51.034, -2.005, "Ebbesbourne Wake"),
    (51.07, -0.718, "Fernhurst"),
    (53.059, -0.144, "Wildmore"),
    (51.473, 0.221, "Dartford"),
    (51.059, 0.05, "Danehill"),
    (52.253, -0.122, "Papworth Everard"),
    (53.498, -0.415, "West Lindsey"),
    (53.392, -0.022, "Brackenborough with Little Grimsby"),
    (53.463, -0.027, "Fulstow"),
    (52.766, 0.31, "Terrington St Clement"),
    (53.1540, -1.8034, "Hartington Town Quarter"),
    (51.8532, -0.8829, "Fleet Marston"),
    (51.4785, -0.354, "London Borough of Hounslow"),
    (51.9687, -0.0327, "Buckland, Hertfordshire"),
    (51.0804, -2.3263, "Zeals"),
    (55.7644, -4.1770, "East Kilbride"),
    (51.4520, -2.6210, "Bristol"),
]

class QueryError(Exception):
    def __init__(self, query, r):
        self.query = query
        self.r = r


app = Flask(__name__)
app.debug = True


def get_random_lat_lon():
    ''' Select random lat/lon within the UK '''
    south, east = 50.8520, 0.3536
    north, west = 53.7984, -2.7296

    mul = 10000
    lat = random.randrange(int(south * mul), int(north * mul)) / mul
    lon = random.randrange(int(west * mul), int(east * mul)) / mul

    return lat, lon


@app.route("/random")
def random_location():
    lat, lon = get_random_lat_lon()

    elements = get_osm_elements(lat, lon)
    result = do_lookup(elements, lat, lon)

    return render_template("random.html", lat=lat, lon=lon, result=result, elements=elements)


@app.route("/wikidata_tag")
def wikidata_tag():
    lat = float(request.args.get("lat"))
    lon = float(request.args.get("lon"))

    scotland_code = get_scotland_code(lat, lon)

    if scotland_code:
        rows = lookup_scottish_parish_in_wikidata(scotland_code)
        hit = commons_from_rows(rows)
        elements = []
        result = build_dict(hit, lat, lon)
    else:
        elements = get_osm_elements(lat, lon)
        result = do_lookup(elements, lat, lon)

    return render_template("wikidata_tag.html", lat=lat, lon=lon, result=result, elements=elements)


@app.route("/detail")
def detail_page():
    try:
        lat, lon = [float(request.args.get(param)) for param in ("lat", "lon")]
    except TypeError:
        return redirect(url_for("index"))
    reply = lat_lon_to_wikidata(lat, lon)
    return render_template("random.html", lat=lat, lon=lon, **reply)


def bounding_box_area(element):
    bbox = element["bounds"]

    x = distance((bbox["maxlat"], bbox["minlon"]), (bbox["maxlat"], bbox["maxlon"]))
    y = distance((bbox["minlat"], bbox["maxlon"]), (bbox["maxlat"], bbox["minlon"]))

    return x.km * y.km


def wd_to_qid(wd):
    # expecting {"type": "url", "value": "https://www.wikidata.org/wiki/Q30"}
    if wd["type"] == "uri":
        return wd_uri_to_qid(wd["value"])


def wd_uri_to_qid(value):
    assert value.startswith(wd_entity)
    return value[len(wd_entity) - 1:]


def build_dict(hit, lat, lon):
    coords = {"lat": lat, "lon": lon}
    if hit is None:
        return dict(commons_cat=None, missing=True, coords=coords)
    commons_cat = hit["commons_cat"]
    url = commons_cat_start + urllib.parse.quote(commons_cat.replace(" ", "_"))
    return dict(commons_cat={"title": commons_cat, "url": url},
                coords=coords,
                admin_level=hit.get("admin_level"),
                wikidata=hit["wikidata"])


def do_lookup(elements, lat, lon):
    try:
        hit = osm_lookup(elements, lat, lon)
    except QueryError as e:
        return {
            "query": e.query,
            "error": e.r.text,
            "query_url": "https://query.wikidata.org/#" + e.query,
        }

    return build_dict(hit, lat, lon)


def get_scotland_code(lat, lon):
    conn = psycopg2.connect(dbname="geocode", user="geocode", password="ooK3ohgh", host="localhost")
    cur = conn.cursor()

    point = f"ST_Transform(ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326), 27700)"
    cur.execute(f"select code, name from scotland where st_contains(geom, {point});")
    row = cur.fetchone()

    # expand search, disabled for now 2020-04-20
    if not row:
        cur.execute(f"select code, name from scotland where ST_DWithin(geom, {point}, 100);")
        row = cur.fetchone()

    conn.close()
    if row:
        return row[0]


def wdqs_geosearch_query(lat, lon):
    if isinstance(lat, float):
        lat = f'{lat:f}'
    if isinstance(lon, float):
        lon = f'{lon:f}'

    query_template = '''

SELECT DISTINCT ?item ?distance ?itemLabel ?isa ?isaLabel ?commonsCat ?commonsSiteLink WHERE {
  {
    SELECT DISTINCT ?item ?location ?distance ?isa WHERE {
      ?item wdt:P31/wdt:P279* wd:Q486972.
      ?item wdt:P31 ?isa .
      SERVICE wikibase:around {
        ?item wdt:P625 ?location.
        bd:serviceParam wikibase:center "Point(LON LAT)"^^geo:wktLiteral;
          wikibase:radius 5;
          wikibase:distance ?distance.
      }
    }
  }
  MINUS { ?item wdt:P582 ?endTime . }
  OPTIONAL { ?item wdt:P373 ?commonsCat. }
  OPTIONAL { ?commonsSiteLink schema:about ?item;
             schema:isPartOf <https://commons.wikimedia.org/>. }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }
} ORDER BY (?distance)'''

    query = query_template.replace('LAT', lat).replace('LON', lon)
    reply = wdqs(query)
    return reply['results']['bindings']


def wdqs_geosearch(lat, lon):
    default_max_dist = 1
    rows = wdqs_geosearch_query(lat, lon)
    max_dist = {
        'Q188509': 1,   # suburb
        'Q3957': 2,     # town
        'Q532': 1,      # village
        'Q5084': 1,     # hamlet
        'Q515': 2,      # city
        'Q1549591': 3,  # big city
    }
    for row in rows:
        isa = wd_uri_to_qid(row['isa']['value'])

        if ('commonsCat' not in row and 'commonsSiteLink' not in row and isa not in max_dist):
            continue

        distance = float(row['distance']['value'])
        if distance > max_dist.get(isa, default_max_dist):
            continue

        if 'commonsCat' not in row and 'commonsSiteLink' not in row:
            break

        return row


def lat_lon_to_wikidata(lat, lon):
    scotland_code = get_scotland_code(lat, lon)

    if scotland_code:
        rows = lookup_scottish_parish_in_wikidata(scotland_code)
        hit = commons_from_rows(rows)
        elements = []
        result = build_dict(hit, lat, lon)

        return {'elements': elements, 'result': result}

    elements = get_osm_elements(lat, lon)
    result = do_lookup(elements, lat, lon)

    # special case because the City of London is admin_level=6 in OSM
    if result['wikidata'] == city_of_london_qid:
        return {'elements': elements, 'result': result}

    admin_level = result['admin_level']

    if not admin_level or admin_level >= 7:
        return {'elements': elements, 'result': result}

    row = wdqs_geosearch(lat, lon)
    if row:
        hit = commons_from_rows([row])
        elements = []
        result = build_dict(hit, lat, lon)

    return {'elements': elements, 'result': result}


@app.route("/")
def index():
    q = request.args.get("q")
    if q and q.strip():
        lat, lon = [v.strip() for v in q.split(",", 1)]
        return redirect(url_for("detail_page", lat=lat, lon=lon))

    lat = request.args.get("lat")
    lon = request.args.get("lon")
    if lat is None or lon is None:
        samples.sort(key=lambda row: row[2])
        return render_template("index.html", samples=samples)

    return jsonify(lat_lon_to_wikidata(lat, lon)["result"])


def wikidata_api_call(params):
    return requests.get(
        "https://www.wikidata.org/w/api.php",
        params={"format": "json", "formatversion": 2, **params},
        headers=headers
    ).json()


def get_entity(qid):
    json_data = wikidata_api_call({"action": "wbgetentities", "ids": qid})

    try:
        entity = list(json_data["entities"].values())[0]
    except KeyError:
        return
    if "missing" not in entity:
        return entity


def qid_to_commons_category(qid):
    entity = get_entity(qid)
    try:
        commons_cat = entity["claims"]["P373"][0]["mainsnak"]["datavalue"]["value"]
    except Exception:
        commons_cat = None

    return commons_cat


def wdqs(query):
    r = requests.post(
        wikidata_query_api_url,
        data={"query": query, "format": "json"},
        headers=headers
    )

    try:
        return r.json()
    except simplejson.errors.JSONDecodeError:
        raise QueryError(query, r)


def run_query(oql, error_on_rate_limit=True):
    return requests.post(OVERPASS_URL + '/api/interpreter',
                         data=oql.encode('utf-8'),
                         headers=headers)


def get_elements(oql):
    return run_query(oql).json()['elements']


def is_in_lat_lon(lat, lon):
    oql = f'''
[out:json][timeout:25];
is_in({lat},{lon})->.a;
(way(pivot.a); rel(pivot.a););
out bb tags qt;'''

    return run_query(oql)


def lookup_scottish_parish_in_wikidata(code):
    query = '''
SELECT ?item ?itemLabel ?commonsSiteLink ?commonsCat WHERE {
  ?item wdt:P528 "CODE" .
  ?item wdt:P31 wd:Q5124673 .
  OPTIONAL { ?commonsSiteLink schema:about ?item ;
             schema:isPartOf <https://commons.wikimedia.org/> }
  OPTIONAL { ?item wdt:P373 ?commonsCat }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }
}
'''.replace('CODE', code)
    reply = wdqs(query)
    return reply['results']['bindings']


def lookup_gss_in_wikidata(gss):
    query = '''
SELECT ?item ?itemLabel ?commonsSiteLink ?commonsCat WHERE {
  ?item wdt:P836 GSS .
  OPTIONAL { ?commonsSiteLink schema:about ?item ;
             schema:isPartOf <https://commons.wikimedia.org/> }
  OPTIONAL { ?item wdt:P373 ?commonsCat }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }
}
'''.replace('GSS', repr(gss))
    reply = wdqs(query)
    return reply['results']['bindings']


def lookup_wikidata_by_name(name, lat, lon):
    query = '''
SELECT DISTINCT ?item ?itemLabel ?commonsSiteLink ?commonsCat WHERE {
  ?item rdfs:label LABEL@en .
  FILTER NOT EXISTS { ?item wdt:P31 wd:Q17362920 } .# ignore Wikimedia duplicated page
  OPTIONAL { ?commonsSiteLink schema:about ?item ;
             schema:isPartOf <https://commons.wikimedia.org/> }
  OPTIONAL { ?item wdt:P373 ?commonsCat }
  ?item wdt:P625 ?coords .

  FILTER(geof:distance(?coords, "Point(LON LAT)"^^geo:wktLiteral) < 10)
  FILTER(?commonsCat || ?commonsSiteLink)

  SERVICE wikibase:label { bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }
}
'''.replace('LABEL', repr(name)).replace('LAT', str(lat)).replace('LON', str(lon))

    reply = wdqs(query)
    return reply['results']['bindings']


def unescape_title(t):
    return urllib.parse.unquote(t.replace("_", " "))


def commons_from_rows(rows):
    for row in rows:
        if "commonsCat" in row:
            qid = wd_to_qid(row["item"])
            return {"wikidata": qid,
                    "commons_cat": row["commonsCat"]["value"]}
        if "commonsSiteLink" in row:
            site_link = row["commonsSiteLink"]["value"]
            qid = wd_to_qid(row["item"])
            cat = unescape_title(site_link[len(commons_cat_start):])
            return {"wikidata": qid, "commons_cat": cat}


def get_commons_cat_from_gss(gss):
    return commons_from_rows(lookup_gss_in_wikidata(gss))


def get_osm_elements(lat, lon):
    filename = f"cache/{lat}_{lon}.json"

    if use_cache and os.path.exists(filename):
        elements = json.load(open(filename))["elements"]
    else:
        r = is_in_lat_lon(lat, lon)
        if use_cache:
            open(filename, "wb").write(r.content)
        elements = r.json()["elements"]

    return elements


def osm_lookup(elements, lat, lon):
    elements.sort(key=lambda e: bounding_box_area(e))

    for e in elements:
        if "tags" not in e:
            continue
        tags = e["tags"]
        admin_level_tag = tags.get("admin_level")
        admin_level = int(admin_level_tag) if admin_level_tag and admin_level_tag.isdigit() else None
        if not admin_level and tags.get("boundary") != "political":
            continue
        if "wikidata" in tags:
            qid = tags["wikidata"]
            commons = qid_to_commons_category(qid)
            if commons:
                return {
                    "wikidata": qid,
                    "commons_cat": commons,
                    "admin_level": admin_level,
                }
        gss = tags.get("ref:gss")
        if gss:
            ret = get_commons_cat_from_gss(gss)
            if ret:
                ret["admin_level"] = admin_level
                return ret

        name = tags.get("name")
        if not name:
            continue
        if name.endswith(" CP"):
            name = name[:-3]
        rows = lookup_wikidata_by_name(name, lat, lon)

        if len(rows) == 1:
            ret = commons_from_rows(rows)
            if ret:
                ret["admin_level"] = admin_level
                return ret

    has_wikidata_tag = [e["tags"] for e in elements if "wikidata" in e["tags"]]
    if len(has_wikidata_tag) != 1:
        return

    qid = has_wikidata_tag[0]["wikidata"]
    return {
        "wikidata": qid,
        "commons_cat": qid_to_commons_category(qid),
        "admin_level": admin_level,
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0")
