"""
Mock Infotainment ECU — SOME/IP Service Provider
=================================================
Simulates an automotive Head Unit ECU exposing three SOME/IP services:
  • Audio Control  (ServiceID 0x1001)
  • Media Player   (ServiceID 0x1002)
  • Navigation     (ServiceID 0x1003)

Runs as a UDP server in a background thread.
Real projects would replace this with a connection to a physical ECU
via python-can, a Vector CANalyzer interface, or a HIL rig.
"""

import json
import logging
import socket
import struct
import threading
from dataclasses import dataclass, field

from services.someip_protocol import (
    MessageType,
    ReturnCode,
    ServiceID,
    AudioMethod,
    MediaMethod,
    NavMethod,
    build_someip_message,
    parse_someip_message,
)

log = logging.getLogger("MockECU")


# ── Internal ECU state ─────────────────────────────────────────────────────────
@dataclass
class InfotainmentState:
    # Audio
    volume: int = 20          # 0-100
    muted: bool = False

    # Media
    media_playing: bool = False
    track_index: int = 0
    tracks: list = field(default_factory=lambda: [
        "Artist A - Song 1",
        "Artist B - Song 2",
        "Artist C - Song 3",
    ])

    # Navigation
    destination: str = ""
    eta_minutes: int = 0
    route_active: bool = False


class InfotainmentECU:
    """
    Lightweight UDP server that speaks SOME/IP.
    Spawn with  ecu = InfotainmentECU(); ecu.start()
    Stop  with  ecu.stop()
    """

    HOST = "127.0.0.1"
    PORT = 30490   # SOME/IP default port (AUTOSAR)

    def __init__(self):
        self.state   = InfotainmentState()
        self._sock   = None
        self._thread = None
        self._stop   = threading.Event()

    # ── Lifecycle ──────────────────────────────────────────────────────────────
    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.HOST, self.PORT))
        self._sock.settimeout(0.5)
        self._stop.clear()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        log.info("InfotainmentECU listening on %s:%d", self.HOST, self.PORT)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._sock:
            self._sock.close()
        log.info("InfotainmentECU stopped")

    # ── Request dispatcher ─────────────────────────────────────────────────────
    def _serve(self):
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(4096)
            except socket.timeout:
                continue

            try:
                msg = parse_someip_message(data)
            except ValueError as exc:
                log.warning("Malformed SOME/IP message: %s", exc)
                continue

            log.debug(
                "REQ svc=0x%04X meth=0x%04X from %s",
                msg["service_id"], msg["method_id"], addr,
            )

            response = self._dispatch(msg)
            if response:
                self._sock.sendto(response, addr)

    def _dispatch(self, msg: dict) -> bytes | None:
        svc  = msg["service_id"]
        meth = msg["method_id"]
        payload_in = msg["payload"]

        handlers = {
            ServiceID.AUDIO_CONTROL: self._handle_audio,
            ServiceID.MEDIA_PLAYER:  self._handle_media,
            ServiceID.NAVIGATION:    self._handle_navigation,
        }

        handler = handlers.get(svc)
        if handler is None:
            return self._error_response(msg, ReturnCode.E_UNKNOWN_SERVICE)

        return handler(msg, meth, payload_in)

    # ── Audio service ──────────────────────────────────────────────────────────
    def _handle_audio(self, msg, method_id, payload):
        if method_id == AudioMethod.SET_VOLUME:
            (volume,) = struct.unpack("!B", payload[:1])
            if not 0 <= volume <= 100:
                return self._error_response(msg, ReturnCode.E_VALUE_OUT_OF_RANGE)
            self.state.volume = volume
            log.info("Volume set to %d", volume)
            return self._ok_response(msg, struct.pack("!B", volume))

        elif method_id == AudioMethod.GET_VOLUME:
            return self._ok_response(msg, struct.pack("!B", self.state.volume))

        elif method_id == AudioMethod.SET_MUTE:
            (mute,) = struct.unpack("!?", payload[:1])
            self.state.muted = bool(mute)
            log.info("Mute set to %s", self.state.muted)
            return self._ok_response(msg, struct.pack("!?", self.state.muted))

        elif method_id == AudioMethod.GET_MUTE:
            return self._ok_response(msg, struct.pack("!?", self.state.muted))

        return self._error_response(msg, ReturnCode.E_UNKNOWN_METHOD)

    # ── Media service ──────────────────────────────────────────────────────────
    def _handle_media(self, msg, method_id, payload):
        if method_id == MediaMethod.PLAY:
            self.state.media_playing = True
            log.info("Media: PLAY  track='%s'", self.state.tracks[self.state.track_index])
            return self._ok_response(msg, b"\x01")

        elif method_id == MediaMethod.PAUSE:
            self.state.media_playing = False
            log.info("Media: PAUSE")
            return self._ok_response(msg, b"\x00")

        elif method_id == MediaMethod.GET_STATUS:
            status = {
                "playing": self.state.media_playing,
                "track":   self.state.tracks[self.state.track_index],
            }
            encoded = json.dumps(status).encode()
            return self._ok_response(msg, encoded)

        elif method_id == MediaMethod.NEXT_TRACK:
            self.state.track_index = (self.state.track_index + 1) % len(self.state.tracks)
            log.info("Media: NEXT  track='%s'", self.state.tracks[self.state.track_index])
            return self._ok_response(msg, json.dumps({"track": self.state.tracks[self.state.track_index]}).encode())

        return self._error_response(msg, ReturnCode.E_UNKNOWN_METHOD)

    # ── Navigation service ────────────────────────────────────────────────────
    def _handle_navigation(self, msg, method_id, payload):
        if method_id == NavMethod.SET_DESTINATION:
            dest_data = json.loads(payload.decode())
            self.state.destination  = dest_data["destination"]
            self.state.eta_minutes  = dest_data.get("eta_minutes", 30)
            self.state.route_active = True
            log.info("Navigation: destination='%s' ETA=%d min", self.state.destination, self.state.eta_minutes)
            return self._ok_response(msg, json.dumps({"status": "route_calculated", "eta_minutes": self.state.eta_minutes}).encode())

        elif method_id == NavMethod.GET_ETA:
            result = {"destination": self.state.destination, "eta_minutes": self.state.eta_minutes, "route_active": self.state.route_active}
            return self._ok_response(msg, json.dumps(result).encode())

        elif method_id == NavMethod.CANCEL_ROUTE:
            self.state.route_active = False
            self.state.destination  = ""
            self.state.eta_minutes  = 0
            log.info("Navigation: route cancelled")
            return self._ok_response(msg, json.dumps({"status": "route_cancelled"}).encode())

        return self._error_response(msg, ReturnCode.E_UNKNOWN_METHOD)

    # ── Response helpers ───────────────────────────────────────────────────────
    def _ok_response(self, req: dict, payload: bytes) -> bytes:
        return build_someip_message(
            service_id    = req["service_id"],
            method_id     = req["method_id"],
            payload       = payload,
            client_id     = req["client_id"],
            session_id    = req["session_id"],
            message_type  = MessageType.RESPONSE,
            return_code   = ReturnCode.E_OK,
        )

    def _error_response(self, req: dict, code: ReturnCode) -> bytes:
        return build_someip_message(
            service_id    = req["service_id"],
            method_id     = req["method_id"],
            payload       = b"",
            client_id     = req["client_id"],
            session_id    = req["session_id"],
            message_type  = MessageType.ERROR,
            return_code   = code,
        )
