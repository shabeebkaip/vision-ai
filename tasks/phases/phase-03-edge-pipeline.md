## Phase 3 — Edge pipeline (weeks 2 to 10)

About 46 developer-days (LD, CV, BE). This is the software that runs at the customer site: it reads cameras, finds people and objects, applies the customer's rules, and sends events with a snapshot and a short clip to the cloud. It starts as a 2-day throwaway prototype (EDG-01) that proves the whole loop, then gets rebuilt as proper services. Everything here runs in Docker and is tested on the fake cameras from REP-05 and the clips from Phase 2.

**Edge data flow:** camera → go2rtc → frame sampler (5 to 10 fps) → detector → tracker → zones and lines → rules engine → event + snapshot + clip → local outbox → cloud.

**MVP rule types (EDG-09)**

| Rule type | Fires when | Example |
| --- | --- | --- |
| `zone_occupancy_over` | More than N people in a zone for at least T seconds | Crowd at the pharmacy counter |
| `zone_empty` | Nobody in a zone for at least T minutes during scheduled hours | Cashier or reception desk unattended |
| `queue_length_over` | Queue zone holds more than N people; also reports estimated wait from dwell | Open a second till |
| `dwell_over` | Any one person or vehicle stays in a zone longer than T | Loitering, truck waiting at dock |
| `line_crossing` | Count of crossings in a direction exceeds N in a period, or any crossing into a restricted side | Entry counting, restricted door |
| `presence_after_hours` | Any person detected in a zone outside the schedule | Night intrusion, staff after closing |

Every rule has: camera, zone or line, threshold, minimum duration, schedule (days and hours, Asia/Riyadh time), cooldown, severity (info, warning, critical), minimum confidence, and a clear-down condition so one situation produces one alert, not fifty.

