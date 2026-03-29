"""
SOME/IP Client
==============
High-level helper used by test cases to send requests to the Infotainment ECU
and receive typed responses.

In a real project this would sit on top of:
  • python-can  – for CAN/CAN-FD physical layer
  • udsoncan    – for UDS diagnostics over CAN (ISO 14229)
  • vsomeip/someipy – for production SOME/IP over Ethernet (DoIP)

Here we use raw UDP to keep the demo self-contained and hardware-free.
"""

import json
import logging
import socket
import struct
import time

from services.someip_protocol import (
    MessageType,
    ReturnCode,
    build_someip_message,
    parse_someip_message,
)

log = logging.getLogger("SOMEIPClient")


class SOMEIPError(Exception):
    """Raised when the ECU returns a non-E_OK return code."""
    def __init__(self, return_code: ReturnCode):
        self.return_code = return_code
        super().__init__(f"ECU returned error: {return_code.name} (0x{return_code:02X})")


class SOMEIPClient:
    """
    Thin UDP client that serialises / deserialises SOME/IP frames.

    Usage
    -----
    client = SOMEIPClient()
    client.connect()
    response = client.request(ServiceID.AUDIO_CONTROL, AudioMethod.SET_VOLUME, payload=b'\x50')
    client.disconnect()

    Or use as a context manager:
    with SOMEIPClient() as client:
        ...
    """

    DEFAULT_TIMEOUT = 2.0   # seconds

    def __init__(self, host: str = "127.0.0.1", port: int = 30490, client_id: int = 0x0042):
        self.host       = host
        self.port       = port
        self.client_id  = client_id
        self._sock      = None
        self._session   = 0

    # ── Connection ─────────────────────────────────────────────────────────────
    def connect(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(self.DEFAULT_TIMEOUT)
        log.info("SOMEIPClient ready → %s:%d", self.host, self.port)

    def disconnect(self):
        if self._sock:
            self._sock.close()
            self._sock = None
        log.info("SOMEIPClient disconnected")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()

    # ── Core request/response ──────────────────────────────────────────────────
    def request(
        self,
        service_id: int,
        method_id: int,
        payload: bytes = b"",
        timeout: float | None = None,
    ) -> dict:
        """
        Send a REQUEST and block until a RESPONSE (or ERROR) is received.

        Returns the parsed response dict.
        Raises SOMEIPError if the ECU returns a non-E_OK code.
        Raises socket.timeout if no response within `timeout` seconds.
        """
        self._session = (self._session % 0xFFFF) + 1

        raw = build_someip_message(
            service_id   = service_id,
            method_id    = method_id,
            payload      = payload,
            client_id    = self.client_id,
            session_id   = self._session,
            message_type = MessageType.REQUEST,
        )

        if timeout:
            self._sock.settimeout(timeout)

        start = time.monotonic()
        self._sock.sendto(raw, (self.host, self.port))
        log.debug("→ svc=0x%04X meth=0x%04X session=%d payload_len=%d",
                  service_id, method_id, self._session, len(payload))

        # Wait for matching response (same service + method + session)
        while True:
            data, _ = self._sock.recvfrom(4096)
            resp = parse_someip_message(data)
            if (
                resp["service_id"] == service_id
                and resp["method_id"] == method_id
                and resp["session_id"] == self._session
            ):
                elapsed = (time.monotonic() - start) * 1000
                log.debug("← rc=%s  %.1f ms", resp["return_code"].name, elapsed)

                if resp["return_code"] != ReturnCode.E_OK:
                    raise SOMEIPError(resp["return_code"])

                return resp

    # ── Typed convenience methods ──────────────────────────────────────────────
    def set_volume(self, volume: int) -> int:
        """Set audio volume (0-100). Returns confirmed volume."""
        payload  = struct.pack("!B", volume)
        resp     = self.request(0x1001, 0x0001, payload)   # AUDIO / SET_VOLUME
        (confirmed,) = struct.unpack("!B", resp["payload"])
        return confirmed

    def get_volume(self) -> int:
        """Return current audio volume."""
        resp = self.request(0x1001, 0x0002)                # AUDIO / GET_VOLUME
        (vol,) = struct.unpack("!B", resp["payload"])
        return vol

    def set_mute(self, mute: bool) -> bool:
        """Mute or un-mute the audio output."""
        payload = struct.pack("!?", mute)
        resp    = self.request(0x1001, 0x0003, payload)    # AUDIO / SET_MUTE
        (state,) = struct.unpack("!?", resp["payload"])
        return bool(state)

    def media_play(self):
        """Start media playback."""
        self.request(0x1002, 0x0001)                       # MEDIA / PLAY

    def media_pause(self):
        """Pause media playback."""
        self.request(0x1002, 0x0002)                       # MEDIA / PAUSE

    def get_media_status(self) -> dict:
        """Return {'playing': bool, 'track': str}."""
        resp = self.request(0x1002, 0x0003)                # MEDIA / GET_STATUS
        return json.loads(resp["payload"].decode())

    def next_track(self) -> str:
        """Skip to the next track; return new track name."""
        resp = self.request(0x1002, 0x0004)                # MEDIA / NEXT_TRACK
        return json.loads(resp["payload"].decode())["track"]

    def set_destination(self, destination: str, eta_minutes: int = 30) -> dict:
        """Set navigation destination. Returns route confirmation."""
        payload = json.dumps({"destination": destination, "eta_minutes": eta_minutes}).encode()
        resp    = self.request(0x1003, 0x0001, payload)    # NAV / SET_DESTINATION
        return json.loads(resp["payload"].decode())

    def get_eta(self) -> dict:
        """Return current navigation ETA information."""
        resp = self.request(0x1003, 0x0002)                # NAV / GET_ETA
        return json.loads(resp["payload"].decode())

    def cancel_route(self) -> dict:
        """Cancel the active navigation route."""
        resp = self.request(0x1003, 0x0003)                # NAV / CANCEL_ROUTE
        return json.loads(resp["payload"].decode())
