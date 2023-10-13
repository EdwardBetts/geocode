#!/usr/bin/python3

import random
import typing

import sqlalchemy
from flask import Flask, jsonify, redirect, render_template, request, url_for
from werkzeug.wrappers import Response

import geocode
from geocode import database, model, scotland, wikidata

city_of_london_qid = "Q23311"
app = Flask(__name__)
app.config.from_object("config.default")
database.init_app(app)


def get_random_lat_lon() -> tuple[float, float]:
    """Select random lat/lon within the UK."""
    south, east = 50.8520, 0.3536
    north, west = 53.7984, -2.7296

    mul = 10000
    lat = random.randrange(int(south * mul), int(north * mul)) / mul
    lon = random.randrange(int(west * mul), int(east * mul)) / mul

    return lat, lon


Elements = sqlalchemy.orm.query.Query


def do_lookup(
    elements: Elements, lat: str | float, lon: str | float
) -> wikidata.WikidataDict:
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

    if not admin_level or admin_level >= 7:
        return {"elements": elements, "result": result}

    row = wikidata.geosearch(lat, lon)
    if row:
        hit = wikidata.commons_from_rows([row])
        elements = []
        result = wikidata.build_dict(hit, lat, lon)

    return {"elements": elements, "result": result}


def osm_lookup(
    elements: Elements, lat: str | float, lon: str | float  # type:ignore
) -> wikidata.Hit | None:
    """OSM lookup."""
    ret: wikidata.Hit | None
    for e in elements:
        assert isinstance(e, model.Polygon)
        assert e.tags
        tags: typing.Mapping[str, typing.Any] = e.tags
        admin_level_tag = tags.get("admin_level")
        admin_level: int | None = (
            int(admin_level_tag)
            if admin_level_tag and admin_level_tag.isdigit()
            else None
        )
        if not admin_level and tags.get("boundary") != "political":
            continue
        if "wikidata" in tags:
            qid = tags["wikidata"]
            commons = wikidata.qid_to_commons_category(qid)
            if commons:
                return {
                    "wikidata": qid,
                    "commons_cat": commons,
                    "admin_level": admin_level,
                    "element": e.osm_id,
                }
        gss = tags.get("ref:gss")
        if gss:
            ret = wikidata.get_commons_cat_from_gss(gss)
            if ret:
                ret["admin_level"] = admin_level
                ret["element"] = e.osm_id
                return ret

        name = tags.get("name")
        if not name:
            continue
        if name.endswith(" CP"):
            name = name[:-3]
        rows = wikidata.lookup_wikidata_by_name(name, lat, lon)

        if len(rows) == 1:
            ret = wikidata.commons_from_rows(rows)
            if ret:
                ret["admin_level"] = admin_level
                ret["element"] = e.osm_id
                return ret

    has_wikidata_tag = [e.tags for e in elements if e.tags.get("wikidata")]
    if len(has_wikidata_tag) != 1:
        return None

    assert has_wikidata_tag[0]
    qid = has_wikidata_tag[0]["wikidata"]
    return typing.cast(
        wikidata.Hit,
        {
            "wikidata": qid,
            "commons_cat": wikidata.qid_to_commons_category(qid),
            "admin_level": admin_level,
        },
    )


def redirect_to_detail(q: str) -> Response:
    """Redirect to detail page."""
    lat, lon = [v.strip() for v in q.split(",", 1)]
    return redirect(url_for("detail_page", lat=lat, lon=lon))


@app.route("/")
def index() -> str | Response:
    """Index page."""
    q = request.args.get("q")
    if q and q.strip():
        return redirect_to_detail(q)

    lat, lon = request.args.get("lat"), request.args.get("lon")

    if lat is not None and lon is not None:
        result = lat_lon_to_wikidata(lat, lon)["result"]
        result.pop("element", None)
        return jsonify(result)

    samples = sorted(geocode.samples, key=lambda row: row[2])
    return render_template("index.html", samples=samples)


@app.route("/random")
def random_location() -> str:
    """Return detail page for random lat/lon."""
    lat, lon = get_random_lat_lon()

    elements = model.Polygon.coords_within(lat, lon)
    result = do_lookup(elements, lat, lon)

    return render_template(
        "detail.html", lat=lat, lon=lon, result=result, elements=elements
    )


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


@app.route("/detail")
def detail_page() -> Response | str:
    """Detail page."""
    try:
        lat_str, lon_str = request.args["lat"], request.args["lon"]
        lat, lon = float(lat_str), float(lon_str)
    except TypeError:
        return redirect(url_for("index"))
    try:
        reply = lat_lon_to_wikidata(lat, lon)
    except wikidata.QueryError as e:
        query, r = e.args
        return render_template("query_error.html", lat=lat, lon=lon, query=query, r=r)

    element = reply["result"].pop("element", None)

    return render_template(
        "detail.html", lat=lat, lon=lon, str=str, element_id=element, **reply
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0")
