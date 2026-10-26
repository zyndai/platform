"""The one line each search logs has to reach stderr, and nothing that holds the search text may."""
import logging

import pytest

from app import log_setup


@pytest.fixture
def clean_loggers():
    log = logging.getLogger(log_setup.FIND_PEOPLE_LOGGER)
    before = (log.level, list(log.handlers))
    log.handlers.clear()
    yield log
    log.handlers[:] = before[1]
    log.setLevel(before[0])


def test_the_find_people_logger_emits_info_with_a_handler(clean_loggers):
    log_setup.configure()
    assert clean_loggers.isEnabledFor(logging.INFO) and len(clean_loggers.handlers) == 1


def test_configuring_twice_does_not_print_every_line_twice(clean_loggers):
    log_setup.configure()
    log_setup.configure()
    assert len(clean_loggers.handlers) == 1


def test_httpx_and_the_root_logger_stay_quiet(clean_loggers):
    """httpx logs each request URL at INFO and the URL holds the search text."""
    root_before = logging.getLogger().level
    log_setup.configure()
    assert logging.getLogger().level == root_before
    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
    assert not logging.getLogger("zynd.oauth").isEnabledFor(logging.INFO)
