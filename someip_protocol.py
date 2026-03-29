"""
SOME/IP Protocol Implementation (AUTOSAR SOME/IP Spec R22-11)
Simulates SOME/IP messaging over UDP without real hardware.

SOME/IP Header Structure (16 bytes):
  [0:2]  Service ID       - identifies the service (e.g., Infotainment Audio)
  [2:4]  Method ID        - identifies the method/event
  [4:8]  Length           - payload length + 8 (for remaining header bytes)
  [8:10] Client ID        - identifies the calling client
  [10:12] Session ID      - monotonically increasing per client/service pair
  [12]   Protocol Version - always 0x01
  [13]   Interface Version- service interface version
  [14]   Message Type     - REQUEST, RESPONSE, NOTIFICATION, etc.
  [15]   Return Code      - E_OK, E_NOT_OK, etc.
"""

import struct
from enum import IntEnum


# ── Service IDs ────────────────────────────────────────────────────────────────
class ServiceID(IntEnum):
    AUDIO_CONTROL   = 0x1001   # Volume, mute, audio source
    MEDIA_PLAYER    = 0x1002   # Play, pause, next, prev
    NAVIGATION      = 0x1003   # Destination, route, guidance
    CLIMATE_CONTROL = 0x1004   # Temperature, fan speed


# ── Method IDs per service ─────────────────────────────────────────────────────
class AudioMethod(IntEnum):
    SET_VOLUME      = 0x0001
    GET_VOLUME      = 0x0002
    SET_MUTE        = 0x0003
    GET_MUTE        = 0x0004

class MediaMethod(IntEnum):
    PLAY            = 0x0001
    PAUSE           = 0x0002
    GET_STATUS      = 0x0003
    NEXT_TRACK      = 0x0004

class NavMethod(IntEnum):
    SET_DESTINATION = 0x0001
    GET_ETA         = 0x0002
    CANCEL_ROUTE    = 0x0003


# ── Message Types (SOME/IP spec Table 4.4) ─────────────────────────────────────
class MessageType(IntEnum):
    REQUEST             = 0x00   # Client → Server, expects response
    REQUEST_NO_RETURN   = 0x01   # Fire-and-forget
    NOTIFICATION        = 0x02   # Server → Client event
    RESPONSE            = 0x80   # Server → Client response
    ERROR               = 0x81   # Server → Client error response


# ── Return Codes (SOME/IP spec Table 4.7) ──────────────────────────────────────
class ReturnCode(IntEnum):
    E_OK                    = 0x00
    E_NOT_OK                = 0x01
    E_UNKNOWN_SERVICE       = 0x02
    E_UNKNOWN_METHOD        = 0x03
    E_NOT_READY             = 0x04
    E_NOT_REACHABLE         = 0x05
    E_TIMEOUT               = 0x06
    E_VALUE_OUT_OF_RANGE    = 0x20


SOMEIP_HEADER_FORMAT = "!HHIHHBBBB"   # network byte order
SOMEIP_HEADER_SIZE   = 16


def build_someip_message(
    service_id: int,
    method_id: int,
    payload: bytes,
    client_id: int = 0x0001,
    session_id: int = 0x0001,
    message_type: MessageType = MessageType.REQUEST,
    return_code: ReturnCode = ReturnCode.E_OK,
    interface_version: int = 0x01,
) -> bytes:
    """
    Serialises a SOME/IP message to bytes.

    Length field = len(payload) + 8  (covers client_id … return_code = 8 bytes)
    """
    length = len(payload) + 8
    header = struct.pack(
        SOMEIP_HEADER_FORMAT,
        service_id,
        method_id,
        length,
        client_id,
        session_id,
        0x01,               # Protocol version (always 1)
        interface_version,
        int(message_type),
        int(return_code),
    )
    return header + payload


def parse_someip_message(raw: bytes) -> dict:
    """
    Deserialises raw bytes into a SOME/IP message dict.
    Raises ValueError on malformed messages.
    """
    if len(raw) < SOMEIP_HEADER_SIZE:
        raise ValueError(f"Message too short: {len(raw)} bytes (min {SOMEIP_HEADER_SIZE})")

    (
        service_id,
        method_id,
        length,
        client_id,
        session_id,
        proto_version,
        iface_version,
        msg_type,
        ret_code,
    ) = struct.unpack(SOMEIP_HEADER_FORMAT, raw[:SOMEIP_HEADER_SIZE])

    payload_len = length - 8
    payload = raw[SOMEIP_HEADER_SIZE: SOMEIP_HEADER_SIZE + payload_len]

    return {
        "service_id":        service_id,
        "method_id":         method_id,
        "length":            length,
        "client_id":         client_id,
        "session_id":        session_id,
        "protocol_version":  proto_version,
        "interface_version": iface_version,
        "message_type":      MessageType(msg_type),
        "return_code":       ReturnCode(ret_code),
        "payload":           payload,
    }
