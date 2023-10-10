from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.schema import Column
from sqlalchemy.types import Integer, Float, Numeric, String
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import column_property
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import func, cast

from geoalchemy2 import Geometry
from .database import session

Base = declarative_base()
Base.query = session.query_property()

class Polygon(Base):
    __tablename__ = "planet_osm_polygon"

    osm_id = Column(Integer, primary_key=True, autoincrement=False)
    admin_level = Column(String)

    way_area = Column(Float)
    tags = Column(postgresql.HSTORE)
    way = Column(Geometry("GEOMETRY", srid=4326, spatial_index=True), nullable=False)
    area = column_property(func.ST_Area(way, False))

    @property
    def osm_url(self):
        osm_type = "way" if self.osm_id > 0 else "relation"
        return f"https://www.openstreetmap.org/{osm_type}/{abs(self.osm_id)}"

    @hybrid_property
    def area_in_sq_km(self):
        return self.area / (1000 * 1000)

    @classmethod
    def coords_within(cls, lat, lon):
        point = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
        return (cls.query.filter(cls.admin_level.isnot(None),
                                 cls.admin_level.regexp_match("^\d+$"),
                                 func.ST_Within(point, cls.way))
                         .order_by(cls.area, cast(cls.admin_level, Integer).desc()))

class Scotland(Base):
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

