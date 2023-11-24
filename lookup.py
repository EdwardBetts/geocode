#!/usr/bin/python3
"""Reverse geocode: convert lat/lon to Wikidata item & Wikimedia Commons category."""

import random
import typing

import sqlalchemy.exc
from flask import Flask, jsonify, redirect, render_template, request, url_for
from sqlalchemy.orm.query import Query
from werkzeug.wrappers import Response

import geocode
from geocode import database, model, scotland, wikidata

city_of_london_qid = "Q23311"
app = Flask(__name__)
app.config.from_object("config.default")
database.init_app(app)

Tags = typing.Mapping[str, str]


def get_random_lat_lon() -> tuple[float, float]:
    """Select random lat/lon within the UK."""
    south, east = 50.8520, 0.3536
    north, west = 53.7984, -2.7296

    mul = 10000
    lat = random.randrange(int(south * mul), int(north * mul)) / mul
    lon = random.randrange(int(west * mul), int(east * mul)) / mul

    return lat, lon


def do_lookup(
    elements: "Query[model.Polygon]", lat: str | float, lon: str | float
) -> wikidata.WikidataDict:
    """Do lookup."""
    try:
        hit = osm_lookup(elements, lat, lon)
    except wikidata.QueryError as e:
        return {
            "query": e.query,
            "error": e.r.text,
            "query_url": "https://query.wikidata.org/#" + e.query,
        }

    return wikidata.build_dict(hit, lat, lon)


def lat_lon_to_wikidata(lat: str | float, lon: str | float) -> dict[str, typing.Any]:
    """Lookup lat/lon and find most appropriate Wikidata item."""
    scotland_code = scotland.get_scotland_code(lat, lon)

    elements: typing.Any
    if scotland_code:
        rows = wikidata.lookup_scottish_parish_in_wikidata(scotland_code)
        hit = wikidata.commons_from_rows(rows)
        elements = []
        result = wikidata.build_dict(hit, lat, lon)

        return {"elements": elements, "result": result}

    elements = model.Polygon.coords_within(lat, lon)
    result = do_lookup(elements, lat, lon)

    # special case because the City of London is admin_level=6 in OSM
    if result.get("wikidata") == city_of_london_qid:
        return {"elements": elements, "result": result}

    admin_level = result.get("admin_level")
    if not admin_level:
        return {"elements": elements, "result": result}

    assert isinstance(admin_level, int)
    if admin_level >= 7:
        return {"elements": elements, "result": result}

    row = wikidata.geosearch(lat, lon)
    if row:
        hit = wikidata.commons_from_rows([row])
        elements = []
        result = wikidata.build_dict(hit, lat, lon)

    return {"elements": elements, "result": result}


def get_admin_level(tags: Tags) -> int | None:
    """Read admin_level from tags."""
    admin_level_tag = tags.get("admin_level")
    return (
        int(admin_level_tag) if admin_level_tag and admin_level_tag.isdigit() else None
    )


def hit_from_wikidata_tag(tags: Tags) -> wikidata.Hit | None:
    """Check element for a wikidata tag."""
    return (
        {
            "wikidata": qid,
            "commons_cat": commons,
        }
        if "wikidata" in tags
        and (commons := wikidata.qid_to_commons_category(qid := tags["wikidata"]))
        else None
    )


def hit_from_ref_gss_tag(tags: Tags) -> wikidata.Hit | None:
    """Check element for rss:gss tag."""
    gss = tags.get("ref:gss")
    return wikidata.get_commons_cat_from_gss(gss) if gss else None


def hit_from_name(
    tags: Tags, lat: str | float, lon: str | float
) -> wikidata.Hit | None:
    """Use name to look for hit."""
    if not (name := tags.get("name")):
        return None
    if name.endswith(" CP"):  # civil parish
        name = name[:-3]

    rows = wikidata.lookup_wikidata_by_name(name, lat, lon)
    return wikidata.commons_from_rows(rows) if len(rows) == 1 else None


