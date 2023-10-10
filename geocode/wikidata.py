from flask import render_template
import requests
import simplejson
from . import headers
import urllib.parse

wikidata_query_api_url = "https://query.wikidata.org/bigdata/namespace/wdq/sparql"
wd_entity = "http://www.wikidata.org/entity/Q"
commons_cat_start = "https://commons.wikimedia.org/wiki/Category:"


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


def wd_to_qid(wd):
    # expecting {"type": "url", "value": "https://www.wikidata.org/wiki/Q30"}
    if wd["type"] == "uri":
        return wd_uri_to_qid(wd["value"])


def wd_uri_to_qid(value):
    assert value.startswith(wd_entity)
    return value[len(wd_entity) - 1 :]

def geosearch_query(lat, lon):
    if isinstance(lat, float):
        lat = f"{lat:f}"
    if isinstance(lon, float):
        lon = f"{lon:f}"

    query = render_template("sparql/geosearch.sparql", lat=lat, lon=lon)
    return wdqs(query)


def geosearch(lat, lon):
    default_max_dist = 1
    rows = geosearch_query(lat, lon)
    max_dist = {
        "Q188509": 1,  # suburb
        "Q3957": 2,  # town
        "Q532": 1,  # village
        "Q5084": 1,  # hamlet
        "Q515": 2,  # city
        "Q1549591": 3,  # big city
    }
    for row in rows:
        isa = wd_uri_to_qid(row["isa"]["value"])

        if (
            "commonsCat" not in row
            and "commonsSiteLink" not in row
            and isa not in max_dist
        ):
            continue

        distance = float(row["distance"]["value"])
        if distance > max_dist.get(isa, default_max_dist):
            continue

        if "commonsCat" not in row and "commonsSiteLink" not in row:
            break

        return row


def lookup_scottish_parish_in_wikidata(code):
    query = render_template("sparql/scottish_parish.sparql", code=code)
    return wdqs(query)


def lookup_gss_in_wikidata(gss):
    query = render_template("sparql/lookup_gss.sparql", gss=gss)
    return wdqs(query)


def lookup_wikidata_by_name(name, lat, lon):
    query = render_template(
        "sparql/lookup_by_name.sparql", name=repr(name), lat=str(lat), lon=str(lon)
    )
    return wdqs(query)


def unescape_title(t):
    return urllib.parse.unquote(t.replace("_", " "))


def commons_from_rows(rows):
    for row in rows:
        if "commonsCat" in row:
            qid = wd_to_qid(row["item"])
            return {"wikidata": qid, "commons_cat": row["commonsCat"]["value"]}
        if "commonsSiteLink" in row:
            site_link = row["commonsSiteLink"]["value"]
            qid = wd_to_qid(row["item"])
            cat = unescape_title(site_link[len(commons_cat_start) :])
            return {"wikidata": qid, "commons_cat": cat}


def get_commons_cat_from_gss(gss):
    return commons_from_rows(lookup_gss_in_wikidata(gss))


def build_dict(hit, lat, lon):
    coords = {"lat": lat, "lon": lon}
    if hit is None:
        return dict(commons_cat=None, missing=True, coords=coords)
    commons_cat = hit["commons_cat"]
    ret = dict(
        coords=coords,
        admin_level=hit.get("admin_level"),
        wikidata=hit["wikidata"],
    )
    if not commons_cat:
        return ret

    url = commons_cat_start + urllib.parse.quote(commons_cat.replace(" ", "_"))
    ret["commons_cat"] = {"title": commons_cat, "url": url}

    return ret
