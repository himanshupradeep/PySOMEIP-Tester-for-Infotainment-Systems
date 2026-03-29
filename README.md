# Infotainment SOME/IP Test Automation

> Automated testing of automotive infotainment services over SOME/IP (AUTOSAR) using Python and pytest — no hardware required.

## Tech stack

| Tool | Purpose |
|------|---------|
| `python-can` | CAN bus abstraction (Vector, PCAN, SocketCAN, virtual) |
| `udsoncan` | UDS ISO 14229 diagnostic client over CAN |
| `someipy` | SOME/IP service communication over Automotive Ethernet |
| `pytest` | Test runner with session and function scoped fixtures |
| `pytest-html` | HTML test report generation |
| `UDP sockets` | Transport layer for the simulated ECU (replaces real Automotive Ethernet) |
---

## Why infotainment matters in the SDV era?

The infotainment system is no longer just a screen with a radio. In a software-defined vehicle it is one of the most active software surfaces in the car — receiving over-the-air updates, connecting to cloud services, exchanging diagnostic data with the backend, and acting as the primary human-machine interface for everything from navigation to vehicle settings.

This makes it one of the highest-risk areas to test. A regression in the audio service after an OTA update, a navigation state that does not clear correctly after a route cancellation, or a media player that silently accepts an out-of-range command — none of these cause a crash, but all of them reach the customer. In an SDV context where software drops happen frequently and remotely, automated regression at the service layer is not optional.

---

## Communication architecture

Modern infotainment ECUs communicate using a layered stack that combines multiple protocols depending on the function.

### SOME/IP — Scalable service-Oriented MiddlEwarE over IP

SOME/IP is the AUTOSAR standard for service-to-service communication over Automotive Ethernet. Every function exposed by the infotainment ECU — audio control, media playback, navigation — is a SOME/IP service with a defined Service ID and a set of Method IDs. Clients send requests; services respond. Notifications can be sent without a request (event-driven).

Each SOME/IP message has a fixed 16-byte header:

```
Byte  0–1  : Service ID       0x1001 = Audio Control
Byte  2–3  : Method ID        0x0001 = SET_VOLUME
Byte  4–7  : Length           payload length + 8
Byte  8–9  : Client ID        identifies the calling client
Byte 10–11 : Session ID       increments per request, used to match responses
Byte  12   : Protocol version  always 0x01
Byte  13   : Interface version service interface version
Byte  14   : Message type      0x00=REQUEST  0x80=RESPONSE  0x81=ERROR
Byte  15   : Return code       0x00=E_OK  0x20=E_VALUE_OUT_OF_RANGE
Byte  16+  : Payload
```

### CAN bus — Controller Area Network

CAN is the classical in-vehicle network used for lower-speed signals: sensor readings, body control, climate, basic status broadcasts. The infotainment ECU receives audio volume status, vehicle speed, and door state over CAN. Testing this layer uses `python-can` with a virtual interface in CI and a Vector or PCAN interface in the lab.

### DoIP — Diagnostics over Internet Protocol (ISO 13400)

DoIP carries UDS diagnostic messages over TCP/IP instead of CAN, enabling diagnostic communication over the same Ethernet backbone used for SOME/IP services. This is how the vehicle's head unit is accessed during remote diagnostics, OTA validation, and end-of-line testing.

### UDS / SOVD — Diagnostic services

**UDS (ISO 14229)** defines the diagnostic services the head unit supports — reading software version DIDs, reading fault codes, triggering ECU reset, flashing new software. These run over DoIP on modern infotainment systems.

**SOVD (Service-Oriented Vehicle Diagnostics)** is the next-generation layer above UDS, exposing diagnostic functions as discoverable REST-style endpoints. In an SDV architecture, the cloud backend and remote engineering tools interact with the vehicle's diagnostics through SOVD rather than raw UDS byte sequences.

---

## Services under test

This project tests three SOME/IP services exposed by the infotainment head unit:

