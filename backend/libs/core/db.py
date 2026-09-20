import os

import boto3
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from libs.core.logger import Logger

STAGE = os.getenv("STAGE", "dev")
SSM_DB_PATH = os.getenv("SSM_DB_PATH", f"/cdts/{STAGE}/db")


def _load_db_config() -> dict:
    ssm = boto3.client("ssm")
    resp = ssm.get_parameters_by_path(Path=SSM_DB_PATH, WithDecryption=True)
    return {p["Name"].rsplit("/", 1)[-1]: p["Value"] for p in resp["Parameters"]}


_cfg = _load_db_config()

engine = create_engine(
    url=f"postgresql+pg8000://{_cfg['user']}:{_cfg['password']}@{_cfg['host']}:{_cfg['port']}/{_cfg['name']}",
    pool_pre_ping=True,
    pool_recycle=840,
)


@event.listens_for(engine, "connect")
def _set_search_path(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute(f"SET search_path TO {STAGE}, pg_catalog")
    cur.close()
    # pg8000 runs that SET inside an implicit transaction. The pool rolls back
    # on return, and PostgreSQL undoes a SET issued in a rolled-back
    # transaction, dropping the connection back to the default search_path
    # (pro). Committing pins it for the life of the connection.
    dbapi_conn.commit()


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
