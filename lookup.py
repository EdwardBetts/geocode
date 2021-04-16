#!/usr/bin/python3

from flask import Flask, render_template, request, jsonify, redirect, url_for
import geocode
import geocode.wikidata
import geocode.overpass
import urllib.parse
import random
import psycopg2
from geopy.distance import distance

# select gid, code, name from scotland where st_contains(geom, ST_Transform(ST_SetSRID(ST_MakePoint(-4.177, 55.7644), 4326), 27700));

commons_cat_start = "https://commons.wikimedia.org/wiki/Category:"

wd_entity = "http://www.wikidata.org/entity/Q"
city_of_london_qid = "Q23311"


app = Flask(__name__)
app.config.from_object("config.default")


def get_random_lat_lon():
    """ Select random lat/lon within the UK """
    south, east = 50.8520, 0.3536
    north, west = 53.7984, -2.7296

    mul = 10000
    lat = random.randrange(int(south * mul), int(north * mul)) / mul
    lon = random.randrange(int(west * mul), int(east * mul)) / mul

    return lat, lon


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
    return value[len(wd_entity) - 1 :]


def build_dict(hit, lat, lon):
    coords = {"lat": lat, "lon": lon}
    if hit is None:
        return dict(commons_cat=None, missing=True, coords=coords)
    commons_cat = hit["commons_cat"]
    url = commons_cat_start + urllib.parse.quote(commons_cat.replace(" ", "_"))
    return dict(
        commons_cat={"title": commons_cat, "url": url},
        coords=coords,
        admin_level=hit.get("admin_level"),
        wikidata=hit["wikidata"],
    )


def do_lookup(elements, lat, lon):
    try:
        hit = osm_lookup(elements, lat, lon)
    except geocode.wkidata.QueryError as e:
        return {
            "query": e.query,
            "error": e.r.text,
            "query_url": "https://query.wikidata.org/#" + e.query,
        }

    return build_dict(hit, lat, lon)


def get_scotland_code(lat, lon):
    conn = psycopg2.connect(**app.config["DB_PARAMS"])
    cur = conn.cursor()

    point = f"ST_Transform(ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326), 27700)"
    cur.execute(f"select code, name from scotland where st_contains(geom, {point});")
    row = cur.fetchone()

    # expand search, disabled for now 2020-04-20
    if not row:
        cur.execute(
            f"select code, name from scotland where ST_DWithin(geom, {point}, 100);"
        )
        row = cur.fetchone()

    conn.close()
    if row:
        return row[0]


def wdqs_geosearch_query(lat, lon):
    if isinstance(lat, float):
        lat = f"{lat:f}"
    if isinstance(lon, float):
        lon = f"{lon:f}"

    query = render_template("sparql/geosearch.sparql", lat=lat, lon=lon)
    return geocode.wikidata.wdqs(query)


def wdqs_geosearch(lat, lon):
    default_max_dist = 1
    rows = wdqs_geosearch_query(lat, lon)
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


def lat_lon_to_wikidata(lat, lon):
    scotland_code = get_scotland_code(lat, lon)

    if scotland_code:
        rows = lookup_scottish_parish_in_wikidata(scotland_code)
        hit = commons_from_rows(rows)
        elements = []
        result = build_dict(hit, lat, lon)

        return {"elements": elements, "result": result}

    elements = geocode.overpass.get_osm_elements(lat, lon)
    result = do_lookup(elements, lat, lon)

    # special case because the City of London is admin_level=6 in OSM
    if result["wikidata"] == city_of_london_qid:
        return {"elements": elements, "result": result}

    admin_level = result["admin_level"]

    if not admin_level or admin_level >= 7:
        return {"elements": elements, "result": result}

    row = wdqs_geosearch(lat, lon)
    if row:
        hit = commons_from_rows([row])
        elements = []
        result = build_dict(hit, lat, lon)

    return {"elements": elements, "result": result}



def lookup_scottish_parish_in_wikidata(code):
    query = render_template("sparql/scottish_parish.sparql", code=code)
    return geocode.wikidata.wdqs(query)


def lookup_gss_in_wikidata(gss):
    query = render_template("sparql/lookup_gss.sparql", gss=gss)
    return geocode.wikidata.wdqs(query)


def lookup_wikidata_by_name(name, lat, lon):
    query = render_template(
        "sparql/lookup_by_name.sparql", name=repr(name), lat=str(lat), lon=str(lon)
    )
    return geocode.wikidata.wdqs(query)


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


def osm_lookup(elements, lat, lon):
    elements.sort(key=lambda e: bounding_box_area(e))

    for e in elements:
        if "tags" not in e:
            continue
        tags = e["tags"]
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
            commons = geocode.wikidata.qid_to_commons_category(qid)
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
        "commons_cat": geocode.qid_to_commons_category(qid),
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

    elements = geocode.overpass.get_osm_elements(lat, lon)
    result = do_lookup(elements, lat, lon)

    return render_template(
        "detail.html", lat=lat, lon=lon, result=result, elements=elements
    )


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
        elements = geocode.overpass.get_osm_elements(lat, lon)
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
    reply = lat_lon_to_wikidata(lat, lon)
    return render_template("detail.html", lat=lat, lon=lon, **reply)


if __name__ == "__main__":
    app.run(host="0.0.0.0")
