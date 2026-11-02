# ADR 001: Process video on an edge box at the customer site

Status: accepted (2 Nov 2026)

**Decision.** Detection, tracking and rules run on a small box on the customer's network. Only
events, snapshots and short clips go to the cloud.

**Why.** A 720p sub-stream is 0.5–1.5 Mbps; 16 cameras need 8–24 Mbps of upload around the clock,
which most Saudi sites do not have. Camera networks are usually isolated VLANs; one outbound HTTPS
connection is acceptable to customer IT, an open NVR is not. Raw video never leaving the building
is the simplest answer to PDPL and the camera law. A cloud GPU to decode 16 streams costs more per
month than the box costs once.

**Consequences.** We need fleet management (enrolment, remote updates, health) from day one, and the
code must run on Jetson (arm64, Python 3.10) as well as x86 + NVIDIA.
