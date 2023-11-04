"""Database model."""

import sqlalchemy
import sqlalchemy.orm.query
from geoalchemy2 import Geometry
from sqlalchemy import and_, cast, func, or_
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import column_property
from sqlalchemy.schema import Column
from sqlalchemy.types import Float, Integer, Numeric, String

from .database import session

Base = declarative_base()
Base.query = session.query_property()


class Polygon(Base):
    """Polygon."""

    __tablename__ = "planet_osm_polygon"

    osm_id = Column(Integer, primary_key=True, autoincrement=False)
    admin_level = Column(String)
    boundary = Column(String)

    way_area = Column(Float)
    tags = Column(postgresql.HSTORE)
    way = Column(Geometry("GEOMETRY", srid=4326, spatial_index=True), nullable=False)
    area = column_property(func.ST_Area(way, False))
    geojson_str = column_property(
        func.ST_AsGeoJSON(way, maxdecimaldigits=6), deferred=True
    )

    @property
    def osm_url(self) -> str:
        """OSM URL for polygon."""
        osm_type = "way" if self.osm_id > 0 else "relation"
        return f"https://www.openstreetmap.org/{osm_type}/{abs(self.osm_id)}"

    @hybrid_property
    def area_in_sq_km(self) -> float:
        """Area in square kilometers."""
        return float(self.area) / (1000 * 1000)

    @classmethod
    def coords_within(
        cls, lat: str | float, lon: str | float
    ) -> sqlalchemy.orm.query.Query:  # type: ignore
        """Polygons that contain given coordinates."""
        point = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
        q = cls.query.filter(
            or_(
                cls.boundary == "political",
                cls.boundary == "place",
                and_(
                    cls.admin_level.isnot(None),  # type: ignore
                    cls.admin_level.regexp_match(r"^\d+$"),  # type: ignore
                ),
            ),
            func.ST_Within(point, cls.way),
        ).order_by(cls.area, cast(cls.admin_level, Integer).desc())
        return q  # type: ignore


class Scotland(Base):
    """Civil parishes in Scotland."""

    __tablename__ = "scotland"

    gid = Column(Integer, primary_key=True)
    shape_leng = Column(Numeric)
    shape_area = Column(Numeric)
    code = Column(String(3))
    c91code1 = Column(String(5))
    c91code2 = Column(String(5))
    c91code3 = Column(String(5))
    c91code4 = Column(String(5))
    name = Column(String(50))

    geom = Column(Geometry("MULTIPOLYGON", srid=27700))
