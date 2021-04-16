import requests
import simplejson
from . import headers

wikidata_query_api_url = "https://query.wikidata.org/bigdata/namespace/wdq/sparql"


class QueryError(Exception):
    def __init__(self, query, r):
        self.query = query
        self.r = r


def api_call(params):
    return requests.get(
        "https://www.wikidata.org/w/api.php",
        params={"format": "json", "formatversion": 2, **params},
        headers=headers,
    ).json()


def get_entity(qid):
    json_data = api_call({"action": "wbgetentities", "ids": qid})

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
        return r.json()["results"]["bindings"]
    except simplejson.errors.JSONDecodeError:
        raise QueryError(query, r)
