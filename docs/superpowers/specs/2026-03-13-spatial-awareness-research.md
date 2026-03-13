# Spatial Awareness & Deictic Perception — Research Summary

**Date:** 2026-03-13
**Status:** Research / Pre-design
**Depends on:** Multi-role composition (feat/multi-role-composition), perception primitives, actuation layer

---

## 1. Problem Statement

The perception layer handles WHEN (temporal: beats, bars, timeline, suppression ramps) but has no treatment of WHERE. Spatial reference in natural language is almost always **deictic** — words like "here", "there", "this", "that" derive meaning entirely from context. The system cannot resolve these references.

### Motivating Examples

| Utterance | Required context | Precision level |
|-----------|-----------------|-----------------|
| "Is my wife on her way?" | Operator location, wife's location, trajectory between them, pragmatics of "on her way" | City/route scale |
| "Should I put this monitor here or there?" | What "this" is (monitor), where "here" and "there" are (room positions) | Room scale |
| "Should I put this here or there?" (at desk, holding instrument + mouse, looking at screen) | Object in each hand, gaze direction, what "here"/"there" refer to on the desk/screen | Surface/pixel scale |
| "Put this here" (dragging a window) | Gaze target, cursor position, active window | Pixel scale |
| "Put this here" (holding a monitor) | Object being held, spatial position being indicated | Room scale |

**Key insight:** The precision level is determined by the action verb and physical context, not the spatial word. Same utterance, wildly different resolution requirements.

---

## 2. Sensor Inventory

### Currently Integrated
- **BRIO webcam** — operator face (presence detection, emotion)
- **C920 webcam** — hardware view
- **IR camera** — experimental
- **Desktop mic** — PipeWire audio input (VAD, energy, wake word)
- **Screen capture** — Hyprland workspace state
- **MIDI clock** — temporal perception

### Available but Undeployed
| Asset | Count | Capabilities | Status |
|-------|-------|-------------|--------|
| **Webcams** (total) | 4 | Video + audio each | 2 integrated, 2 available |
| **Raspberry Pi 4** | 4 | Compute, GPIO, USB, WiFi, BT | Sitting in a corner. Clean slate. |
| **Pixel 10** (operator) | 1 | GPS, UWB, accelerometer, gyro, proximity, ambient light, barometer, camera, mic | Daily carry |
| **Pixel 8a** (wife) | 1 | GPS, accelerometer, camera, mic | Daily carry |
| **Pixel Watch** (operator) | 1 | HR, HRV, activity recognition, sleep stages, accelerometer | Daily wear |
| **Pixel Buds** (operator) | 1 | Mic (head-mounted), audio output, proximity | Available |

### Unexplored API/Platform Space
- **Google Health Connect** — watch biometrics (HR, HRV, sleep stages, activity) via Android API
- **Google Location Sharing / Geofencing API** — real-time location, ETA
- **Android Activity Recognition API** — in-vehicle, walking, running, still (no custom ML)
- **UWB (Pixel 10)** — sub-meter indoor ranging to other UWB devices
- **Tasker → MQTT** — phone state events published to home network, zero custom app code
- **Digital Wellbeing / Usage Stats API** — app usage context
- **Nearby Devices API** — BLE/UWB device proximity

---

## 3. Architecture Gap

### Current Model
```
PerceptionBackend (local hardware) → Behavior → Governance
```

### Required Model
```
Distributed sensors (Pis, phones, watch, buds)
  → Transport (MQTT)
    → Ingestion layer (new PerceptionBackend: MQTTBackend)
      → SpatialModel (who is where, doing what, moving how)
        → Behavior[SpatialFrame] → Governance
```

### Missing Infrastructure
1. **MQTT broker** — Mosquitto on workstation (single apt install)
2. **Pi sensor firmware** — minimal publishers: PIR + mic + env sensors → MQTT topics
3. **Phone bridge** — Tasker → MQTT for location, activity, phone state
4. **MQTTBackend** — new PerceptionBackend subscribing to MQTT topics, updating Behaviors
5. **SpatialFrame** — hierarchical spatial decomposition analogous to MusicalPosition

### Proposed SpatialFrame Primitive
```python
@dataclass(frozen=True)
class SpatialFrame:
    room: str            # "studio" | "office" | "living_room" | "unknown"
    station: str         # "desk" | "standing" | "couch" | "mobile"
    focus_surface: str   # "screen_left" | "mixer" | "guitar" | "unknown"
    gaze_target: str     # what the operator is attending to
    hands: tuple[str, str]  # what each hand is doing/holding
    confidence: float    # [0, 1] — how sure are we about any of this
```

### Precision Cascade
"Here" resolves differently at each level:
1. **Room** — Pi PIR + audio → which room (easy, high confidence)
2. **Station** — Pi audio + desk camera → position within room (medium)
3. **Surface** — webcam + gaze estimation → what surface is in focus (hard)
4. **Point** — gaze + pointing estimation → specific location on surface (very hard)

The system should report its confidence level and degrade gracefully. "I know you're in the studio but I can't tell what you're pointing at" is better than guessing.

---