| Service | Service ID | Responsibility |
|---------|-----------|----------------|
| Audio Control | `0x1001` | Volume, mute state |
| Media Player | `0x1002` | Playback, track navigation |
| Navigation | `0x1003` | Destination, ETA, route lifecycle |

---

## Project structure

```
automotive_test_demo/
├── services/
│   ├── someip_protocol.py      # SOME/IP header serialiser / deserialiser
│   ├── infotainment_ecu.py     # UDP server simulating the real head unit ECU
│   └── someip_client.py        # Typed Python client: set_volume, media_play, etc.
├── utils/
│   └── can_utils.py            # python-can wrapper (virtual bus for CI, real hw in lab)
├── tests/
│   ├── conftest.py             # ECU session-scoped fixture, client resets per test
│   └── test_infotainment.py
└── requirements.txt
```

The mock ECU is a UDP server that processes SOME/IP requests and maintains internal state. Swapping it for a real head unit means changing the IP address and port. The test cases do not change.

---

## Getting started

**Install dependencies**

```bash
pip install -r requirements.txt
```

**Run all tests**

```bash
pytest tests/ -v
```

**Generate HTML report**

```bash
pytest tests/ -v --html=report.html --self-contained-html
```

---

## Test suite 1 — Audio Control

`ServiceID 0x1001` — SET_VOLUME, GET_VOLUME, SET_MUTE

Audio control is the most used service on any infotainment ECU. These tests cover the full round-trip, the boundary behaviour, and the mute state machine. The boundary test matters in particular because an ECU that silently clamps 101 to 100 instead of rejecting it masks a caller bug and could cause unexpected behaviour on hardware with an amplifier that uses the raw byte value.

### Sequence — volume round-trip and boundary rejection

"C:\Users\himan\Pictures\Screenshots\Screenshot 2026-03-29 164642.png"

```python
def test_tc01_volume_set_and_get(self, client, ecu):
    # Precondition — fixture guarantees volume = 20
    initial = client.get_volume()
    assert initial == 20

    # Action
    confirmed = client.set_volume(75)

    # Verify response payload
    assert confirmed == 75

    # Verify ECU internal state
    assert ecu.state.volume == 75

    # Verify read-back is consistent
    retrieved = client.get_volume()
    assert retrieved == 75
```

**What the SOME/IP log looks like:**

<img width="776" height="362" alt="image" src="https://github.com/user-attachments/assets/c671d1e8-3c5d-4fb9-94fa-1c4ef2c43bb8" />


```
  DEBUG  SOMEIPClient  → svc=0x1001 meth=0x0002 session=1 payload_len=0
  DEBUG  MockECU       REQ svc=0x1001 meth=0x0002 from ('127.0.0.1', 58831)
  DEBUG  SOMEIPClient  ← rc=E_OK  payload=b'\x14'   (volume=20)
  DEBUG  SOMEIPClient  → svc=0x1001 meth=0x0001 session=2 payload_len=1
  INFO   MockECU       Volume set to 75
  DEBUG  SOMEIPClient  ← rc=E_OK  payload=b'\x4b'   (confirmed=75)
  DEBUG  SOMEIPClient  → svc=0x1001 meth=0x0002 session=3 payload_len=0
  DEBUG  SOMEIPClient  ← rc=E_OK  payload=b'\x4b'   (read-back=75)
```

**Boundary value test:**

<img width="755" height="329" alt="image" src="https://github.com/user-attachments/assets/6f05028b-f632-4547-8dba-50ff5ffd5d30" />

```python
def test_tc01_volume_boundary_values(self, client):
    for valid_vol in (0, 50, 100):
        result = client.set_volume(valid_vol)
        assert result == valid_vol

    # Value > 100 must trigger E_VALUE_OUT_OF_RANGE
    with pytest.raises(SOMEIPError) as exc_info:
        client.set_volume(101)

    assert exc_info.value.return_code == ReturnCode.E_VALUE_OUT_OF_RANGE
```

| Test | Validates |
|------|-----------|
| `test_tc01_volume_set_and_get` | Round-trip SET/GET — response, ECU state, and read-back all match |
| `test_tc01_volume_boundary_values` | 0/50/100 accepted; 101 returns E_VALUE_OUT_OF_RANGE |
| `test_tc01_mute_toggle` | SET_MUTE True → False — state machine transitions verified |

