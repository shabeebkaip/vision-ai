# ADR 007: Our own ByteTrack-style tracker

Status: accepted (2 Nov 2026)

**Decision.** Tracking uses `edge/src/vision_edge/tracking.py`: a constant-velocity Kalman filter per
track, two-stage IoU association (high-confidence detections first, then low-confidence ones against
recently seen tracks), Hungarian matching with class gating, as described in the ByteTrack paper.

**Why.** `supervision` 0.31 removed `sv.ByteTrack`. Its replacement, Roboflow's `trackers`
(Apache-2.0), depends on the non-headless `opencv-python` build, which needs desktop libraries that
edge boxes do not have and conflicts with `opencv-python-headless`. Our tracker is about 200 lines,
needs only numpy and scipy, and is covered by unit tests and the video harness.

**Revisit when** we need re-identification across long occlusions (queues behind shelving), or if
`trackers` drops the non-headless OpenCV requirement; BoT-SORT with camera-motion compensation is
the candidate.
