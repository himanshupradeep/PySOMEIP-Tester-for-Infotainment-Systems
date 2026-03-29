"""
CAN Bus Utilities — python-can wrapper
=======================================
Demonstrates python-can usage for automotive testing.

Physical interfaces supported by python-can:
  • Vector (CANalyzer / CANcase)   interface='vector'
  • PEAK PCAN                       interface='pcan'
  • SocketCAN (Linux)               interface='socketcan'
  • Kvaser                          interface='kvaser'
  • Virtual (for unit tests)        interface='virtual'  ← used here

In CI/CD or on a developer machine without hardware, 'virtual' creates an
in-process loopback bus that is indistinguishable from real CAN in the API.
"""

import logging
import time
from typing import Generator

try:
    import can
    CAN_AVAILABLE = True
except ImportError:
    CAN_AVAILABLE = False
    can = None

log = logging.getLogger("CANUtils")


# ── Standard Automotive CAN IDs (example subset) ──────────────────────────────
class CANId:
    # Infotainment cluster
    AUDIO_STATUS        = 0x210   # ECU → display unit: current volume/mute
    MEDIA_STATUS        = 0x211   # ECU → display unit: track info
    NAV_STATUS          = 0x212   # ECU → display unit: ETA / turn instruction

    # Diagnostic
    UDS_REQUEST         = 0x7DF   # Tester → ECU  (ISO 15765-2)
    UDS_RESPONSE_BASE   = 0x7E8   # ECU → Tester  (physical addressing offset)


def create_virtual_bus(channel: str = "test_channel") -> "can.Bus | None":
    """
    Opens a virtual CAN bus for testing.
    Returns None (gracefully) if python-can is not installed.
    """
    if not CAN_AVAILABLE:
        log.warning("python-can not installed — CAN features disabled")
        return None
    bus = can.Bus(channel=channel, interface="virtual")
    log.info("Virtual CAN bus opened on channel '%s'", channel)
    return bus


def send_can_frame(bus, arb_id: int, data: bytes, extended: bool = False):
    """
    Send a single CAN frame.

    Parameters
    ----------
    bus      : can.Bus instance
    arb_id   : 11-bit (standard) or 29-bit (extended) arbitration ID
    data     : up to 8 bytes payload
    extended : True for 29-bit extended frame
    """
    if not CAN_AVAILABLE or bus is None:
        log.debug("CAN stub: id=0x%03X  data=%s", arb_id, data.hex())
        return

    msg = can.Message(
        arbitration_id   = arb_id,
        data             = data,
        is_extended_id   = extended,
        is_fd            = False,
    )
    bus.send(msg)
    log.debug("CAN TX: id=0x%03X  data=%s", arb_id, data.hex())


def receive_can_frame(bus, timeout: float = 1.0) -> "can.Message | None":
    """
    Block until a CAN frame arrives or the timeout expires.
    Returns None on timeout.
    """
    if not CAN_AVAILABLE or bus is None:
        return None
    return bus.recv(timeout=timeout)


def listen_for_id(
    bus,
    target_id: int,
    count: int = 1,
    timeout: float = 2.0,
) -> list:
    """
    Collect `count` frames matching `target_id` within `timeout` seconds.
    Useful for verifying that an ECU broadcasts expected CAN signals.
    """
    frames = []
    deadline = time.monotonic() + timeout
    while len(frames) < count and time.monotonic() < deadline:
        msg = receive_can_frame(bus, timeout=max(0, deadline - time.monotonic()))
        if msg and msg.arbitration_id == target_id:
            frames.append(msg)
    return frames


# ── CAN signal encoder / decoder (big-endian Motorola) ────────────────────────
def encode_signal(value: int, start_bit: int, length: int, data: bytearray) -> bytearray:
    """Pack an integer signal into a CAN frame byte array (Motorola byte order)."""
    for i in range(length):
        bit_pos  = start_bit - i
        byte_idx = bit_pos // 8
        bit_idx  = bit_pos %  8
        if (value >> (length - 1 - i)) & 1:
            data[byte_idx] |= (1 << bit_idx)
        else:
            data[byte_idx] &= ~(1 << bit_idx)
    return data


def decode_signal(start_bit: int, length: int, data: bytes) -> int:
    """Extract an integer signal from a CAN frame (Motorola byte order)."""
    value = 0
    for i in range(length):
        bit_pos  = start_bit - i
        byte_idx = bit_pos // 8
        bit_idx  = bit_pos %  8
        if (data[byte_idx] >> bit_idx) & 1:
            value |= (1 << (length - 1 - i))
    return value
