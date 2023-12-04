"""Wikidata API functions."""

import typing
import urllib.parse

import requests
from flask import render_template

from . import headers

wikidata_query_api_url = "https://query.wikidata.org/bigdata/namespace/wdq/sparql"
wd_entity = "http://www.wikidata.org/entity/Q"
commons_cat_start = "https://commons.wikimedia.org/wiki/Category:"


class QueryError(Exception):
    """Query error."""

    def __init__(self, query: str, r: requests.Response):
        """Init."""
        self.query = query
        self.r = r


def api_call(params: dict[str, str | int]) -> dict[str, typing.Any]:
    """Wikidata API call."""
    api_params: dict[str, str | int] = {"format": "json", "formatversion": 2, **params}
    r = requests.get(
        "https://www.wikidata.org/w/api.php", params=api_params, headers=headers
    )
    return typing.cast(dict[str, typing.Any], r.json())


def get_entity(qid: str) -> dict[str, typing.Any] | None:
    """Get Wikidata entity."""
    json_data = api_call({"action": "wbgetentities", "ids": qid})

    try:
        entity: dict[str, typing.Any] = list(json_data["entities"].values())[0]
    except KeyError:
        return None
    return entity if "missing" not in entity else None


def qid_to_commons_category(qid: str, check_p910: bool = True) -> str | None:
    """Commons category for a given Wikidata item."""
    entity = get_entity(qid)
    cat_start = "Category:"
    if not entity:
        return None

    try:
        cat: str = entity["claims"]["P373"][0]["mainsnak"]["datavalue"]["value"]
        return cat
    except Exception:
        pass

    try:
        sitelink = entity["sitelinks"]["commonswiki"]["title"]
    except KeyError:
        sitelink = None

    if sitelink:
        return sitelink[len(cat_start) :] if sitelink.startswith(cat_start) else None

    if not check_p910:
        return None

    try:
        cat_qid = entity["claims"]["P910"][0]["mainsnak"]["datavalue"]["value"]["id"]
    except Exception:
        return None

    return qid_to_commons_category(cat_qid, check_p910=False)


Row = dict[str, dict[str, typing.Any]]


def wdqs(query: str) -> list[Row]:
    """Pass query to the Wikidata Query Service."""
    r = requests.post(
        wikidata_query_api_url, data={"query": query, "format": "json"}, headers=headers
    )

    try:
        return typing.cast(list[Row], r.json()["results"]["bindings"])
    except requests.exceptions.JSONDecodeError:
        raise QueryError(query, r)


def wd_to_qid(wd: dict[str, str]) -> str:
    """Convert Wikidata URL from WDQS to QID."""
    # expecting {"type": "url", "value": "https://www.wikidata.org/wiki/Q30"}
    assert wd["type"] == "uri"
    return wd_uri_to_qid(wd["value"])


def wd_uri_to_qid(value: str) -> str:
    """Convert URL like https://www.wikidata.org/wiki/Q30 to QID."""
    assert value.startswith(wd_entity)
    return value[len(wd_entity) - 1 :]


def geosearch_query(lat: str | float, lon: str | float) -> list[Row]:
    """Geosearch via WDQS."""
    if isinstance(lat, float):
        lat = f"{lat:f}"
    if isinstance(lon, float):
        lon = f"{lon:f}"

    query = render_template("sparql/geosearch.sparql", lat=lat, lon=lon)
    return wdqs(query)


def geosearch(lat: str | float, lon: str | float) -> Row | None:
    """Geosearch."""
    default_max_dist = 1
    rows = geosearch_query(lat, lon)
    max_dist = {
        "Q188509": 1,  # suburb
        "Q3957": 2,  # town
        "Q532": 1,  # village
        "Q5084": 1,  # hamlet
        "Q515": 2,  # city
        "Q1549591": 3,  # big city
        "Q589282": 2,  # ward or electoral division of the United Kingdom
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
    return None


def lookup_scottish_parish_in_wikidata(code: str) -> list[Row]:
    """Lookup scottish parish in Wikidata."""
    return wdqs(render_template("sparql/scottish_parish.sparql", code=code))


def lookup_gss_in_wikidata(gss: str) -> list[Row]:
    """Lookup GSS in Wikidata."""
    return wdqs(render_template("sparql/lookup_gss.sparql", gss=gss))


def lookup_wikidata_by_name(name: str, lat: float | str, lon: float | str) -> list[Row]:
    """Lookup place in Wikidata by name."""
    query = render_template(
        "sparql/lookup_by_name.sparql", name=repr(name), lat=str(lat), lon=str(lon)
    )
    return wdqs(query)


def unescape_title(t: str) -> str:
    """Unescape article title."""
    return urllib.parse.unquote(t.replace("_", " "))


Hit = dict[str, str | int | None]


def commons_from_rows(rows: list[Row]) -> Hit | None:
    """Commons from rows."""
    for row in rows:
        if "commonsCat" in row:
            qid = wd_to_qid(row["item"])
            return {"wikidata": qid, "commons_cat": row["commonsCat"]["value"]}
        if "commonsSiteLink" in row:
            site_link = row["commonsSiteLink"]["value"]
            qid = wd_to_qid(row["item"])
            cat = unescape_title(site_link[len(commons_cat_start) :])
            return {"wikidata": qid, "commons_cat": cat}
    return None


def get_commons_cat_from_gss(gss: str) -> Hit | None:
    """Get commons from GSS via Wikidata."""
    return commons_from_rows(lookup_gss_in_wikidata(gss))


WikidataDict = dict[str, None | bool | str | int | dict[str, typing.Any]]


def build_dict(hit: Hit | None, lat: str | float, lon: str | float) -> WikidataDict:
    """Build dict."""
    coords = {"lat": lat, "lon": lon}
    if hit is None:
        return {"commons_cat": None, "missing": True, "coords": coords}
    commons_cat = hit["commons_cat"]
    ret: WikidataDict = {
        "coords": coords,
        "admin_level": hit.get("admin_level"),
        "wikidata": hit["wikidata"],
        "element": hit.get("element"),
        "geojson": hit.get("geojson"),
    }
    if not commons_cat:
        return ret

    url = commons_cat_start + urllib.parse.quote(commons_cat.replace(" ", "_"))
    ret["commons_cat"] = {"title": commons_cat, "url": url}

    return ret
