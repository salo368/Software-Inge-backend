import json
import traceback
from functools import wraps

from libs.core.db import db_session
from libs.core.logger import Logger


def generate_response(body=None, status_code=200):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body or {}, default=str),
    }


class HandledError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def handle_exceptions(func):
    @wraps(func)
    def wrapper(event, context):
        try:
            response = func(event, context)
            db_session.commit()
            return response
        except HandledError as e:
            db_session.rollback()
            Logger.log("WARNING", f"{func.__name__}: {e.message}")
            return generate_response({"error": e.message}, e.status_code)
        except Exception as e:
            db_session.rollback()
            Logger.log("ERROR", f"{func.__name__}: {e}\n{traceback.format_exc()}")
            return generate_response({"error": "internal_server_error"}, 500)
        finally:
            # The session is a module-level singleton that outlives the
            # invocation on a warm container. Without this the transaction
            # stays open and later invocations keep reading the same snapshot,
            # missing rows another service committed in the meantime.
            db_session.close()
    return wrapper
