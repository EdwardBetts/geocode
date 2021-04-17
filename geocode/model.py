from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.schema import Column
from sqlalchemy.types import Integer, Float, Numeric, String
from sqlalchemy.dialects import postgresql
from geoalchemy2 import Geometry
from .database import session

Base = declarative_base()
Base.query = session.query_property()

class Polygon(Base):
    __tablename__ = "planet_osm_polygon"

    osm_id = Column(Integer, primary_key=True, autoincrement=False)

    way_area = Column(Float)
    tags = Column(postgresql.HSTORE)
    way = Column(Geometry("GEOMETRY", srid=4326, spatial_index=True), nullable=False)

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

