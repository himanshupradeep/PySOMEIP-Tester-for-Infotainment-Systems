"""
Infotainment SOME/IP Test Suite
================================
Three test cases covering the core Infotainment ECU services:

  TC_01  Audio Control   — volume & mute via SOME/IP
  TC_02  Media Playback  — play/pause/next-track state machine
  TC_03  Navigation      — set destination, query ETA, cancel route

Each test follows the standard automotive test pattern:
  1. Precondition  — verify system is in a known state
  2. Action        — send SOME/IP request(s) to the ECU
  3. Verification  — assert response payload and ECU internal state
  4. Postcondition — handled by the 'client' fixture reset in conftest.py

Why no Selenium/Playwright?
  Those tools drive web browsers.  Automotive ECU communication is at the
  network / transport layer (UDP/TCP for SOME/IP, CAN for diagnostics).
  The correct stack here is: python-can → isotp → udsoncan (UDS) for
  diagnostics, and someipy / raw sockets for SOME/IP service calls.
"""

import struct
import pytest
from services.someip_protocol import ReturnCode
from services.someip_client import SOMEIPClient, SOMEIPError


# ═══════════════════════════════════════════════════════════════════════════════
# TC_01  AUDIO CONTROL SERVICE
# ═══════════════════════════════════════════════════════════════════════════════

class TestAudioControl:
    """
    Verifies the Audio Control SOME/IP service (ServiceID 0x1001).

    Requirements covered
    --------------------
    REQ-AUDIO-001: ECU shall accept SET_VOLUME requests in range [0..100]
    REQ-AUDIO-002: ECU shall reject SET_VOLUME values outside [0..100]
    REQ-AUDIO-003: ECU shall toggle mute state on SET_MUTE request
    """

    def test_tc01_volume_set_and_get(self, client: SOMEIPClient, ecu):
        """
        TC_01_A  Volume round-trip
        --------------------------
        Precondition : Volume = 20 (fixture default)
        Action       : SET_VOLUME = 75
        Verify       : GET_VOLUME returns 75 && ECU internal state = 75
        """
        # ── Precondition ──────────────────────────────────────────────────────
        initial = client.get_volume()
        assert initial == 20, f"Precondition failed: expected volume=20, got {initial}"

        # ── Action ────────────────────────────────────────────────────────────
        confirmed = client.set_volume(75)

        # ── Verify response payload ────────────────────────────────────────────
        assert confirmed == 75, f"SET_VOLUME response mismatch: {confirmed}"

        # ── Verify ECU state (direct state read — only possible in simulated env)
        assert ecu.state.volume == 75, "ECU internal state not updated"

        # ── Verify GET_VOLUME is consistent ───────────────────────────────────
        retrieved = client.get_volume()
        assert retrieved == 75, f"GET_VOLUME returned {retrieved}, expected 75"

    def test_tc01_volume_boundary_values(self, client: SOMEIPClient):
        """
        TC_01_B  Volume boundary / equivalence partitioning
        ----------------------------------------------------
        Tests: 0 (min), 100 (max), 50 (mid), 101 (out-of-range → error)
        """
        for valid_vol in (0, 50, 100):
            result = client.set_volume(valid_vol)
            assert result == valid_vol, f"Boundary value {valid_vol} failed"

        # Values > 100 must trigger E_VALUE_OUT_OF_RANGE
        with pytest.raises(SOMEIPError) as exc_info:
            client.set_volume(101)

        assert exc_info.value.return_code == ReturnCode.E_VALUE_OUT_OF_RANGE, (
            f"Expected E_VALUE_OUT_OF_RANGE, got {exc_info.value.return_code.name}"
        )

    def test_tc01_mute_toggle(self, client: SOMEIPClient, ecu):
        """
        TC_01_C  Mute / un-mute state machine
        ----------------------------------------
        Precondition : muted = False
        Step 1       : SET_MUTE True  → verify response + ECU state
        Step 2       : SET_MUTE False → verify response + ECU state
        """
        assert not ecu.state.muted, "Precondition: muted must be False"

        # Mute ON
        state = client.set_mute(True)
        assert state is True,           "SET_MUTE(True) response incorrect"
        assert ecu.state.muted is True, "ECU mute state not set"

        # Mute OFF
        state = client.set_mute(False)
        assert state is False,            "SET_MUTE(False) response incorrect"
        assert ecu.state.muted is False,  "ECU mute state not cleared"


# ═══════════════════════════════════════════════════════════════════════════════
# TC_02  MEDIA PLAYER SERVICE
# ═══════════════════════════════════════════════════════════════════════════════

