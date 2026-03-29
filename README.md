# Automotive SOME/IP Test Automation Demo
## Python · python-can · udsoncan · pytest

A self-contained demo that simulates an **Infotainment ECU** communicating via
**SOME/IP over UDP** and tests it with **three pytest test suites**.
No real hardware required — runs entirely in software.

---

## Why NOT Selenium / Playwright / ROS?

| Tool | Intended for | Why not here |
|------|-------------|--------------|
| Selenium / Playwright | Web browser automation (HTML/DOM) | ECU APIs are not web browsers |
| ROS | Robot Operating System (actuators, sensors) | Not used in automotive ECUs |
| **python-can** | **CAN bus (all interfaces)** | ✅ Correct layer for diagnostics |
| **udsoncan** | **UDS ISO 14229 over CAN** | ✅ Correct for ECU diagnostics |
| **SOME/IP sockets** | **Automotive Ethernet middleware** | ✅ Correct for service calls |

---

## Architecture

```
┌─────────────────────────────────────┐
│          pytest test suite          │
│  TC_01 Audio  TC_02 Media  TC_03 Nav│
└──────────────┬──────────────────────┘
               │  SOMEIPClient (UDP)
               ▼
┌─────────────────────────────────────┐
│      Mock Infotainment ECU          │
│  ┌───────────┐ ┌──────┐ ┌────────┐ │
│  │AudioControl│ │Media │ │  Nav  │ │
│  └───────────┘ └──────┘ └────────┘ │
│         InfotainmentState           │
└─────────────────────────────────────┘

Real project: replace Mock ECU with physical ECU via:
  • python-can → Vector / PCAN / SocketCAN hardware
  • udsoncan   → UDS ISO 14229 diagnostics over CAN
  • someipy    → SOME/IP over DoIP (Ethernet)
```

---

## Project Structure

```
automotive_test_demo/
├── services/
│   ├── someip_protocol.py   # SOME/IP header serialiser/deserialiser
│   ├── infotainment_ecu.py  # Mock ECU UDP server (replaces real hardware)
│   └── someip_client.py     # High-level test client
├── utils/
│   └── can_utils.py         # python-can wrapper (virtual bus for CI)
├── tests/
│   ├── conftest.py          # pytest fixtures (ECU lifecycle + client reset)
│   └── test_infotainment.py # 3 test classes × 3 sub-cases = 9 test cases
├── requirements.txt
└── README.md
```

---

## Test Cases

### TC_01 · Audio Control (ServiceID `0x1001`)

| Sub-case | Covers |
|----------|--------|
| `test_tc01_volume_set_and_get` | Round-trip SET_VOLUME / GET_VOLUME |
| `test_tc01_volume_boundary_values` | Equivalence partitioning 0/50/100/101 |
| `test_tc01_mute_toggle` | SET_MUTE state machine (True → False) |

### TC_02 · Media Player (ServiceID `0x1002`)

| Sub-case | Covers |
|----------|--------|
| `test_tc02_play_pause_state_machine` | PLAY → PAUSE transitions |
| `test_tc02_track_advance_and_wrap` | NEXT_TRACK × 3, wrap-around check |
| `test_tc02_get_status_reflects_track_name` | GET_STATUS payload integrity |

### TC_03 · Navigation (ServiceID `0x1003`)

| Sub-case | Covers |
|----------|--------|
| `test_tc03_set_destination_and_query_eta` | Full flow: set → GET_ETA → cancel |
| `test_tc03_route_overwrite` | Overwriting an active route |
| `test_tc03_get_eta_without_active_route` | ETA query when no route is active |

---

## Running

```bash
pip install -r requirements.txt

# Run all tests with verbose output
pytest tests/ -v

# Generate HTML report (great for sharing with team)
pytest tests/ -v --html=report.html --self-contained-html

# Run a single test class
pytest tests/ -v -k "TestNavigation"
```

---

## Key Concepts for the Interview

### SOME/IP Message Structure (AUTOSAR)
```
Byte  0-1  : Service ID   (e.g., 0x1001 = Audio Control)
Byte  2-3  : Method  ID   (e.g., 0x0001 = SET_VOLUME)
Byte  4-7  : Length       (payload_len + 8)
Byte  8-9  : Client  ID
Byte 10-11 : Session ID   (increments per request, used for matching responses)
Byte 12    : Protocol Version = 0x01
Byte 13    : Interface Version
Byte 14    : Message Type  (0x00=REQUEST, 0x80=RESPONSE, 0x81=ERROR)
Byte 15    : Return Code   (0x00=E_OK, 0x20=E_VALUE_OUT_OF_RANGE …)
Byte 16+   : Payload
```

### python-can (real hardware)
```python
import can

# Connect to a Vector CANalyzer interface (real lab setup)
bus = can.Bus(interface='vector', channel=0, bitrate=500_000)

# Or use virtual bus for CI/CD (no hardware needed)
bus = can.Bus(interface='virtual', channel='test')

msg = can.Message(arbitration_id=0x7DF, data=[0x02, 0x10, 0x03])
bus.send(msg)
response = bus.recv(timeout=1.0)
```

### udsoncan (UDS diagnostics)
```python
import udsoncan
from udsoncan.connections import PythonIsoTpConnection
from udsoncan.client import Client

conn   = PythonIsoTpConnection(bus, rxid=0x7E8, txid=0x7DF)
config = {"exception_on_negative_response": True}

with Client(conn, config=config) as client:
    client.change_session(udsoncan.services.DiagnosticSessionControl.Session.extendedDiagnosticSession)
    response = client.read_data_by_identifier(0xF190)  # Read VIN
```
