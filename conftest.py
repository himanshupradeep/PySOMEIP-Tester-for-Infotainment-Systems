"""
conftest.py — shared pytest fixtures
=====================================
pytest automatically discovers this file and makes fixtures available
to every test module in the same directory.

Fixture scope:
  'session'  → created once per test run   (ECU server)
  'function' → created fresh per test case (client connection)

This mirrors real automotive test setups where:
  • The DUT (Device Under Test / ECU) stays powered the entire session
  • Each test case gets a clean communication channel
"""

import logging
import time

import pytest

from services.infotainment_ecu import InfotainmentECU
from services.someip_client import SOMEIPClient

# Turn on debug logging so interview reviewers can follow the SOME/IP frames
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)


@pytest.fixture(scope="session")
def ecu():
    """
    Start the mock Infotainment ECU once for the entire test session.
    Yields the ECU instance so individual tests can inspect ECU state.
    Tears down after all tests complete.
    """
    server = InfotainmentECU()
    server.start()
    time.sleep(0.05)   # give the UDP socket a moment to bind
    yield server
    server.stop()


@pytest.fixture
def client(ecu):   # depends on 'ecu' so ECU is always up first
    """
    Open a fresh SOME/IP client connection for each test.
    Resets ECU state before the test so tests are independent.
    """
    # Reset ECU to known defaults before every test
    ecu.state.volume        = 20
    ecu.state.muted         = False
    ecu.state.media_playing = False
    ecu.state.track_index   = 0
    ecu.state.destination   = ""
    ecu.state.eta_minutes   = 0
    ecu.state.route_active  = False

    with SOMEIPClient() as c:
        yield c