class TestMediaPlayer:
    """
    Verifies the Media Player SOME/IP service (ServiceID 0x1002).

    Requirements covered
    --------------------
    REQ-MEDIA-001: ECU shall transition to PLAYING state on PLAY request
    REQ-MEDIA-002: ECU shall transition to PAUSED state on PAUSE request
    REQ-MEDIA-003: ECU shall advance track index on NEXT_TRACK and wrap around
    """

    def test_tc02_play_pause_state_machine(self, client: SOMEIPClient, ecu):
        """
        TC_02_A  Play / Pause transitions
        -----------------------------------
        Precondition : media_playing = False
        Step 1       : PLAY  → status.playing == True
        Step 2       : PAUSE → status.playing == False
        """
        # ── Precondition ──────────────────────────────────────────────────────
        status = client.get_media_status()
        assert status["playing"] is False, "Precondition: media should be paused"

        # ── PLAY ──────────────────────────────────────────────────────────────
        client.media_play()
        status = client.get_media_status()
        assert status["playing"] is True,      "Media did not transition to PLAYING"
        assert ecu.state.media_playing is True, "ECU state not PLAYING"

        # ── PAUSE ─────────────────────────────────────────────────────────────
        client.media_pause()
        status = client.get_media_status()
        assert status["playing"] is False,      "Media did not transition to PAUSED"
        assert ecu.state.media_playing is False, "ECU state not PAUSED"

    def test_tc02_track_advance_and_wrap(self, client: SOMEIPClient, ecu):
        """
        TC_02_B  Next-track sequencing & wrap-around
        -----------------------------------------------
        Precondition : track_index = 0  (3 tracks in playlist)
        Action       : NEXT_TRACK × 3
        Verify       : sequence matches playlist order, wraps to index 0
        """
        assert ecu.state.track_index == 0, "Precondition: track_index must be 0"

        playlist = ecu.state.tracks                 # reference to ECU playlist
        expected_sequence = [1, 2, 0]               # indices after each NEXT_TRACK

        for expected_index in expected_sequence:
            new_track = client.next_track()
            assert new_track == playlist[expected_index], (
                f"Expected track '{playlist[expected_index]}', got '{new_track}'"
            )
            assert ecu.state.track_index == expected_index

    def test_tc02_get_status_reflects_track_name(self, client: SOMEIPClient, ecu):
        """
        TC_02_C  GET_STATUS payload integrity
        ----------------------------------------
        Verify that GET_STATUS returns the correct track name matching ECU state.
        """
        status = client.get_media_status()

        assert "playing" in status, "Response missing 'playing' field"
        assert "track"   in status, "Response missing 'track' field"
        assert status["track"] == ecu.state.tracks[ecu.state.track_index]


# ═══════════════════════════════════════════════════════════════════════════════
# TC_03  NAVIGATION SERVICE
# ═══════════════════════════════════════════════════════════════════════════════

class TestNavigation:
    """
    Verifies the Navigation SOME/IP service (ServiceID 0x1003).

    Requirements covered
    --------------------
    REQ-NAV-001: ECU shall accept a destination string and return route_calculated
    REQ-NAV-002: ECU shall persist ETA and return it via GET_ETA
    REQ-NAV-003: ECU shall clear the route on CANCEL_ROUTE
    """

    def test_tc03_set_destination_and_query_eta(self, client: SOMEIPClient, ecu):
        """
        TC_03_A  Full navigation flow: set → query → cancel
        -------------------------------------------------------
        Precondition : route_active = False, destination = ""
        Step 1       : SET_DESTINATION "BMW Welt, Munich" ETA=25
        Step 2       : GET_ETA  → verify destination + eta_minutes
        Step 3       : CANCEL_ROUTE → verify route cleared
        """
        # ── Precondition ──────────────────────────────────────────────────────
        assert not ecu.state.route_active, "Precondition: no active route"
        assert ecu.state.destination == "", "Precondition: destination empty"

        destination = "BMW Welt, Munich"
        eta_expected = 25

        # ── SET_DESTINATION ───────────────────────────────────────────────────
        result = client.set_destination(destination, eta_minutes=eta_expected)
        assert result["status"] == "route_calculated", (
            f"Unexpected status: {result['status']}"
        )
        assert result["eta_minutes"] == eta_expected
        assert ecu.state.route_active is True
        assert ecu.state.destination == destination

        # ── GET_ETA ───────────────────────────────────────────────────────────
        eta_info = client.get_eta()
        assert eta_info["route_active"]                        is True
        assert eta_info["destination"]                         == destination
        assert eta_info["eta_minutes"]                         == eta_expected

        # ── CANCEL_ROUTE ──────────────────────────────────────────────────────
        cancel_result = client.cancel_route()
        assert cancel_result["status"] == "route_cancelled"
        assert ecu.state.route_active  is False
        assert ecu.state.destination   == ""

    def test_tc03_route_overwrite(self, client: SOMEIPClient, ecu):
        """
        TC_03_B  Overwriting an active route with a new destination
        ---------------------------------------------------------------
        Verify that setting a second destination replaces the first.
        """
        client.set_destination("Porsche Museum, Stuttgart", eta_minutes=40)
        assert ecu.state.destination == "Porsche Museum, Stuttgart"

        # Overwrite with a new destination
        client.set_destination("Nürburgring, Nürburg", eta_minutes=90)
        assert ecu.state.destination  == "Nürburgring, Nürburg"
        assert ecu.state.eta_minutes  == 90
        assert ecu.state.route_active is True

        eta_info = client.get_eta()
        assert eta_info["destination"] == "Nürburgring, Nürburg"

    def test_tc03_get_eta_without_active_route(self, client: SOMEIPClient, ecu):
        """
        TC_03_C  GET_ETA when no route is active
        -------------------------------------------
        Verify the ECU returns route_active=False and empty destination.
        """
        assert not ecu.state.route_active  # fixture default

        eta_info = client.get_eta()
        assert eta_info["route_active"]  is False
        assert eta_info["destination"]   == ""
        assert eta_info["eta_minutes"]   == 0