---

## Test suite 2 — Media Player

`ServiceID 0x1002` — PLAY, PAUSE, GET_STATUS, NEXT_TRACK

The media player tests cover the playback state machine and the track index wrap-around. The wrap-around is the most commonly missed edge case — implementations that use `track_index + 1` without a modulo silently go out of bounds on the last track.

### Sequence — play, pause, next track with wrap-around

<img width="773" height="591" alt="Screenshot 2026-03-29 164911" src="https://github.com/user-attachments/assets/5e3480e9-949f-43f3-bd6f-2e6cb49500ed" />

```python
def test_tc02_track_advance_and_wrap(self, client, ecu):
    assert ecu.state.track_index == 0

    playlist = ecu.state.tracks
    expected_sequence = [1, 2, 0]    # indices after each NEXT_TRACK

    for expected_index in expected_sequence:
        new_track = client.next_track()
        assert new_track == playlist[expected_index]
        assert ecu.state.track_index == expected_index
```

**What the log looks like for this test:**

<img width="858" height="327" alt="image" src="https://github.com/user-attachments/assets/955b1a13-d9b1-4c87-81b4-ba8970aface6" />

```
  INFO   MockECU  Media: NEXT  track='Artist B - Song 2'   (index 0→1)
  DEBUG  SOMEIPClient  ← rc=E_OK  16.0ms  payload=b'{"track":"Artist B - Song 2"}'
  INFO   MockECU  Media: NEXT  track='Artist C - Song 3'   (index 1→2)
  DEBUG  SOMEIPClient  ← rc=E_OK  0.0ms   payload=b'{"track":"Artist C - Song 3"}'
  INFO   MockECU  Media: NEXT  track='Artist A - Song 1'   (index 2→0 wrap)
  DEBUG  SOMEIPClient  ← rc=E_OK  0.0ms   payload=b'{"track":"Artist A - Song 1"}'
```

> The 16ms latency on the first call is normal — the UDP socket pays its setup cost once. All subsequent calls in the same session are sub-millisecond.

**Play/pause state machine test:**

<img width="1019" height="325" alt="image" src="https://github.com/user-attachments/assets/e484d2d2-e1eb-4a80-9f7a-de8a67f041da" />

```python
def test_tc02_play_pause_state_machine(self, client, ecu):
    # Precondition
    status = client.get_media_status()
    assert status["playing"] is False

    # PLAY
    client.media_play()
    status = client.get_media_status()
    assert status["playing"] is True
    assert ecu.state.media_playing is True

    # PAUSE
    client.media_pause()
    status = client.get_media_status()
    assert status["playing"] is False
    assert ecu.state.media_playing is False
```

| Test | Validates |
|------|-----------|
| `test_tc02_play_pause_state_machine` | PLAY → PAUSE transitions verified with GET_STATUS after each |
| `test_tc02_track_advance_and_wrap` | NEXT_TRACK × 3 — sequence correct, wraps to index 0 |
| `test_tc02_get_status_reflects_track_name` | GET_STATUS payload matches ECU internal track name |

---

## Test suite 3 — Navigation

`ServiceID 0x1003` — SET_DESTINATION, GET_ETA, CANCEL_ROUTE

Navigation is the most stateful of the three services. These tests cover the full route lifecycle, the edge case where a second destination overwrites the first (partial state left over from the previous route is a real ECU bug), and the empty-state query when no route is active.

### Sequence — set destination, overwrite, cancel, verify cleared

<img width="743" height="662" alt="Screenshot 2026-03-29 165104" src="https://github.com/user-attachments/assets/36615596-f166-42d1-bbc1-1f5854312681" />

