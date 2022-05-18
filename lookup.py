#!/usr/bin/python3

from flask import Flask, render_template, request, jsonify, redirect, url_for
from geocode import wikidata, scotland, database, model
import geocode
import random

city_of_london_qid = "Q23311"
app = Flask(__name__)
app.config.from_object("config.default")
database.init_app(app)


def get_random_lat_lon():
    """ Select random lat/lon within the UK """
    south, east = 50.8520, 0.3536
    north, west = 53.7984, -2.7296

    mul = 10000
    lat = random.randrange(int(south * mul), int(north * mul)) / mul
    lon = random.randrange(int(west * mul), int(east * mul)) / mul

    return lat, lon


def do_lookup(elements, lat, lon):
    try:
        hit = osm_lookup(elements, lat, lon)
    except wikidata.QueryError as e:
        return {
            "query": e.query,
            "error": e.r.text,
            "query_url": "https://query.wikidata.org/#" + e.query,
        }

    return wikidata.build_dict(hit, lat, lon)


def lat_lon_to_wikidata(lat, lon):
    scotland_code = scotland.get_scotland_code(lat, lon)

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


def osm_lookup(elements, lat, lon):
    for e in elements:
        tags = e.tags
        admin_level_tag = tags.get("admin_level")
        admin_level = (
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
                }
        gss = tags.get("ref:gss")
        if gss:
            ret = wikidata.get_commons_cat_from_gss(gss)
            if ret:
                ret["admin_level"] = admin_level
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
                return ret

    has_wikidata_tag = [e["tags"] for e in elements if "wikidata" in e["tags"]]
    if len(has_wikidata_tag) != 1:
        return

    qid = has_wikidata_tag[0]["wikidata"]
    return {
        "wikidata": qid,
        "commons_cat": wikidata.qid_to_commons_category(qid),
        "admin_level": admin_level,
    }


@app.route("/")
def index():
    q = request.args.get("q")
    if q and q.strip():
        lat, lon = [v.strip() for v in q.split(",", 1)]
        return redirect(url_for("detail_page", lat=lat, lon=lon))

    lat, lon = request.args.get("lat"), request.args.get("lon")

    if lat is not None and lon is not None:
        return jsonify(lat_lon_to_wikidata(lat, lon)["result"])

    samples = sorted(geocode.samples, key=lambda row: row[2])
    return render_template("index.html", samples=samples)


@app.route("/random")
def random_location():
    lat, lon = get_random_lat_lon()

    elements = model.Polygon.coords_within(lat, lon)
    result = do_lookup(elements, lat, lon)

    return render_template(
        "detail.html", lat=lat, lon=lon, result=result, elements=elements
    )


@app.route("/wikidata_tag")
def wikidata_tag():
    lat = float(request.args.get("lat"))
    lon = float(request.args.get("lon"))

    scotland_code = scotland.get_scotland_code(lat, lon)

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
def detail_page():
    try:
        lat, lon = [float(request.args.get(param)) for param in ("lat", "lon")]
    except TypeError:
        return redirect(url_for("index"))
    try:
        reply = lat_lon_to_wikidata(lat, lon)
    except wikidata.QueryError as e:
        query, r = e.args
        return render_template(
            "query_error.html",
            lat=lat,
            lon=lon,
            query=query,
            r=r
        )

    return render_template("detail.html", lat=lat, lon=lon, **reply)


if __name__ == "__main__":
    app.run(host="0.0.0.0")