| ID | Task | Owner | Days | Pri | Needs | Done when |
| --- | --- | --- | --- | --- | --- | --- |
| EDG-01 | Throwaway prototype, one script: read a file or RTSP stream with OpenCV, sample 5 fps, detect people with RF-DETR Nano on CPU, track with Supervision ByteTrack, count people in one polygon, fire when more than 3 for 30 s, send snapshot to Telegram | LD | 2 | Must | SET-07 | The queue clip alerts and the empty-counter clip does not; shown in week 2 demo |
| EDG-02 | Frame source service: `FileSource` and `RtspSource` behind one interface; target fps sampling; wall-clock timestamp per frame; reconnect with exponential backoff (1 s to 60 s); stalled-stream detection (no frame for 10 s); per-camera health (online, real fps, resolution, codec, last frame time) | LD | 3 | Must | REP-04 | Unplugging a fake camera for 2 minutes and back recovers with no restart; health shows the gap |
| EDG-03 | go2rtc as the camera front door: generate its config from `CameraConfig`, one connection per camera, local restream for inference, JPEG snapshot endpoint for the zone editor | LD | 1 | Must | EDG-02 | Each camera opens exactly one session on the NVR |
| EDG-04 | Camera discovery: ONVIF WS-Discovery scan, `GetProfiles` / `GetStreamUri`, fallback URL templates for Hikvision, Dahua, Uniview, Axis and Hanwha NVRs and cameras, credential test, sub-stream selection, report of resolution and codec per channel | BE | 3 | Should | EDG-02 | Office NVR channels discovered automatically with working sub-stream URLs |
| EDG-05 | Inference worker: `Detector` interface with three backends (PyTorch CPU for development, ONNX Runtime CPU/GPU, TensorRT on Jetson); batches frames from all cameras; letterbox resize; class and confidence filtering; latency measured per batch | CV | 4 | Must | REP-04 | Same clip gives the same detections (within tolerance) on all three backends |
| EDG-06 | Model packaging on the edge: model file plus manifest (name, version, classes, input size, checksum, licence); hot-swap a model without restarting the pipeline; refuse a model whose checksum fails | CV | 1.5 | Must | EDG-05 | Swapping person-v1 for person-v2 mid-run drops no frames beyond 2 s |
| EDG-07 | Tracking: Supervision ByteTrack per camera, track lifecycle (new, active, lost, removed), per-camera tuning of thresholds, optional motion gating so inference is skipped on still frames | CV | 2 | Must | EDG-05 | Person IDs stay stable through a 3-second occlusion on the test clips |
| EDG-08 | Zones and lines: polygons and lines stored in normalised 0–1 coordinates and scaled per camera; anchor point per class (bottom-centre for people, centre for objects); several zones per camera; zone membership and time-in-zone per track | LD | 1.5 | Must | EDG-07 | Unit tests cover edge-of-zone and crossing-back cases |
| EDG-09 | Rules engine: plugin interface `evaluate(state, now) → Event \| None`; the six MVP rule types above; schedules, cooldowns, severity, hysteresis (armed → triggered → cleared); rules loaded from site config and reloaded live | LD | 6 | Must | EDG-08 | Each rule type has unit tests plus at least 3 positive and 3 negative test clips passing |
| EDG-10 | Counters and aggregates: per camera per minute occupancy, entries and exits, queue length average and maximum, average dwell; stored locally and uploaded in batches every 5 minutes for reports and footfall | LD | 2 | Must | EDG-09 | One hour of office footage produces a correct per-minute footfall table |
| EDG-11 | Clip and snapshot service: rolling 30-second buffer per camera kept as encoded 2-second segments in RAM disk (no re-encoding while idle); on event, cut 5 s before to 5 s after into an MP4 (H.264, 720p); snapshot JPEG with boxes and zone drawn | LD | 3 | Must | EDG-03, EDG-09 | Event clip starts before the trigger and plays in WhatsApp and in a browser |
| EDG-12 | Event uploader with outbox: events queued in local SQLite, uploaded with snapshot and clip through pre-signed URLs, idempotency key per event, retries with backoff, ordered delivery; offline mode keeps events for 7 days and clips up to a disk quota (oldest clips dropped first, events never) | BE | 3 | Must | CLD-05 | Pulling the internet for 2 hours then restoring delivers every event once, in order |
| EDG-13 | Edge agent: enrolment with a one-time token; heartbeat every 60 s (CPU, GPU, temperature, RAM, disk, per-camera status, software and model versions); pulls site config and rules (ETag polling every 60 s) and applies without restart; reports applied config version; downloads new models; uploads recent logs on request | BE | 4 | Must | CLD-04 | Changing a rule in the cloud takes effect on the box within 2 minutes |
| EDG-14 | Watchdog and self-protection: Docker restart policies, health endpoint per service, disk guard (delete oldest clips above 80% use), thermal guard (lower fps above 80 °C), camera-down event after 5 minutes offline | DO | 2 | Must | EDG-13 | Killing any service restarts it within 30 s and logs why |
| EDG-15 | Installer page on the box (LAN only, password protected): camera list with snapshots, zones drawn, live counts, health; used by the field engineer during setup | FE | 2 | Should | EDG-03 | Field engineer verifies a site without cloud access |
| EDG-16 | Performance budget and profiling: time per stage (decode, detect, track, rules, encode); targets 8 cameras at 5 fps on Orin Nano, 16 on Orin NX, 24 on RTX 4060; profiling report in `docs/` | CV | 2 | Must | EDG-05, HW-02 | Report shows measured cameras-per-box for each hardware tier |
| EDG-17 | Time sync: chrony/NTP on the box; all event times from the box clock, never the camera clock | DO | 0.5 | Must |  | Event times match wall clock within 1 s |
| EDG-18 | Offline-only mode: the box can run entirely from a local `site.yaml` with no cloud (for hospitals and government), events kept on box and visible on the installer page | LD | 1 | Should | EDG-13, EDG-15 | Box runs a full day with the network cable to the internet removed |
| EDG-19 | Privacy guards in code: no face crops or face embeddings anywhere; snapshots on the box deleted after 24 h; clips only for triggered events; site flag "events only, no clips" for sensitive sites | LD | 1 | Must | EDG-11 | Code review checklist item; test proves the flag stops clip upload |

---
Full plan: [docs/development-task-plan.md](../../docs/development-task-plan.md) · All tasks as CSV: [tasks/tasks.csv](../tasks.csv)
