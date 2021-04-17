from flask import current_app
import psycopg2

def get_scotland_code(lat, lon):
    conn = psycopg2.connect(**current_app.config["DB_PARAMS"])
    cur = conn.cursor()

    point = f"ST_Transform(ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326), 27700)"
    cur.execute(f"select code, name from scotland where st_contains(geom, {point});")
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None
