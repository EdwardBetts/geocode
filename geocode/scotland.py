"""Reverse geocode civil parishes in Scotland."""

from sqlalchemy import func

from geocode.database import session
from geocode.model import Scotland


def get_scotland_code(lat: float, lon: float) -> str | None:
    """Find civil parish in Scotland for given lat/lon."""
    point = func.ST_Transform(func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326), 27700)
    result = (
        session.query(Scotland.code)
        .filter(func.ST_Contains(Scotland.geom, point))
        .first()
    )
    return result[0] if result else None
