#!/usr/bin/python3

from flask import Flask, render_template, request, jsonify
import requests
import os
import json
import urllib.parse
import random

commons_cat_start = 'https://commons.wikimedia.org/wiki/Category:'
use_cache = False

south = 50.8520
east = 0.3536

north = 53.7984
west = -2.7296

headers = {
    'User-Agent': 'UK gecode/0.1 (edward@4angle.com)',
}

OVERPASS_URL = 'https://lz4.overpass-api.de'
wikidata_query_api_url = 'https://query.wikidata.org/bigdata/namespace/wdq/sparql'
wikidata_url = 'https://www.wikidata.org/w/api.php'

samples = [
    (50.8326, -0.2689, 'Adur'),
    (52.4914, -0.69645, 'Corby'),
    (50.893, -4.265, 'Newton St Petrock'),
    (51.779, 0.128, 'Harlow'),
    (52.387, 0.294, 'Ely'),
    (50.9, -1.6, 'Minstead'),
    (52.43, -1.11, 'South Kilworth'),
    (53.117, -0.202, 'Tattershall Thorpe'),
    (53.351, -2.701, 'Halton'),
    (52.421, -0.651, 'Warkton'),
    (51.51, -1.547, 'Lambourn'),
    (52.62, -1.884, 'Shenstone'),
    (53.309, -1.539, 'Sheffield'),
    (53.322, 0.032, 'Haugham'),
    (51.05, -2.598, 'Babcary'),
    (51.158, -1.906, 'Berwick St James'),
    (51.867, -1.204, 'Weston-on-the-Green'),
    (51.034, -2.005, 'Ebbesbourne Wake'),
    (51.07, -0.718, 'Fernhurst'),
    (53.059, -0.144, 'Wildmore'),
    (51.473, 0.221, 'Dartford'),
    (51.059, 0.05, 'Danehill'),
    (52.253, -0.122, 'Papworth Everard'),
    (53.498, -0.415, 'West Lindsey'),
    (53.392, -0.022, 'Brackenborough with Little Grimsby'),
    (53.463, -0.027, 'Fulstow'),
    (52.766, 0.31, 'Terrington St Clement'),
    (53.1540, -1.8034, 'Hartington Town Quarter'),
    (51.8532, -0.8829, 'Fleet Marston'),
    (51.4785, -0.354, 'London Borough of Hounslow'),
    (51.9687, -0.0327, 'Buckland, Hertfordshire'),
    (51.0804, -2.3263, 'Zeals'),
    (55.7644, -4.1770, 'East Kilbride'),
    (51.4520, -2.6210, 'Bristol'),
]

class QueryError(Exception):
    def __init__(self, query, r):
        self.query = query
        self.r = r


app = Flask(__name__)
app.debug = True

mul = 10000

@app.route("/random")
def random_location():
    lat = random.randrange(int(south * mul), int(north * mul)) / mul
    lon = random.randrange(int(west * mul), int(east * mul)) / mul

    elements = get_osm_elements(lat, lon)
    result = do_lookup(elements, lat, lon)

    return render_template('random.html', lat=lat, lon=lon, result=result, elements=elements)

def do_lookup(elements, lat, lon):
    commons_cat = osm_lookup(elements)
    coords = {'lat': lat, 'lon': lon}
    if commons_cat is None:
        return dict(commons_cat=None, missing=True, coords=coords)
    url = commons_cat_start + urllib.parse.quote(commons_cat.replace(' ', '_'))
    return dict(commons_cat={'title': commons_cat, 'url': url}, coords=coords)

@app.route("/")
def index():
    lat = request.args.get('lat')
    lon = request.args.get('lon')
    if lat is None or lon is None:
        return render_template('index.html', samples=samples)

    elements = get_osm_elements(lat, lon)
    ret = do_lookup(elements, lat, lon)
    return jsonify(ret)

def wikidata_api_call(params):
    call_params = {
        'format': 'json',
        'formatversion': 2,
        **params,
    }

    r = requests.get(wikidata_url, params=call_params, headers=headers)
    return r

def get_entity(qid):
    json_data = wikidata_api_call({'action': 'wbgetentities', 'ids': qid}).json()

    try:
        entity = list(json_data['entities'].values())[0]
    except KeyError:
        return
    if 'missing' not in entity:
        return entity

def qid_to_commons_category(qid):
    entity = get_entity(qid)
    try:
        commons_cat = entity['claims']['P373'][0]['mainsnak']['datavalue']['value']
    except Exception:
        commons_cat = None

    return commons_cat

def wdqs(query):
    r = requests.post(wikidata_query_api_url,
                      data={'query': query, 'format': 'json'},
                      headers=headers)

    try:
        return r.json()
    except simplejson.errors.JSONDecodeError:
        raise QueryError(query, r)

def endpoint():
    return OVERPASS_URL + '/api/interpreter'

def run_query(oql, error_on_rate_limit=True):
    return requests.post(endpoint(),
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

def lookup_gss_in_wikidata(gss):
    query = '''
SELECT ?item ?itemLabel ?commonsSiteLink ?commonsCat WHERE {
  ?item wdt:P836 "GSS" .
  OPTIONAL { ?commonsSiteLink schema:about ?item ;
             schema:isPartOf <https://commons.wikimedia.org/> }
  OPTIONAL { ?item wdt:P373 ?commonsCat }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }
}
'''.replace('GSS', gss)
    reply = wdqs(query)
    return reply['results']['bindings']

def unescape_title(t):
    return urllib.parse.unquote(t.replace('_', ' '))

def get_commons_cat_from_gss(gss):
    rows = lookup_gss_in_wikidata(gss)
    for row in rows:
        if 'commonsCat' in row:
            return row['commonsCat']['value']
        if 'commonsSiteLink' in row:
            site_link = row['commonsSiteLink']['value']
            return unescape_title(site_link[len(commons_cat_start):])

def get_osm_elements(lat, lon):
    filename = f'cache/{lat}_{lon}.json'

    if use_cache and os.path.exists(filename):
        elements = json.load(open(filename))['elements']
    else:
        r = is_in_lat_lon(lat, lon)
        if use_cache:
            open(filename, 'wb').write(r.content)
        elements = r.json()['elements']

    return elements

def osm_lookup(elements):
    is_in = []
    for e in elements:
        try:
            admin_level = int(e['tags']['admin_level'])
        except (ValueError, KeyError):
            continue

        is_in.append((admin_level, e['tags']))

    for _, tags in sorted(is_in, key=lambda i: i[0], reverse=True):
        if 'wikidata' in tags:
            qid = tags['wikidata']
            return qid_to_commons_category(qid)
        gss = tags.get('ref:gss')
        if not gss:
            continue
        return get_commons_cat_from_gss(gss)


if __name__ == '__main__':
    app.run(host='0.0.0.0')
