"""Logging that uvicorn does not set up.

uvicorn configures only its own loggers, so an INFO line from the app never reaches stderr (the root
logger stays at WARNING): the one line each search logs was silent in prod and dev. Only that
logger is turned on. Root INFO would also print httpx's request URLs, and those carry the search text.
"""
import logging

FIND_PEOPLE_LOGGER = "zynd.find_people"


def configure() -> None:
    log = logging.getLogger(FIND_PEOPLE_LOGGER)
    log.setLevel(logging.INFO)
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        log.addHandler(handler)