## 4. Hardest Perception Problems

### "What am I holding?" + "What am I pointing at?"
Requires:
- Hand detection + pose estimation (MediaPipe Hands — runs on-device, GPU)
- Object recognition in hand (YOLO-class detection, custom-trained for studio objects)
- Gaze/pointing direction estimation (head pose + hand vector)
- Scene understanding (what exists at the indicated point)

**Feasibility:** The webcams can physically provide the input. MediaPipe + YOLO gets ~70% accuracy. The last 30% (disambiguating similar objects, understanding pointing semantics in context) is genuinely hard and may require iterative prototyping.

**Recommended approach:** Prototype hand + object detection on desktop GPU first. If accuracy is sufficient, deploy to Pis as edge inference nodes.

### "Is my wife on her way?"
Requires:
- Her GPS location (phone API or location sharing)
- Operator's location (known — home)
- Route/trajectory inference (Google Maps Directions API)
- Pragmatics: "on her way" = moving toward home, not just "not home"

**Feasibility:** High, given phone GPS access. Tasker + MQTT can publish coarse location without a custom app. Google Maps API provides ETA.

**Critical dependency:** Requires consent framework (see §5).

---

## 5. Governance Prerequisite: Interpersonal Transparency

**This section identifies a governance gap that MUST be resolved before building the distributed sensor mesh.**

### The Problem
The sensor inventory includes devices that belong to or track other people (wife's phone). The current axiom set has no constraints on modeling non-operator persons:
- `single_user` assumes all data is the operator's own
- `su-privacy-001` explicitly says "Privacy controls, data anonymization, and consent mechanisms are unnecessary since the user is also the developer"
- No axiom addresses what happens when the system models someone who is NOT the operator

### Proposed New Axiom: `interpersonal_transparency`
Two core principles identified through discussion:
1. **(a) Opt-in** — the system must not model, track, or infer state about any non-operator person without their explicit, recorded, revocable consent
2. **(b) Mutual transparency** — what the system knows about a person, that person can inspect. No asymmetric surveillance.

### Proposed New Concept: Consent Contract
A **contract** is a runtime artifact that the axiom requires before certain data flows are permitted. The axiom is the lock; the contract is the key. A contract has:
- **Parties**: operator + subject
- **Scope**: what data (location? presence? biometrics? coarse "home/away" only?)
- **Direction**: one-way or bidirectional
- **Visibility**: what the subject can inspect
- **Revocation**: either party can revoke at any time → system immediately stops modeling + purges
- **Record**: timestamped, auditable, stored alongside axiom precedents

### Key Distinction: Environmental vs. Personal
The threshold for requiring a contract: **any persistent state the system maintains about a specific non-operator person.**
- Environmental sensing (VAD detects someone speaking in the room) = no contract needed
- Personal modeling ("wife is 10 minutes away", "wife is home") = contract required

### Tension with `su-privacy-001`
The existing implication `su-privacy-001` ("Privacy controls and consent mechanisms are unnecessary") applies to the **operator's own data**. A new axiom about non-operator persons doesn't contradict it — it adds a constraint for a case `single_user` never contemplated (the system modeling people who are not the single user).

This is addressed in full in the axiom evaluation (separate document, pending).

---

## 6. Infrastructure Deployment Plan (Pending Governance)

Blocked until the interpersonal_transparency axiom is ratified. When unblocked:

### Phase A: MQTT Backbone
1. Install Mosquitto on workstation
2. Create MQTTBackend (new PerceptionBackend)
3. Define topic schema: `hapax/room/{room_id}/presence`, `hapax/person/{id}/location`, etc.

### Phase B: Pi Room Sensors
1. Flash Pis with minimal OS (Raspberry Pi OS Lite)
2. Attach PIR + mic (or mic array for direction)
3. Deploy MQTT publisher service
4. One Pi per room (studio, office, living room, bedroom)

### Phase C: Phone Integration
1. Tasker on operator's Pixel 10 → MQTT (location, activity, phone state)
2. **After consent contract with wife:** Tasker on her Pixel 8a → MQTT (coarse location only, per contract scope)
3. Watch biometrics via Health Connect → Tasker → MQTT

### Phase D: Spatial Perception
1. Implement SpatialFrame primitive
2. Room-level perception from Pis
3. Station-level from desk cameras
4. Prototype hand/object detection on GPU

---

## 7. Open Questions

1. **Axiom weight and scope:** Is interpersonal_transparency constitutional or domain-scoped? What weight relative to the existing four?
2. **Contract storage:** Where do contracts live? Alongside axiom precedents? In their own registry?
3. **Contract UI:** How does a non-operator inspect what the system knows? A web interface? A shared document?
4. **Degradation:** What happens when a contract is revoked mid-session? How quickly does the system purge?
5. **Pi networking:** Static IPs? mDNS? How do Pis discover the MQTT broker?
6. **Edge vs. central inference:** Hand/object detection on Pi (limited) vs. desktop GPU (powerful but centralized)?
7. **UWB ranging:** Pixel 10 supports it — is there a UWB tag we could place to enable sub-meter indoor positioning without cameras?
