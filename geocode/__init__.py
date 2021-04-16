import requests
import simplejson

wikidata_query_api_url = "https://query.wikidata.org/bigdata/namespace/wdq/sparql"
OVERPASS_URL = "https://lz4.overpass-api.de"

headers = {"User-Agent": "UK gecode/0.1 (edward@4angle.com)"}

class QueryError(Exception):
    def __init__(self, query, r):
        self.query = query
        self.r = r


def wikidata_api_call(params):
    return requests.get(
        "https://www.wikidata.org/w/api.php",
        params={"format": "json", "formatversion": 2, **params},
        headers=headers,
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
        wikidata_query_api_url, data={"query": query, "format": "json"}, headers=headers
    )

    try:
        return r.json()
    except simplejson.errors.JSONDecodeError:
        raise QueryError(query, r)


def run_query(oql, error_on_rate_limit=True):
    return requests.post(
        OVERPASS_URL + "/api/interpreter", data=oql.encode("utf-8"), headers=headers
    )



