import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from libs.core.logger import Logger

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
STAGE = os.getenv("STAGE", "dev")

engine = create_engine(
    url=f"postgresql+pg8000://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}",
    pool_pre_ping=True,
    pool_recycle=840,
)


@event.listens_for(engine, "connect")
def _set_search_path(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute(f"SET search_path TO {STAGE}, pg_catalog")
    cur.close()


Session = sessionmaker(bind=engine)


class DBSession:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.session = Session()
            Logger.log("INFO", "Session created")
        return cls._instance

    def commit(self):
        self.session.commit()

    def rollback(self):
        self.session.rollback()

    def close(self):
        self.session.close()


db_session = DBSession()
