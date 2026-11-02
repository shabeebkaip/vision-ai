## Phase 8 — Edge packaging and hardware (weeks 10 to 16)

About 21 developer-days (DO, CV, BE, FLD). Up to week 10 everything runs on laptops and fake cameras. Hardware is bought only now, once the pipeline is stable, and only two boxes. The aim of this phase: a box arrives at a site, is plugged in, the installer scans a QR code, and the box is live within an hour, can be updated and supported remotely, and never needs a technician to log in at the site again.

**Hardware tiers we support (from the product plan)**

| Tier | Box | Target cameras | Landed cost (approx.) |
| --- | --- | --- | --- |
| S | Jetson Orin Nano Super 8 GB | up to 8 | SAR 2,500 |
| M | Jetson Orin NX 16 GB (e.g. Seeed reComputer J4012) | 16 to 24 | SAR 4,600 |
| M-alt | Mini-PC with RTX 4060 | 20 to 30 | SAR 6,600 |
| L | Workstation with RTX 4090 | 60 to 100 | SAR 25,000 |

| ID | Task | Owner | Days | Pri | Needs | Done when |
| --- | --- | --- | --- | --- | --- | --- |
| HW-01 | Buy the development kit (week 10): 1 Orin Nano Super, 1 Orin NX box, NVMe SSDs, a small PoE switch, a 4G router with data SIM, 2 small UPS units. Order lead time 2 to 3 weeks | PO | 0.5 | Must | EDG-09 | Kit received in the Riyadh office |
| HW-02 | Benchmark each tier with the real pipeline (EDG-16): cameras per box at 5 and 10 fps with the MVP model and with the V1 models; publish the official camera limit per tier | CV | 2 | Must | HW-01 | Table in `docs/hardware.md`; plan limits in CLD-18 match it |
| HW-03 | Edge operating system build, scripted with Ansible for both Jetson (JetPack 6) and x86 + NVIDIA (Ubuntu 22.04): SSH keys only, firewall allowing outbound only, automatic security updates, encrypted data partition, Docker with the NVIDIA runtime, chrony | DO | 4 | Must | HW-01 | A blank box is ready in under 30 minutes by running one script |
| HW-04 | Multi-architecture Docker images built in CI: arm64 on the Jetson L4T base and amd64 on a CUDA base; image size budget; images signed | DO | 3 | Must | REP-06 | Same tag runs on both box types |
| HW-05 | Zero-touch provisioning: box ships prepared from the Riyadh office; at the site the installer opens the box's local page (or scans its QR sticker), enters the enrolment token, the box enrols and pulls its site config | DO, BE | 2 | Must | CLD-04, HW-03 | A non-developer enrols a box in under 10 minutes |
| HW-06 | Remote access for support: Tailscale on every box, tagged per customer, access rules so only Code-Ox ops can connect, every session logged; no inbound ports opened at customer sites | DO | 1 | Must | HW-03 | Ops reaches a box behind a customer firewall with no firewall change |
| HW-07 | Over-the-air updates: the agent pulls new image tags per channel (staging, canary, stable), restarts services, runs health checks, and rolls back automatically if heartbeat or cameras fail within 10 minutes | DO, BE | 3 | Must | EDG-13, HW-04 | A deliberately broken update rolls itself back on the office box |
| HW-08 | Network fallback: 4G/5G router option tested end to end; average upload measured (target under 1 Mbps per site); data usage per month documented for SIM sizing | DO | 1 | Must | HW-01 | 7-day test on 4G with usage figures recorded |
| HW-09 | Heat test: run both boxes 48 h in a closed cabinet at about 45 °C ambient; choose enclosures and placement rules from the results | FLD, DO | 1 | Must | HW-01 | No thermal throttling below the target fps, or a documented cooling rule |
| HW-10 | Power resilience: UPS per box, clean shutdown on low battery, automatic start after power returns (firmware setting), no data loss after a hard power cut | DO | 0.5 | Must | HW-03 | 10 pulled-plug tests with no corrupted disk |
| HW-11 | Analogue and DVR sites: test RTSP from a Hikvision Turbo HD DVR; document when a separate video encoder is needed | FLD | 1 | Should | HW-01 | Recipe in the installer guide |
| HW-12 | Bill of materials and suppliers in Saudi Arabia for tiers S, M and M-alt: part numbers, landed price, supplier, lead time, warranty; spare pool of one box per 10 sites | PO | 1 | Must | HW-02 | BOM sheet approved; first supplier quotes received |
| HW-13 | Asset tracking: serial number, asset tag and QR enrolment sticker per box; warranty and location recorded in the admin console | PO, DO | 0.5 | Should | WEB-15 | Every box in the field is listed with its site |

---
Full plan: [docs/development-task-plan.md](../../docs/development-task-plan.md) · All tasks as CSV: [tasks/tasks.csv](../tasks.csv)
