#!/usr/bin/python3
"""Reverse geocode: convert lat/lon to Wikidata item & Wikimedia Commons category."""

import inspect
import random
import socket
import sys
import traceback
import typing
from time import time

import sqlalchemy.exc
import werkzeug.debug.tbtools
from flask import Flask, jsonify, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.orm.query import Query
from werkzeug.wrappers import Response

import geocode
from geocode import database, model, scotland, wikidata
from geocode.error_mail import setup_error_mail

city_of_london_qid = "Q23311"
app = Flask(__name__)
app.config.from_object("config.default")
database.init_app(app)
setup_error_mail(app)

Tags = typing.Mapping[str, str]
StrDict = dict[str, typing.Any]
logging_enabled = True

fallback_qid_to_commons_cat = {"Q68816332": "Orphir"}


@app.errorhandler(werkzeug.exceptions.InternalServerError)
def exception_handler(e: werkzeug.exceptions.InternalServerError) -> tuple[str, int]:
    """Handle exception."""
    exec_type, exc_value, current_traceback = sys.exc_info()
    assert exc_value
    tb = werkzeug.debug.tbtools.DebugTraceback(exc_value)

    summary = tb.render_traceback_html(include_title=False)
    exc_lines = "".join(tb._te.format_exception_only())

    last_frame = list(traceback.walk_tb(current_traceback))[-1][0]
    last_frame_args = inspect.getargs(last_frame.f_code)

    return (
        render_template(
            "show_error.html",
            plaintext=tb.render_traceback_text(),
            exception=exc_lines,
            exception_type=tb._te.exc_type.__name__,
            summary=summary,
            last_frame=last_frame,
            last_frame_args=last_frame_args,
        ),
        500,
    )


def get_random_lat_lon() -> tuple[float, float]:
    """Select random lat/lon within the UK."""
    south, east = 50.8520, 0.3536
    north, west = 53.7984, -2.7296

    mul = 10000
    lat = random.randrange(int(south * mul), int(north * mul)) / mul
    lon = random.randrange(int(west * mul), int(east * mul)) / mul

    return lat, lon


def do_lookup(
    elements: "Query[model.Polygon]", lat: float, lon: float
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


def add_missing_commons_cat(rows: list[StrDict]) -> None:
    """Add missing details for Commons Categories to Wikidata query results."""
    for row in rows:
        if "commonsSiteLink" in row or "commonsCat" in row:
            continue

        qid = row["item"]["value"].rpartition("/")[2]
        if qid not in fallback_qid_to_commons_cat:
            continue

        commons_cat = fallback_qid_to_commons_cat[qid]
        row["commonsCat"] = {"type": "literal", "value": commons_cat}


def lat_lon_to_wikidata(lat: float, lon: float) -> dict[str, typing.Any]:
    """Lookup lat/lon and find most appropriate Wikidata item."""
    scotland_code = scotland.get_scotland_code(lat, lon)

    elements: typing.Any
    if scotland_code:
        rows = wikidata.lookup_scottish_parish_in_wikidata(scotland_code)
        add_missing_commons_cat(rows)
        hit = wikidata.commons_from_rows(rows)
        elements = []
        result = wikidata.build_dict(hit, lat, lon)

        if not result.get("missing"):
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


def hit_from_name(tags: Tags, lat: float, lon: float) -> wikidata.Hit | None:
    """Use name to look for hit."""
    if not (name := tags.get("name")):
        return None
    if name.endswith(" CP"):  # civil parish
        name = name[:-3]

    rows = wikidata.lookup_wikidata_by_name(name, lat, lon)
    return wikidata.commons_from_rows(rows) if len(rows) == 1 else None


def osm_lookup(
    elements: "Query[model.Polygon]", lat: float, lon: float
) -> wikidata.Hit | None:
    """OSM lookup."""
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
    t0 = time()
    database.session.execute("SELECT 1")
    q = request.args.get("q")
    if q and q.strip():
        return redirect_to_detail(q)

    lat_str, lon_str = request.args.get("lat"), request.args.get("lon")

    if lat_str is None or lon_str is None:
        samples = sorted(geocode.samples, key=lambda row: row[2])
        return render_template("index.html", samples=samples)

    lat, lon = float(lat_str), float(lon_str)

    if lat < -90 or lat > 90 or lon < -180 or lon > 180:
        return jsonify(
            coords={"lat": lat, "lon": lon},
            error="lat must be between -90 and 90, "
            + "and lon must be between -180 and 180",
        )

    result = lat_lon_to_wikidata(lat, lon)["result"]
    result.pop("element", None)
    result.pop("geojson", None)
    if logging_enabled:
        remote_addr = request.headers.get("X-Forwarded-For", request.remote_addr)
        log = model.LookupLog(
            lat=lat,
            lon=lon,
            remote_addr=remote_addr,
            fqdn=socket.getfqdn(remote_addr) if remote_addr else None,
            result=result,
            response_time_ms=int((time() - t0) * 1000),
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
    if lat < -90 or lat > 90 or lon < -180 or lon > 180:
        error = (
            "latitude must be between -90 and 90, "
            + "and longitude must be between -180 and 180"
        )
        return render_template("query_error.html", lat=lat, lon=lon, error=error)

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


@app.route("/reports")
def reports() -> str:
    """Return reports page with various statistics."""
    log_count = model.LookupLog.query.count()

    log_start_time, average_response_time = database.session.query(
        func.min(model.LookupLog.dt), func.avg(model.LookupLog.response_time_ms)
    ).one()

    # Construct the query
    by_day = (
        database.session.query(
            func.date(model.LookupLog.dt).label("log_date"),
            func.count(model.LookupLog.id).label("count"),
        )
        .group_by("log_date")
        .order_by(func.date(model.LookupLog.dt).desc())
    )

    top_places = (
        database.session.query(
            model.LookupLog.result["commons_cat"]["title"].label("place"),
            func.count().label("num"),
        )
        .group_by("place")
        .order_by(func.count().desc())
        .limit(50)
    )

    missing_places = (
        database.session.query(model.LookupLog)
        .filter(
            model.LookupLog.result.has_key("missing")  # type: ignore
        )  # Filtering for entries where result contains 'missing'
        .order_by(model.LookupLog.dt.desc())  # Ordering by dt in descending order
        .limit(50)  # Limiting to the top 50 results
    )

    return render_template(
        "reports.html",
        log_count=log_count,
        log_start_time=log_start_time,
        average_response_time=average_response_time,
        by_day=by_day,
        top_places=top_places,
        missing_places=missing_places,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0")