def osm_lookup(
    elements: "Query[model.Polygon]", lat: str | float, lon: str | float
) -> wikidata.Hit | None:
    """OSM lookup."""
    ret: wikidata.Hit | None
    for e in elements:
        assert isinstance(e, model.Polygon)
        assert e.tags
        tags: typing.Mapping[str, str] = e.tags
        admin_level: int | None = get_admin_level(tags)
        if not admin_level and tags.get("boundary") not in ("political", "place"):
            continue
        if not (
            (hit := hit_from_wikidata_tag(tags))
            or (hit := hit_from_ref_gss_tag(tags))
            or (hit := hit_from_name(tags, lat, lon))
        ):
            continue
        hit["admin_level"] = admin_level
        hit["element"] = e.osm_id
        hit["geojson"] = typing.cast(str, e.geojson_str)
        return hit

    has_wikidata_tag = [e for e in elements if e.tags.get("wikidata")]
    if len(has_wikidata_tag) != 1:
        return None

    e = has_wikidata_tag[0]
    assert e.tags
    qid = e.tags["wikidata"]
    return {
        "wikidata": qid,
        "element": e.osm_id,
        "geojson": typing.cast(str, e.geojson_str),
        "commons_cat": wikidata.qid_to_commons_category(qid),
        "admin_level": admin_level,
    }


def redirect_to_detail(q: str) -> Response:
    """Redirect to detail page."""
    lat, lon = [v.strip() for v in q.split(",", 1)]
    return redirect(url_for("detail_page", lat=lat, lon=lon))


@app.errorhandler(sqlalchemy.exc.OperationalError)
def handle_database_error(error: Exception) -> tuple[str, int]:
    """Show error screen on database error."""
    return render_template("database_error.html"), 500


@app.route("/")
def index() -> str | Response:
    """Index page."""
    database.session.execute("SELECT 1")
    q = request.args.get("q")
    if q and q.strip():
        return redirect_to_detail(q)

    lat, lon = request.args.get("lat"), request.args.get("lon")

    if lat is None or lon is None:
        samples = sorted(geocode.samples, key=lambda row: row[2])
        return render_template("index.html", samples=samples)

    result = lat_lon_to_wikidata(lat, lon)["result"]
    result.pop("element", None)
    result.pop("geojson", None)
    log = model.LookupLog(
        lat=lat, lon=lon, remote_addr=request.remote_addr, result=result
    )
    database.session.add(log)
    database.session.commit()
    return jsonify(result)


@app.route("/random")
def random_location() -> str | Response:
    """Return detail page for random lat/lon."""
    lat, lon = get_random_lat_lon()
    return build_detail_page(lat, lon)


@app.route("/wikidata_tag")
def wikidata_tag() -> str:
    """Lookup Wikidata tag for lat/lon."""
    lat_str, lon_str = request.args["lat"], request.args["lon"]
    lat, lon = float(lat_str), float(lon_str)

    scotland_code = scotland.get_scotland_code(lat, lon)

    elements: typing.Any
    if scotland_code:
        rows = wikidata.lookup_scottish_parish_in_wikidata(scotland_code)
        hit = wikidata.commons_from_rows(rows)
        elements = []
        result = wikidata.build_dict(hit, lat, lon)
    else:
        elements = model.Polygon.coords_within(lat, lon)
        result = do_lookup(elements, lat, lon)

    return render_template(
        "wikidata_tag.html", lat=lat, lon=lon, result=result, elements=elements
    )


def build_detail_page(lat: float, lon: float) -> str:
    """Run lookup and build detail page."""
    try:
        reply = lat_lon_to_wikidata(lat, lon)
    except wikidata.QueryError as e:
        query, r = e.args
        return render_template("query_error.html", lat=lat, lon=lon, query=query, r=r)

    element = reply["result"].pop("element", None)
    geojson = reply["result"].pop("geojson", None)

    return render_template(
        "detail.html",
        lat=lat,
        lon=lon,
        str=str,
        element_id=element,
        geojson=geojson,
        **reply,
    )


@app.route("/detail")
def detail_page() -> Response | str:
    """Detail page."""
    database.session.execute("SELECT 1")
    try:
        lat_str, lon_str = request.args["lat"], request.args["lon"]
        lat, lon = float(lat_str), float(lon_str)
    except TypeError:
        return redirect(url_for("index"))

    return build_detail_page(lat, lon)


if __name__ == "__main__":
    app.run(host="0.0.0.0")
