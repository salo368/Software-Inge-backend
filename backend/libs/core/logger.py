import logging
import os

_logger = logging.getLogger()
_logger.setLevel(logging.INFO)


class Logger:
    @staticmethod
    def log(level: str, message):
        getattr(_logger, level.lower(), _logger.info)(message)