```python
def test_tc03_set_destination_and_query_eta(self, client, ecu):
    # Precondition
    assert not ecu.state.route_active
    assert ecu.state.destination == ""

    destination  = "BMW Welt, Munich"
    eta_expected = 25

    # SET_DESTINATION
    result = client.set_destination(destination, eta_minutes=eta_expected)
    assert result["status"] == "route_calculated"
    assert result["eta_minutes"] == eta_expected
    assert ecu.state.route_active is True

    # GET_ETA
    eta_info = client.get_eta()
    assert eta_info["route_active"]  is True
    assert eta_info["destination"]   == destination
    assert eta_info["eta_minutes"]   == eta_expected

    # CANCEL_ROUTE
    cancel_result = client.cancel_route()
    assert cancel_result["status"] == "route_cancelled"
    assert ecu.state.route_active  is False
    assert ecu.state.destination   == ""
```
<img width="1269" height="324" alt="image" src="https://github.com/user-attachments/assets/0af86878-c48b-46e0-83fb-fa580166aeda" />

**Route overwrite test — verifies no stale state:**

```python
def test_tc03_route_overwrite(self, client, ecu):
    client.set_destination("Porsche Museum, Stuttgart", eta_minutes=40)
    assert ecu.state.destination == "Porsche Museum, Stuttgart"

    # Overwrite completely
    client.set_destination("Nurburgring, Nurburg", eta_minutes=90)
    assert ecu.state.destination  == "Nurburgring, Nurburg"
    assert ecu.state.eta_minutes  == 90
    assert ecu.state.route_active is True

    eta_info = client.get_eta()
    assert eta_info["destination"] == "Nurburgring, Nurburg"
```
<img width="1028" height="327" alt="image" src="https://github.com/user-attachments/assets/39bb03e2-b60d-4018-b006-b2fa29154532" />

**No-route edge case:**

```python
def test_tc03_get_eta_without_active_route(self, client, ecu):
    assert not ecu.state.route_active

    eta_info = client.get_eta()
    assert eta_info["route_active"] is False
    assert eta_info["destination"]  == ""
    assert eta_info["eta_minutes"]  == 0
```
<img width="1223" height="311" alt="image" src="https://github.com/user-attachments/assets/30e7dfe1-6dfa-4b37-bb6b-7b20ed2b2ce0" />

| Test | Validates |
|------|-----------|
| `test_tc03_set_destination_and_query_eta` | Full lifecycle: set → GET_ETA → cancel → state cleared |
| `test_tc03_route_overwrite` | Second destination fully replaces first — no stale state |
| `test_tc03_get_eta_without_active_route` | GET_ETA with no active route returns correct empty state |

---

## How this connects to real hardware

The mock ECU is a UDP server on `127.0.0.1:30490` (SOME/IP default port). To test against a real head unit, replace the IP address and port in the client:

```python
# Simulated (this project)
with SOMEIPClient(host="127.0.0.1", port=30490) as client:
    confirmed = client.set_volume(75)
```

```python
# Real hardware — head unit on Automotive Ethernet
with SOMEIPClient(host="192.168.1.10", port=30490) as client:
    confirmed = client.set_volume(75)
```

For a production setup with `someipy` (AUTOSAR SOME/IP library):

```python
import someipy
from someipy import ServiceDiscovery

# Discover the Audio Control service via SOME/IP SD
sd = ServiceDiscovery()
audio_service = sd.find_service(service_id=0x1001)

# Call SET_VOLUME on the discovered service
response = audio_service.call_method(
    method_id=0x0001,
    payload=bytes([75])
)
```

For CAN signals alongside SOME/IP (python-can):

```python
import can

# Virtual bus for CI — swap to 'vector' or 'socketcan' for real hardware
bus = can.Bus(interface="virtual", channel="test_channel")

# Listen for audio status broadcast on CAN ID 0x210
msg = bus.recv(timeout=1.0)
if msg and msg.arbitration_id == 0x210:
    volume = msg.data[0]
    muted  = bool(msg.data[1])
```

---

## Test results

<img width="919" height="494" alt="Screenshot 2026-03-29 165956" src="https://github.com/user-attachments/assets/192e8f45-2ff6-4dd6-9423-1a9b572aefb3" />

```
============================== 9 passed in 0.61s ==============================
```

---

END OF REPORT
