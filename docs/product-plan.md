# Code-Ox Vision AI — Product Plan, Architecture & Budget

_Last updated: 2 November 2026 · Owner: Shabeeb (Product owner)_

## Summary

We are building **Code-Ox Vision**: real-time operational alerts from the CCTV cameras our customers already own, with open-source AI, a small edge box per site and a Saudi-hosted cloud. Cost: about **SAR 230K to reach paid pilots (6 months) and SAR 560K to 850K for the first year**, aiming at **15 paying sites by December 2027** on per-site plans from SAR 299 to 1,499 a month.

- **What we sell:** the moment something goes wrong on the floor (queue building, shelf empty, exit blocked, helmet missing, forklift too close to a person, hygiene lapse, fall), a manager gets a WhatsApp message with a 10-second clip. No new cameras, installed in 1 to 2 days, video never leaves the building.
- **What we build:** six industries (retail, restaurants, logistics, manufacturing, hotels, healthcare) served from five generic capabilities: zone occupancy, dwell and queue timing, object present or missing, proximity and crossing, and a visual question to a vision-language model. Our differentiators: WhatsApp-native alerts, Odoo and POS integration, Arabic-first dashboard, published pricing and a reseller channel.
- **How it works:** cameras stream to an edge box on the customer's network; a detector (RF-DETR, Apache-2.0) and tracker (ByteTrack) turn frames into events; a rules engine fires alerts; only events and clips go to our cloud; a vision-language model gives a second opinion on fuzzy events to cut false alarms.
- **Hardware:** Jetson Orin Nano (up to 8 cameras, \~SAR 2,500 landed), Orin NX or RTX 4060 mini-PC (16 to 30 cameras, \~SAR 4,600 to 6,600), RTX 4090 workstation (60 to 100 cameras, \~SAR 25,000). The customer pays for the box in the setup fee. Development needs no hardware at all: it runs on recorded video and the office NVR.
- **The one trap:** Ultralytics YOLO, the best-known detector, needs a paid licence for any commercial product. We use RF-DETR and D-FINE instead, which are free for commercial use and as accurate.
- **Legal:** anonymous analytics are fine under PDPL and the Saudi camera law if video stays on site and we never identify people; face recognition is sensitive biometric data and stays out of the product.
- **Plan:** five phases with a gate after each; the real money is only committed after two of three free pilots sign.

**Decision asked:** approve phase 0 (one month, hire one senior computer-vision engineer, build the lab) on the lean budget; see the last section for the five decisions.

## The market and what buyers expect

Operational video analytics on existing CCTV is an established category: US vendors charge $20 to 100 per camera per month, India has several players, and Riyadh already has a funded local startup ([RIME](https://bridgemena.com/news/saudi-based-rime-secures-over-2-million-seed-round-to-advance-ai-powered-enterprise-surveillance-solutions), $2M+ seed, 6,000+ cameras). Buyers have learned what to expect from how the category is sold, and nobody in the Saudi market publishes a price. We will meet every expectation below and beat the market on the items in the last table.

**What buyers expect (and we must deliver)**

| Expectation | Our answer |
| --- | --- |
| Works with existing cameras, no rewiring, no downtime | RTSP/ONVIF pull from the NVR; analogue cameras via the site's DVR or an encoder |
| Installed in 1 to 2 days, site stays open | Pre-configured edge box, survey before quote, our field engineer installs |
| Video stays in the building, data stays in the country, keeps working when the internet drops | Edge inference, events and clips only to a Saudi-hosted cloud, offline queue on the box |
| Alert on the phone with a clip, approve or dismiss in one tap | WhatsApp and Telegram first, app later |
| Free pilot before any contract, customer keeps the findings | One area, two weeks, their cameras |
| A named contact and ongoing tuning | Field engineer plus a 2-week tuning period in every contract |
| Sold on money recovered, not on technology | Loss calculator on our site (retail shrink \~1.6% of sales, out-of-stocks 3 to 4%, detention \~2% of freight spend) |

**Detections buyers ask for, by industry**

| Industry | Most requested | Also asked for |
| --- | --- | --- |
| Retail | Theft/concealment, unscanned items at till, live queue count and wait, footfall vs receipts, customer path, aisle heatmap | Staff on floor, planogram drift, peak cover, queue abandonment, promo performance, opening checks |
| Logistics | Dock dwell per door, pallet damage at the door, blocked aisles and fire exits, forklift–pedestrian near miss | High-vis compliance, vehicle speed zones, yard occupancy, load counts, gate access, cold-chain doors |
| Manufacturing | PPE per zone per shift, forklift proximity, downtime with reason, defect detection on belt | Machine guarding, restricted zones, changeover timing, spills, line speed, shift handover |
| Hotels | Check-in queue, room turn time, pool occupancy and unattended entry, back-of-house door logs | Luggage handling, spills, gym/spa occupancy, valet, housekeeping carts, after-hours entry |
| Restaurants | Counter queue timing, hygiene proof (hairnet, gloves, handwash), table-clear detection, waste visibility | Wet floors, cleaning rounds, station idle, order-ready dwell, drive-thru timing, staff on floor |
| Healthcare | Bed exit/fall to nearest station, hand-hygiene by role, blocked corridors, waiting room count vs target | PPE in clinical zones, pharmacy access, wheelchair availability, visitor flow, equipment location, ward capacity |

Almost every row above is the same five building blocks dressed for a sector: people counting in a zone, dwell/queue timing, object present or missing (shelf, PPE, trolley), two objects too close (forklift and person), and a VLM yes/no check (spill, damage, hygiene). We build the five blocks once and sell them six ways.

**Competitors and their pricing (for our own pricing later)**

| Competitor | Model | Public pricing |
| --- | --- | --- |
| [RIME](https://bridgemena.com/news/saudi-based-rime-secures-over-2-million-seed-round-to-advance-ai-powered-enterprise-surveillance-solutions) (Riyadh) | Cameras to AI agents, 6,000+ cameras, $2M+ seed Aug 2026 | Not public |
| Sighti AI (Riyadh, sighti.ai) | YOLO-based edge analytics on existing cameras, vendor-installed in 1 to 2 days, iOS app alerts with clip, free one-week pilot; \~4 staff, $180K pre-seed from Antler (2025), six industries, no named customers | Not public; direct sales only, no WhatsApp, ERP or POS integrations, no Android app |
| [Spot AI](https://getsafeandsound.com/blog/spot-ai-pricing/) (US) | On-site recorder + cloud | \~$99 per camera per month, $1.5 to 5K install |
| [Coram AI](https://us.fitgap.com/products/032483/coram-ai) (US) | Cloud VMS + AI alerts | \~$180 to 400 per camera per year |
| [Lumeo](https://lumeo.com/pricing) (US) | No-code pipelines, bring your cameras | $99/month for 10 streams, +$10 per stream |
| [Wobot.ai](https://help.wobot.ai/en/article/how-does-pricing-work-in-wobot-gjxuos/) (IN) | Restaurant SOP compliance | From $40 per location per month (2022) |
| [Slinai](https://slinai.com/) (IN) | Agentic analytics, alerts to WhatsApp/Slack/Teams | Not public |
| Lumana, Hakimo, Chooch, Everseen, Ambient.ai | Enterprise security/ops AI | Quote only |

**Where we win**

| Gap in the market | Code-Ox Vision |
| --- | --- |
| No WhatsApp-native alerting from local vendors | WhatsApp first, Arabic and English, with clip and one-tap feedback |
| No ERP or POS integration | Odoo integration (we are an Odoo partner with an installed base), footfall vs sales, events as tickets |
| English-first dashboards | Arabic-first UI and reports |
| No published price | Per-site plans from SAR 299 a month, published on the website |
| Direct sales by tiny teams | Reseller programme through Odoo partners and CCTV integrators |
| iOS-only or no app | Web first, then Android and iOS |

## How computer vision AI works (what we are actually building)

This product is not one AI model; it is a pipeline that turns a camera's video into a short list of business events. Every stage below is a known, solved engineering problem with open-source parts.

1. **Pull video from the camera.** Nearly every IP camera or NVR exposes a video stream over the local network (RTSP). We read it like a file, nothing is installed on the camera.
2. **Decode and sample frames.** Video is 25 frames per second; analytics only needs 2 to 10 per second. Skipping frames is the single biggest cost saver, one GPU can then serve many cameras.
3. **Detect objects.** A detection model (YOLO or DETR family) looks at a frame and returns boxes: person, forklift, box, cart, shelf item, hand, helmet, puddle. It runs in 5 to 30 milliseconds on a GPU.
4. **Track objects between frames.** A tracker (ByteTrack) gives each person or vehicle an ID so we can count unique people, measure dwell time and queue length, and detect loitering or entering a zone.
5. **Apply business rules.** This is where the product lives. A rule is a zone drawn on the camera view plus a condition: more than 5 people in the checkout zone for 2 minutes = queue alert; no person detected in the kitchen zone for 10 minutes during opening hours = unattended station; a person box overlapping a forklift box in the aisle = safety alert.
6. **Verify with a vision-language model (optional, high value).** For fuzzy events (spill on floor, shelf looks empty, staff not wearing uniform), a VLM such as Qwen-VL or Claude is shown the frame and asked a yes/no question. This is slower and costs money per call, so it runs only when the cheap detector thinks something may be happening, and it cuts false alarms a lot.
7. **Alert and record.** Send the clip and a one-line message to WhatsApp, Telegram, email or a dashboard; store the event, not the whole video; let the manager mark it true or false, which becomes training data.

**Three kinds of model, and when to use each**

| Kind | What it does | Needs training on our data? | Typical use |
| --- | --- | --- | --- |
| Pretrained detector (YOLO, RT-DETR, RF-DETR) | Finds 80 common object types (person, car, chair, bottle, etc.) fast | No for people, vehicles, bags, carts; yes for custom things (specific products, a company's uniform) | People counting, queues, zones, vehicles, dwell time |
| Fine-tuned detector | Same model retrained with 300 to 2,000 labelled images of the customer's objects | Yes, a few days of labelling per use case | PPE/helmet, forklift, spills, empty shelf, cleaning trolley |
| Vision-language model (VLM) | Answers a question about an image in plain words, no training | No | Any new use case on day one, false-alarm filtering, "describe what happened" reports |

The practical strategy: launch new use cases with a VLM (zero training, slow, higher cost per frame), collect real customer frames, then fine-tune a small detector for the ones that get volume (fast, near-free per frame). This is how we offer custom detections in days without a research team.

**Accuracy reality.** Good pretrained detectors hit about 50 to 55 percent mAP on the standard COCO benchmark, which in practice means people and vehicles are detected reliably in decent lighting from a normal CCTV angle. Accuracy drops with overhead fisheye cameras, night IR, reflections and crowds, so every site needs a 1 to 2 week tuning period where thresholds and zones are adjusted and the manager's true/false feedback is used.

## Our product: features, use cases and priorities

Working name: **Code-Ox Vision** (rename later). Promise: *"Your cameras tell you the moment something goes wrong, on WhatsApp, in Arabic or English."* We build five generic capabilities that cover every industry, and differentiate on WhatsApp-native alerts, Odoo/POS integration, Arabic-first design, a public price and a reseller channel.

**The five capabilities everything is built from**

| Capability | What the customer sees | Built from |
| --- | --- | --- |
| Zone occupancy | "More than N people in zone X for T minutes", "nobody at station Y during opening hours", capacity limits | Person detector + tracker + polygon zones + timers |
| Dwell and queue timing | Queue length, average wait, dock dwell, table turn time, room turn time, drive-thru timing | Tracker IDs entering/leaving zones, time in zone |
| Object present / missing | Empty shelf, blocked exit, trolley in corridor, missing hairnet/helmet/vest/gloves, wet-floor sign | Fine-tuned detector per object class, with a VLM check |
| Proximity and crossing | Forklift near person, vehicle in pedestrian zone, line crossing, after-hours entry, tailgating | Two detections overlapping or crossing a virtual line |
| Visual question (VLM) | "Is there a spill?", "Is the pallet damaged?", "Is the counter clean?", free-text custom checks on a schedule | Hosted or self-hosted vision-language model on a snapshot |

**Release plan by priority**

| Release | Scope | Why this order |
| --- | --- | --- |
| MVP (pilot-ready) | People counting, zone occupancy, queue length and wait, dwell time, line crossing, after-hours presence, WhatsApp + Telegram alerts with clip, zone editor on a camera snapshot, true/false feedback, daily summary message | All run on pretrained models with zero training; cover retail, restaurant, hotel and clinic queues on day one |
| V1 (first paying customers) | PPE (helmet, vest, hairnet, gloves), forklift–person proximity, blocked aisle/exit, empty-shelf, wet floor, cleaning-round verification, table-clear, Arabic/English web dashboard, weekly PDF report, multi-site view, roles and permissions, per-site plan billing | Needs 5 to 8 fine-tuned classes and the VLM check; unlocks logistics, manufacturing and F&B compliance |
| V2 (differentiation) | Scheduled VLM "visual checklists" (opening/closing checks with photo proof), Odoo integration (events as helpdesk tickets, footfall vs POS sales), heatmaps and path maps, dock dwell by door, fall detection, hand-hygiene by role, open API and webhooks, Android/iOS app, partner/reseller portal | What competitors lack and what lets Code-Ox sell to its Odoo base |
| Later / only on demand | Checkout sweethearting, defect detection on a belt, face-based anything | Each is its own product with heavy training or legal risk (see Risks); quote as custom projects |

**Use cases per industry, mapped to capabilities (core use cases, our differentiators in bold)**

| Industry | Core use cases | Our differentiators |
| --- | --- | --- |
| Retail | Queue and wait per till, footfall by hour, empty shelf, staff presence on floor, aisle heatmap, after-hours entry | **Footfall vs Odoo POS conversion**, **promo-zone dwell**, **opening/closing visual checklist with photo proof**, **Ramadan/Eid hour schedules** |
| Restaurants / F&B | Counter queue, hairnet/gloves, table-clear, wet floor, cleaning rounds, station idle, drive-thru timing | **Baladiya (municipality) hygiene evidence pack**, **delivery-rider waiting-area count**, **kitchen VLM checklist (surfaces, bins, uniforms)** |
| Logistics | Dock dwell per door, blocked aisle/exit, forklift near miss, high-vis, yard occupancy, gate access | **Truck plate-free dock scheduling by dwell**, **pallet damage photo at door (VLM)**, **loading-bay idle report** |
| Manufacturing | PPE per zone, forklift proximity, line stopped (motion absent), restricted zones, spills | **Downtime timeline exported to Odoo Manufacturing**, **shift-handover compliance snapshot** |
| Hotels | Check-in queue, pool occupancy and unattended entry, housekeeping cart timing, back-of-house doors, gym occupancy | **Room-turn time to housekeeping WhatsApp group**, **breakfast buffet queue and refill (VLM)** |
| Healthcare (clinics, home-care offices) | Waiting-room count vs target, blocked corridors, PPE in clinical zones, pharmacy access, hand-hygiene | **Patient wait SMS/WhatsApp when queue exceeds target**, **fully offline mode for hospitals**; fall detection only in V2 after validation |

**Product rules we commit to from day one**

- No face recognition, no identity tracking. Reports name a role and a zone, never a person. This is both the legal safe zone and the selling point.
- Video never leaves the site; only events, snapshots and 10-second clips do, and the customer sets retention (default 30 days).
- Every alert can be marked true or false in one tap; false-alert rate per rule is visible to the customer and to us.
- Alerts have cooldowns, quiet hours, escalation (manager, then area manager) and a daily cap so WhatsApp never becomes noise.
- Arabic and English everywhere: dashboard, alerts, reports.

## System architecture

We run the AI on a small box at the customer site and keep only events, clips and settings in a Saudi-hosted cloud. "Works with your existing cameras" forces this design on anyone who promises it, and it is the only one that fits Saudi data rules, bandwidth costs and NVRs on isolated networks.

![System architecture: edge box at the site, Saudi-hosted cloud, three user groups](images/system-architecture.png)

Cameras feed the edge box over the site network; the box sends only detected events and 10-second clips to the cloud, which verifies, alerts and reports, and pushes rule or model updates back down.

**Why edge-first and not cloud-first**

- A single 720p camera stream is 1 to 2 Mbps. Twenty cameras streaming to the cloud is 30 to 40 Mbps upload around the clock, which most Saudi shops and warehouses do not have spare, and cloud GPU time to decode it costs more than the box.
- Camera networks are usually on a separate VLAN with no internet. A box plugged into that VLAN with one outbound connection is a 30-minute install; opening the NVR to the internet is a security conversation customers refuse.
- Raw video never leaves the premises, which is the answer to the PDPL question every Saudi buyer will ask.
- Cloud is kept for what must be shared: rules, events, alerts, dashboards, VLM checks, model training and fleet management.

**Components and the tech we will use**

| Component | Runs where | Technology | Notes |
| --- | --- | --- | --- |
| Stream ingest | Edge | go2rtc or FFmpeg/GStreamer, hardware decode (NVDEC) | Pull RTSP sub-streams at 5 to 10 fps; reconnect logic is most of the work |
| Inference | Edge | Detector exported to TensorRT or ONNX, ByteTrack tracker | One process per box, batches frames from all cameras |
| Rules engine | Edge | Python service, rules as JSON (zone + condition + schedule + cooldown) | Evaluates every frame's detections; writes an event when a rule fires |
| Clip buffer | Edge | Rolling 30-second ring buffer per camera in RAM/disk | Cuts the 10 seconds around an event and uploads it |
| Edge agent | Edge | Docker Compose, MQTT or HTTPS heartbeat, remote update via Balena-style or plain SSH + Ansible | Reports health, pulls new rules and models |
| Event API + store | Cloud | FastAPI, PostgreSQL, S3-compatible object storage for clips | Multi-tenant: customer > site > camera > rule > event |
| VLM verification | Cloud | Hosted model API (Claude or Gemini) first; self-hosted Qwen-VL later if volume justifies a GPU | Called only on candidate events; budget per customer |
| Alert dispatcher | Cloud | WhatsApp Business Cloud API, Telegram Bot API, SMTP, webhooks | Deduplicate, group, respect quiet hours and escalation |
| Dashboard | Cloud | React web app, Arabic + English | Live events, zone editor on a camera snapshot, true/false feedback, weekly reports |
| Model ops | Cloud | CVAT or Label Studio for labelling, training jobs on a rented GPU, model registry | Feedback loop from manager's true/false marks |
| Auth + billing | Cloud | Keycloak or Clerk for login, Stripe or local gateway (Moyasar/HyperPay) for SAR billing | Per-site plan subscription |

## AI models and open-source stack

Everything we need exists as open source with a licence that allows a commercial, self-hosted product, provided we avoid one trap: Ultralytics YOLO. Our stack: **RF-DETR** for detection, **Supervision + ByteTrack** for tracking and zones, **go2rtc** for camera streams, **TensorRT/ONNX Runtime** on NVIDIA hardware, **Qwen3-VL or Claude Haiku** for visual questions, **CVAT** for labelling, **Frigate** as a reference design.

**The licence trap, in one paragraph.** YOLO11/YOLO26 from Ultralytics are the most famous detectors and most competitors use them, but the code and any model you train with it are AGPL-3.0, and [Ultralytics' licence page](https://www.ultralytics.com/license) says any commercial product, SaaS or edge device needs their paid Enterprise licence (quote only, no public price). The permissive alternatives below are as accurate or better, so we do not need it.

**Detection models (the eyes)**

| Model | Licence | Accuracy (COCO mAP) | Speed on a T4 GPU | Verdict |
| --- | --- | --- | --- | --- |
| [RF-DETR](https://github.com/roboflow/rf-detr) Nano / Small / Medium / Large | Apache-2.0 | 48.4 / 53.0 / 54.7 / 56.5 | 2.3 / 3.5 / 4.4 / 6.8 ms | **Primary choice.** Best accuracy per millisecond, free for commercial use, easy fine-tuning. Avoid the Atto/Pico and XL/2XL sizes (different licence) |
| [D-FINE](https://github.com/Peterande/D-FINE) / [DEIM](https://github.com/Intellindust-AI-Lab/DEIM) N to X | Apache-2.0 | 42.8 to 56.5 | 2.1 to 12.9 ms | Backup; in Hugging Face Transformers. DEIMv2 is not Apache, do not upgrade to it |
| [RT-DETRv2](https://github.com/lyuwenyu/RT-DETR) S to X | Apache-2.0 | 48.1 to 54.3 | 108 to 217 FPS | Fine, slightly older |
| [YOLO26](https://docs.ultralytics.com/models/yolo26/) n to x | AGPL-3.0 / paid Enterprise | 40.9 to 57.5 | 1.7 to 11.8 ms | Only if we buy the licence or run on Roboflow cloud |
| YOLOX, DAMO-YOLO, PP-YOLOE | Apache-2.0 | 40 to 55 | similar | Unmaintained since 2023, skip |
| YOLO-NAS | Weights non-commercial |  |  | Trap, skip |

What these numbers mean: a Nano model on a desktop GPU answers in 2 to 4 ms, so one GPU can run 250 to 400 detections per second, which is 25 to 40 cameras at 10 frames per second before decoding becomes the limit.

**Tracking and zones (the memory)**

| Tool | Licence | Use |
| --- | --- | --- |
| [Supervision](https://github.com/roboflow/supervision) (Roboflow) | MIT | ByteTrack tracker, polygon zones, line crossing, time-in-zone, drawing. Most of our rules engine's primitives |
| [roboflow/trackers](https://github.com/roboflow/trackers) | Apache-2.0 | SORT, ByteTrack, OC-SORT, BoT-SORT if we need re-identification across occlusions |
| BoxMOT, original DeepSORT | AGPL / GPL | Avoid |

**Vision-language models (the second opinion, zero training)**

| Model | Licence | Where it runs | Use |
| --- | --- | --- | --- |
| [Claude Haiku 5.5](https://platform.claude.com/docs/en/about-claude/pricing) | Hosted API, $0.10 in / $0.50 out per 1M tokens | Cloud | Start here: about $0.001 per image check, no GPU to run. Gemini Flash-Lite is the equivalent |
| [Qwen3-VL 8B](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct) | Apache-2.0 | Our cloud GPU (about 18 GB VRAM) | Self-host when volume makes API cost matter, or for customers who demand no external API |
| [SmolVLM2 2.2B](https://huggingface.co/HuggingFaceTB/SmolVLM2-2.2B-Instruct) | Apache-2.0 | Edge box (5 GB VRAM) | On-site visual checks for fully offline hospital/government deployments |
| [Florence-2](https://huggingface.co/microsoft/Florence-2-large) | MIT | Edge or cloud | Zero-shot detection of odd objects, captions, OCR on signs |
| [Grounding DINO](https://github.com/IDEA-Research/GroundingDINO) | Apache-2.0 | Labelling pipeline | Auto-label training images from a text prompt ("forklift", "hairnet") |
| [SAM 3](https://github.com/facebookresearch/sam3) | SAM licence (commercial OK) | Labelling / V2 | Text-prompted segmentation and tracking in video; heavy |

**Ready-made models and datasets for V1 use cases**

| Need | Source | Note |
| --- | --- | --- |
| PPE: helmet, vest, hairnet, gloves | [Roboflow PPE tutorial](https://roboflow.com/blog/ppe-detection) (RF-DETR Small, 79% mAP50) and Universe datasets (CC BY 4.0) | Good warm start; fine-tune on 300 to 500 site images |
| Pose for fall / slip | [RF-DETR Keypoint](https://github.com/roboflow/rf-detr) (Apache, 71.8 AP) or MMPose RTMPose | Fall detection needs site validation before selling |
| Fire and smoke | [D-Fire dataset](https://github.com/sayedgamal99/DFireDataset) 21K images | Public models are experimental (\~29% mAP), treat as warm start only |
| Empty shelf, wet floor, blocked exit, pallet damage | No reliable public model | VLM first, then collect customer frames and fine-tune RF-DETR |

**Pipeline and runtime**

| Component | Licence | Why |
| --- | --- | --- |
| [go2rtc](https://github.com/AlexxIT/go2rtc) | MIT | Pulls each camera once (RTSP/ONVIF), feeds analytics and the live view; handles reconnects |
| [Frigate NVR](https://github.com/blakeblackshear/frigate) | MIT | The best open reference for motion-gated detection, MQTT events and multi-accelerator support (Jetson, Hailo, OpenVINO). We can even ship it as the recording layer |
| [NVIDIA DeepStream](https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_Overview.html) + [Savant](https://github.com/insight-platform/Savant) | Free NVIDIA EULA / Apache-2.0 | Needed above about 8 streams per box: hardware decode and batching without copying frames. Savant wraps it in Python/YAML |
| [Roboflow Inference](https://github.com/roboflow/inference) | Apache-2.0 core | Workflows server: detect, track, count, time-in-zone, VLM, webhook; fastest way to a demo. Enterprise folder has a separate licence |
| TensorRT / [ONNX Runtime](https://onnxruntime.ai/docs/execution-providers/TensorRT-ExecutionProvider.html) | Free | FP16 export doubles speed; INT8 with 500 calibration images doubles again |
| [OpenVINO](https://github.com/openvinotoolkit/openvino) | Apache-2.0 | If we ever ship Intel mini-PCs without NVIDIA GPUs |
| [Hailo-8](https://hailo.ai/products/ai-accelerators/hailo-8-ai-accelerator/) M.2 card | Runtime MIT | 26 TOPS at 2.5 W, \~500 FPS for a small YOLO; cheap add-on for Intel boxes |

**Labelling and training**

| Tool | Licence / price | Use |
| --- | --- | --- |
| [CVAT](https://www.cvat.ai/pricing) | MIT self-hosted; cloud from $23/user/month | Our labelling tool, self-hosted in India |
| [Roboflow](https://roboflow.com/pricing) | Free tier; Core $39/month | Fastest for the first 6 months: datasets, auto-label, training, hosted demos. Export weights and self-host |
| [Label Studio](https://humansignal.com/pricing/) | Apache-2.0; cloud $99/month | Alternative to CVAT |
| Training GPU | Rented, about $1 to 2 per hour | A fine-tune of RF-DETR Small on 1,000 images takes 1 to 2 hours |

**Alert channels and cost in Saudi Arabia**

| Channel | Cost | Note |
| --- | --- | --- |
| [WhatsApp Cloud API](https://developers.facebook.com/docs/whatsapp/pricing) | Utility template about $0.0107 (SAR 0.04) per message in KSA; free inside a 24-hour reply window | Primary channel. Needs Meta Business verification and template approval |
| Telegram Bot API | Free | Internal ops and price-sensitive customers |
| Email (SMTP) | Near free | Daily and weekly reports |
| Microsoft Teams | Free | Legacy webhooks retired May 2026; use Power Automate Workflows |
| [Twilio SMS to KSA](https://www.twilio.com/en-us/sms/pricing/sa) | $0.19 per message | Escalation only, 18× WhatsApp |

## CCTV camera integration

We connect to what the customer already has by pulling the low-resolution "sub-stream" of each camera from the NVR over the site network. No camera is replaced, nothing is installed on the camera, and the main recording is untouched. In Saudi Arabia that mostly means Hikvision, Dahua and Uniview NVRs, which all speak RTSP and ONVIF.

**How we pull video from each brand**

| Brand | RTSP URL pattern (sub-stream) | Note |
| --- | --- | --- |
| [Hikvision](https://help.nsoft.vision/hc/en-us/articles/4411595651345-List-of-RTSP-URLs-of-security-camera-manufacturers) (and HiLook, Hik OEMs) | `rtsp://user:pass@NVR:554/Streaming/Channels/N02` where N is the NVR channel (ch 17 = `1702`) | Most common in KSA; their Turbo HD DVRs for analogue cameras expose the same paths |
| [Dahua](https://securitycamcenter.com/rtsp-url-address-format-dahua/) (Amcrest, Lorex, IMOU) | `rtsp://user:pass@NVR:554/cam/realmonitor?channel=N&subtype=1` | Same for camera and NVR |
| Uniview | `rtsp://NVR:554/unicast/cN/s1/live` |  |
| [Axis](https://developer.axis.com/vapix/network-video/rtsp-adjustable-live-stream/) | `rtsp://IP/axis-media/media.amp?streamprofile=...` | Premium sites; can also run our app on the camera later |
| Hanwha/Wisenet | `rtsp://NVR:554/LiveChannel/N/media.smp` | Channels start at 0 |
| Any ONVIF device | Auto-discovery: GetProfiles then GetStreamUri | Use ONVIF first, brand table as fallback for cheap cameras with broken ONVIF |

**Stream settings we ask for**

| Setting | Value | Why |
| --- | --- | --- |
| Resolution | 1280×720 (minimum 704×576) | Person detection at 10 to 15 m needs more than the 352×288 default on old Hikvision sub-streams |
| Frame rate | 10 to 15 fps from the camera, we analyse 5 to 10 | Halving fps roughly halves bitrate |
| Codec | H.264 preferred; H.265 fine on Jetson and modern GPUs | Older decoders and browser previews prefer H.264 |
| Bitrate | 0.5 to 1.5 Mbps per stream ([VEG guide](https://help.videoexpertsgroup.com/kb/recommended-bitrate-settings)) | 16 cameras = 8 to 24 Mbps on the LAN; trivial for a switch, impossible to send to the cloud |

**NVR limits to respect.** NVRs have an outgoing bandwidth budget and a cap on remote connections: a current 16-channel Hikvision ([DS-7616NI-I2C](https://assets.hikvision.com/prd/normal/all/doc/m000000573/DS-7616NI-I2C_Datasheet_20250121.pdf)) allows 256 Mbps out and 128 connections, which is plenty, but 2018-era units allow 80 Mbps total and drop off the network when oversubscribed. Each camera also allows only about 6 simultaneous viewers. Rule: one session per channel from our box, pull from cameras directly on old NVRs, and never pull main streams.

**Older video management systems.** Milestone XProtect has a free [AI Bridge](https://doc.milestonesys.com/AIB/Help/Latest/en-US/feature_flags/ff_aibridge/aib_adm_licensing_expl.htm) that pushes video to us over RTSP and takes events back; Genetec exposes an RTSP Media Gateway after signing their free SDK terms. Both only matter for large enterprise accounts; the first 50 customers will be NVR-based.

**Analogue cameras.** The "one small box" competitors sell for analogue cameras is a video encoder. In practice the site's HD-TVI DVR already exposes RTSP, so we rarely need one; when we do, a 16-channel encoder is roughly $1,000.

**Gotchas we will hit on every third site**

1. Cameras sit on a separate VLAN with no internet. Our box plugs into that VLAN and needs one outbound firewall rule (HTTPS to our cloud). Plan a 4G/5G router as a fallback for sites whose IT will not open anything.
2. Consumer Wi-Fi cameras with app-only access (no RTSP) cannot be used; say so during survey, not after.
3. Admin passwords for the NVR are lost or held by a departed integrator; budget time for a reset.
4. Sub-stream set to CIF; fix in the NVR UI during install.
5. Camera angle is wrong for the use case (a door camera cannot measure a queue). Some use cases need one repositioned or added camera; price it as an option.
6. Night IR, reflections on glass, overhead fisheye lenses all reduce accuracy; set expectations per camera in the survey report.
7. Saudi summer: a fanless box in an unventilated NVR cabinet will throttle. Use a fanned enclosure or an industrial unit rated to 60 °C.

**Site survey checklist (one page, done before any quote)**

- [ ] Camera list: brand, model, IP or analogue, resolution, codec; test-pull one sub-stream with ffprobe
- [ ] NVR/DVR model, channel count, spare outgoing bandwidth, RTSP port, admin login available
- [ ] Network: CCTV VLAN layout, spare switch port and power for our box, internet upload speed test, who approves firewall rules
- [ ] Per camera: what it sees, mounting height, lighting day and night, intended use case, obstructions
- [ ] Legal: signage present, no cameras in prohibited areas (changing rooms, exam rooms, toilets), current retention setting, site sensitivity class
- [ ] Environment: rack or cabinet space, temperature, UPS
- [ ] Commercial: number of cameras, alerts wanted, who receives them, existing VMS, data-residency requirement

## Server and hardware configurations

Three standard edge boxes cover every site size, and the cloud side starts on one small server. NVIDIA [raised Jetson prices by up to 100% in July 2026](https://cnx-software.com/2026/07/22/nvidia-increases-the-price-of-jetson-modules-and-devkits-by-up-to-101), so a GPU mini-PC is now often cheaper per camera than a Jetson above 16 cameras. Saudi landed cost is roughly US price × 3.75 × 1.35 (15% VAT plus import and distributor margin); all SAR figures below use that.

**Edge box tiers (per customer site)**

| Tier | Hardware | Cameras it handles (720p, 5 to 10 fps, Nano/Small detector) | US price | Landed SAR (est.) | Source |
| --- | --- | --- | --- | --- | --- |
| S: small shop, clinic, café | Jetson Orin Nano Super 8 GB dev kit + SSD + fanned case | up to 8 | $399 + \~$100 | \~2,500 | [SparkFun](https://www.sparkfun.com/nvidia-jetson-orin-nano-developer-kit.html), [Seeed benchmark](https://wiki.seeedstudio.com/YOLOv8-DeepStream-TRT-Jetson/) |
| M: supermarket, restaurant group site, hotel | Seeed reComputer J4012 (Orin NX 16 GB, boxed, fanned) or Advantech MIC-713 (industrial, 60 °C rated) | 16 to 24 | $899 / \~$2,400 | \~4,600 / \~12,000 | [Hackster store](https://hackster.io/products/buy/116837), [PB Tech](https://www.pbtech.com/product/IPCAVH080031/Advantech-MIC-713S-OX4A1-MIC-713S-Orin-NX-16GB-Sol) |
| M-alt: same tier, cheaper per camera | Mini-PC with RTX 4060 8 GB (e.g. Minisforum 795S7) | 20 to 30 | \~$1,300 | \~6,600 | [deal listing](https://slickdeals.net/f/18294889-minisforum-795s7-mini-pc-ryzen-9-7945hx-rtx-4060-32gb-ddr5-ram-1tb-ssd-win-11-pro-949-99), [Frigate benchmarks](https://docs.frigate.video/frigate/hardware) |
| L: warehouse, factory, mall | Workstation with RTX 4090 24 GB (or RTX 5090) + DeepStream | 60 to 100 | \~$3,200 card, \~$5,000 built | \~25,000 | [GPU prices Oct 2026](https://gpupoet.com/gpu/learn/price/october-2026/nvidia-geforce-rtx-4090) |
| XL: enterprise / data-centre | Server with NVIDIA L4 or L40S | 100 to 150 | $7,400 (L40S card) | \~37,000 | [DeepStream performance](https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_Performance.html) |
| Budget option | Intel mini-PC + Hailo-8 M.2 card ($180) via OpenVINO/Hailo runtime | 8 to 12 | \~$600 total | \~3,000 | [Waveshare](https://www.waveshare.com/product/raspberry-pi/hailo-8.htm), [Seeed Hailo benchmark](https://wiki.seeedstudio.com/benchmark_of_multistream_inference_on_raspberrypi5_with_hailo8/) |

Camera counts are planning figures derived from vendor benchmarks at 1080p30; we must benchmark our own pipeline (detector + tracker + decode) on each tier before quoting. Decode and RAM, not the AI, are what run out first on Jetson.

**Standard edge software image (same on every tier)**

- Ubuntu 22.04 (JetPack 6 on Jetson), Docker Compose, Tailscale or WireGuard for our remote access
- go2rtc (streams), inference service (TensorRT engine), rules engine, clip buffer, edge agent (heartbeat, config pull, model pull, log shipping)
- Watchdog: auto-restart, disk cleanup, and an offline mode that keeps detecting and queues events until the internet returns
- No inbound ports; everything outbound over HTTPS/MQTT

**Cloud side**

| Stage | Setup | Monthly cost | Note |
| --- | --- | --- | --- |
| MVP and pilots | One VPS (8 vCPU, 32 GB) + object storage; VLM via hosted API | $150 to 300 | Hetzner or AWS UAE (me-central-1) is fine for pilots; events and clips only |
| Commercial launch (data residency) | In-Kingdom hosting: [Google Cloud Dammam via CNTXT](https://docs.cloud.google.com/docs/dammam-region-access), [Oracle Riyadh](https://www.oracle.com/sa/cloud/cloud-regions/riyadh/), Alibaba/SCCC or stc cloud; AWS Saudi region [expected Dec 2026](https://tbreak.com/aws-saudi-arabia-cloud-region-december-2026/) | $500 to 1,500 | Needed for hospitals, government and any tender; private retail does not legally require it but will ask |
| Self-hosted VLM (only if API bill exceeds this) | One L4 GPU: [AWS g6.xlarge UAE $0.99/h](https://www.devzero.io/instances/aws/g6.xlarge) (~~$720/month) or [RunPod L4 $0.59/h](https://www.runpod.io/gpu-cloud/pricing) (~~$430) | $430 to 720 | Runs Qwen3-VL-8B for all customers |
| Training | Rented GPU by the hour ([RunPod RTX 4090 $0.89/h](https://www.runpod.io/gpu-cloud/pricing)) | $50 to 150 | A fine-tune is 1 to 2 hours |

**Why not stream everything to the cloud.** A 16-camera site uploads 5 TB a month at 1 Mbps per camera; a [stc small-office 300/100 Mbps plan](https://stc.com.sa/content/stc/sa/en/small-office/packages/fiber-link.html) (SAR 287/month) could carry it but measured Saudi upload averages are only [18 to 32 Mbps](https://insights.opensignal.com/reports/2026/02/saudiarabia/fixed-broadband-experience), and a cloud GPU to decode 16 streams costs more than the Jetson box every two months. Edge inference sends under 1 Mbps per site.

## Budget

Year-one cost is about **SAR 500K (lean, reusing existing Code-Ox developers) to SAR 720K (dedicated team)**, of which the first six months of build are SAR 180K to 300K. Hardware is small and mostly recovered from customers; people are the cost. All figures are estimates in SAR with USD at 3.75; salaries from the [JobRise India 2026 benchmarks](https://jobrise.io/en/blog/salary-benchmarks-india-2026/) at the mid of the IT-services band plus 15% overhead.

**Team cost per month**

| Role | Where | Monthly cost (SAR) | Lean plan | Full plan |
| --- | --- | --- | --- | --- |
| Senior computer-vision / ML engineer (new hire) | India | 13,000 | 1 | 1 |
| Mid CV engineer (new hire) | India | 7,800 | 1 | 1 |
| Python backend engineer | India | 6,000 | 2 existing | 2 |
| DevOps / MLOps | India | 6,500 | 0.5 existing | 1 |
| Frontend (React, Arabic/English) | India | 5,200 | 1 existing | 1 |
| QA | India | 2,600 | 0.5 existing | 0.5 |
| Product owner, sales, pilots | Riyadh (Shabeeb) | existing | existing | existing |
| Saudi field / install engineer (from month 4) | Riyadh | 12,000 all-in (SAR 8K base × 1.5 for iqama, GOSI, housing, vehicle) | 1 | 1 |
| New cash per month (months 1 to 6) |  |  | \~21,000 | \~47,000 |
| New cash per month (months 7 to 12, with field engineer) |  |  | \~33,000 | \~50,000 |

Lean plan assumes three existing Code-Ox developers are moved onto this product for six months (their salaries are already paid, but it is real opportunity cost on client work).

**One-time and setup costs**

| Item | SAR | Note |
| --- | --- | --- |
| Lab kit: 2 Orin NX boxes, 1 RTX 4060 mini-PC, 4 Hikvision cameras + 8-ch NVR, PoE switch | 18,000 | Also our office demo site |
| Pilot edge boxes for 3 free pilots (reusable) | 12,000 | Tier S/M boxes |
| First 15 customer edge boxes | 70,000 | Recovered via setup fee; treat as working capital |
| Legal: PDPL privacy notice, DPIA template, customer contract, camera-law review | 15,000 | Saudi law firm or Clara-type template plus review |
| Meta Business verification, WhatsApp templates, domains, app store accounts | 2,000 |  |
| Marketing: one-page site, Arabic brochure, demo video, LinkedIn | 25,000 |  |
| Training data labelling (contract labellers, \~10,000 boxes) | 8,000 | Or in-house with CVAT |
| Total one-time | \~150,000 | \~80,000 excluding customer boxes |

**Recurring cloud and tooling per month**

| Item | SAR / month | Note |
| --- | --- | --- |
| Cloud server + object storage (pilots) | 900 | Rises to 2,000 to 5,500 on in-Kingdom hosting at launch |
| VLM API checks | 400 to 2,000 | \~SAR 0.004 per check at Haiku/Flash-Lite prices; 20 sites × 16 cameras × 50 checks/day ≈ SAR 2,000 |
| WhatsApp alerts | 200 to 800 | SAR 0.04 per utility message; 20 sites × 30 alerts/day ≈ SAR 720 |
| Roboflow Core, Tailscale, monitoring, training GPU hours | 600 |  |
| Total | \~2,100 to 4,300 (year 1 average \~3,000) |  |

**Year-one total**

|  | Lean (SAR) | Full (SAR) |
| --- | --- | --- |
| People, 12 months | 325,000 | 585,000 |
| One-time (excluding customer boxes) | 80,000 | 80,000 |
| Customer edge boxes (working capital, recovered) | 70,000 | 70,000 |
| Cloud and tooling | 36,000 | 36,000 |
| Contingency 10% | 50,000 | 75,000 |
| **Total** | **\~560,000 (USD 150K)** | **\~850,000 (USD 225K)** |
| Of which months 1 to 6 (build to pilot) | \~230,000 | \~380,000 |

**Revenue model to set against it (see Risks and go-to-market for pricing logic)**

| Assumption | Value |
| --- | --- |
| Pricing (per site, not per camera) | Starter up to 4 cameras SAR 299/month; Standard up to 8 SAR 499; Business up to 16 SAR 899; Enterprise up to 32 SAR 1,499; above 32 by quote. Two months free on annual prepay |
| Setup fee | One-time SAR 1,500 to 4,000 depending on the box (hardware at cost plus one install day); box included on a 24-month contract |
| Average site | SAR 800 per month (mix of Standard and Business) = SAR 9,600 per year |
| Variable cost per site | \~SAR 200 per month (VLM checks, WhatsApp, cloud share) plus support time; Starter at SAR 299 is the floor, not a target |
| Break-even on lean plan | \~40 sites (SAR 33K/month) |
| Year-one target | 15 paying sites by Dec 2027 = SAR 12K/month run-rate plus \~SAR 40K in setup fees |
| Gross margin | Setup covers the box and install day; about 75% on the subscription after variable cost and support time |

The honest read: cheap per-site pricing is a volume bet. Year one is an investment of roughly SAR 500K to 850K; at SAR 800 per site it pays back in year two or three at 40 to 60 sites, so the install must take one day every time, and the Odoo customer base and resellers must bring the volume. Local competitors reached this stage on a single pre-seed round of about SAR 675K with four people, so the lean plan is in line with the market.

## Roadmap

Fourteen months from decision to fifteen paying sites, with a gate between every phase so we stop early if pilots do not convert. The expensive commitment (hiring the field engineer, in-Kingdom hosting, customer hardware stock) only happens after gate 2.

![Roadmap: 5 phases, Nov 2026 to Dec 2027, 5 gates](images/roadmap.png)

Phases 0 to 2 cost about SAR 230K on the lean plan and end with a yes/no answer from real customers; phases 3 and 4 are only funded if two of three pilots sign.

**What each phase delivers**

- **0 Foundation (4 weeks):** decisions in the last section taken; senior CV engineer hired or contracted; lab built in the Riyadh office with 4 cameras and an NVR; RF-DETR + Supervision pipeline running on one Orin NX with zones and WhatsApp alerts; licence and PDPL review done; name chosen.
- **1 MVP build (12 weeks):** the five capabilities, rules engine, clip buffer, edge agent with remote updates, event API, WhatsApp/Telegram dispatcher, minimal web dashboard with zone editor and true/false feedback, daily summary. Runs for 4 weeks on the office cameras and one friendly client site (a Code-Ox Odoo customer with a restaurant or warehouse).
- **2 Pilots (8 weeks):** three free pilots in Riyadh, one each in restaurant, retail and logistics, with a simple offer (one area, two weeks, their cameras, they keep the findings). Measure false-alert rate, alerts acted on, and willingness to pay. Pricing tested here.
- **3 V1 + commercial launch (12 weeks):** PPE, forklift proximity, blocked exit, empty shelf, wet floor, cleaning rounds; Arabic/English dashboard, weekly reports, multi-site, roles, per-site plan billing in SAR; in-Kingdom hosting; field engineer hired; sales deck, brochure, website; first five paying sites.
- **4 Scale + V2 (20 weeks):** Odoo integration, scheduled visual checklists, heatmaps, dock dwell, fall detection validation, Android/iOS app, open API, reseller programme for the existing Odoo partner network; 15 paying sites, and a decision on raising money or staying bootstrapped.

## Team, skills and dependencies

The one hire that matters is a senior computer-vision engineer who has shipped a multi-camera pipeline to production; everything else Code-Ox already has. Without that person the team will spend months rediscovering decode bottlenecks, tracker drift and TensorRT export quirks.

**Roles**

| Role | Who | Responsibilities | Must-have skills |
| --- | --- | --- | --- |
| Product owner and Saudi lead | Shabeeb | Use cases, pilots, pricing, customer feedback loop, site surveys for the first 10 sites | Already in place |
| Senior CV / ML engineer (hire) | India, full-time or 6-month contract | Pipeline architecture, model selection and fine-tuning, TensorRT/DeepStream, accuracy targets | PyTorch, ONNX/TensorRT, RTSP/GStreamer, ByteTrack-class tracking, has deployed on Jetson |
| Mid CV engineer (hire or upskill) | India | Dataset building, labelling pipeline, training runs, evaluation, per-site tuning | Python, detection fine-tuning, CVAT/Roboflow |
| Backend engineers ×2 | Existing Code-Ox devs | Rules engine, event API, dispatcher, multi-tenant data model, billing, edge agent | Python/FastAPI, PostgreSQL, MQTT, Docker |
| DevOps / MLOps | Existing, part-time | Edge image, fleet updates, monitoring, in-Kingdom cloud, CI for model releases | Docker, Ansible/Balena-style fleet tools, Grafana |
| Frontend | Existing | Arabic/English dashboard, zone editor, reports, later mobile app | React, RTL layouts |
| QA | Existing, part-time | Test sites, recorded-video regression suite, false-alert tracking |  |
| Field / install engineer (month 4) | Riyadh hire | Site surveys, NVR configuration, box install, first-line support, Arabic | ELV/CCTV networking, Hikvision/Dahua admin, driving licence |
| Sales and partnerships | Shabeeb + BDM, later Odoo partners | Pilots, pricing, reseller channel |  |

**Skills the current team should pick up before month 2**

- Reading and tuning RTSP streams (ffprobe, go2rtc), the vendor URL table in the CCTV section
- Running RF-DETR + Supervision locally and understanding confidence thresholds, zones and tracker IDs
- Exporting a model to TensorRT on Jetson and measuring frames per second per camera
- PDPL basics: what counts as personal data, retention, DPIA

**External dependencies**

| Dependency | Risk | Mitigation |
| --- | --- | --- |
| NVIDIA Jetson supply and price (doubled in July 2026) | Medium | Standardise the Tier M on an RTX 4060 mini-PC as well; keep Hailo-8 as a fallback |
| Meta WhatsApp Business API approval | Low | Apply in month 1; Telegram and email as fallback |
| In-Kingdom cloud provider onboarding (CNTXT, Oracle, SCCC need commercial agreements) | Medium | Start the paperwork in phase 1 so hosting is ready for launch |
| Model licences | Low if we stay on the Apache list | Licence check in code review; no Ultralytics code in the product repo |
| Hosted VLM API availability and price | Low | Abstract the VLM behind one interface; Qwen3-VL self-host path tested in phase 3 |
| Customer IT cooperation (VLAN access, firewall) | High per site | 4G router option; survey before quote; install guide for their IT |
| Labelled data for custom classes | Medium | Pilots are the data source; contract labellers; auto-label with Grounding DINO |
| Saudi camera-law retention rules and site classes | Medium | Legal review in phase 0; we never alter or delete the customer's recordings |

## Risks, compliance and go-to-market

The legal position is workable if we stay anonymous: counting, queues, PPE and safety alerts without identifying anyone rely on legitimate interest under PDPL, while face recognition is sensitive biometric data needing explicit consent and a DPIA. The commercial risk is bigger than the legal one: alerts that are wrong or ignored kill renewals, so false-alert rate is the product's main metric.

**Saudi rules that shape the product**

| Rule | What it says | What we do |
| --- | --- | --- |
| [PDPL](https://www.dlapiperdataprotection.com/index.html?c=SA&t=law) (SDAIA) | Images of people are personal data; biometrics are sensitive data needing explicit consent, a DPIA and a DPO; large-scale monitoring needs a DPIA; breach notice to SDAIA within 72 hours; fines to SAR 5M | No face or gait recognition by default; DPIA template per deployment; privacy notice the customer can post; raw frames kept hours, anonymised events 30 days ([Saipem KSA notice](https://www.saipem.com/sites/default/files/2025-04/Information%20notice%20Smart%20Cameras_Saudi%20Arabian%20Saipem%20Co%20Ltd_1.pdf) as a model) |
| [Security Surveillance Cameras Law](https://saudipedia.com/en/article/3315/government-and-politics/systems/law-of-the-use-of-security-surveillance-cameras-in-saudi-arabia) (MOI, 2022) | Cameras mandatory in malls, hotels, warehouses, clinics, restaurants, schools; banned in exam rooms, changing rooms, toilets, salons, guest rooms; signage required; retention \~90 days; footage leaves the site only with MOI/State Security approval; fines to SAR 20,000 for unlawful transfer | We never move, alter or delete recordings; we export only event metadata and short clips with the owner's written authority; prohibited zones excluded at survey; high-sensitivity sites (hospitals, government) run fully on-prem |
| Cross-border transfer (PDPL) | No blanket localisation for private data, but transfers need adequacy or Saudi standard clauses and a risk assessment | Pilots on UAE/EU hosting with clauses in the contract; move to in-Kingdom hosting at launch so the question goes away |
| [CST cloud framework](https://www.dlapiper.com/en/insights/publications/2021/04/saudi-arabia-releases-version-3-of-its-cloud-computing-regulatory-framework) | SaaS is a cloud service; government data must stay in KSA; subscribers must be told of offshore processing | Host on a CST-registered in-Kingdom provider; state hosting location in the contract |
| [SDAIA AI Ethics 2.0](https://gccbdi.org/legal-updates/saudi-data-and-artificial-intelligence-authority-reveals-ai-ethics-principles-20-ksa) | Risk-tiered; higher-risk systems need a responsible-AI owner and assessment | Keep to "limited risk" by avoiding identification; name an AI owner internally |

**Top risks**

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| False alerts make managers mute WhatsApp | High | Fatal for renewals | VLM second check on fuzzy events; per-rule cooldowns and daily caps; a 2-week tuning period in every contract; false-alert rate shown on the dashboard |
| Accuracy on bad cameras (fisheye, night IR, reflections) | High | Pilot fails | Survey grades each camera; price repositioning as an option; only promise use cases the camera supports |
| A local or foreign competitor undercuts us with a mature product | Medium | Lost deals | We win on WhatsApp + Odoo + Arabic + price transparency + Code-Ox's existing customer base |
| Edge box dies in a hot cabinet, nobody notices | Medium | Silent outage, churn | Heartbeat alerts to Code-Ox ops; fanned or industrial enclosures; spare box per 10 sites |
| Customer IT refuses network access | Medium per site | Install stalls | 4G router option; one-page IT guide; outbound-only design |
| Key engineer leaves | Medium | Months lost | Two CV engineers, documented pipeline, recorded-video regression tests |
| Licence slip (AGPL code in product) | Low | Legal exposure | Approved-library list, licence scan in CI |
| Cash: build runs past 6 months | Medium | SAR 50 to 100K extra | Gate 2 is a hard stop; MVP scope frozen at the five capabilities |

**Go-to-market**

| Element | Plan |
| --- | --- |
| Beachhead | Riyadh restaurants and F&B groups first (Code-Ox has PATIQ and Odoo F&B clients, hygiene and queue use cases need no training), then logistics yards and retail chains |
| Offer | Copy the pilot: one area, two weeks, their cameras, free, they keep the report. Convert to annual contract |
| Pricing | Per-site plans, not per camera: SAR 299 (up to 4 cameras), 499 (8), 899 (16), 1,499 (32), two months free on annual prepay, plus a one-time setup of SAR 1,500 to 4,000 that covers the box and install day. Published on the website, unlike every competitor. US vendors sit at [$20 to 100 per camera per month](https://getsafeandsound.com/blog/spot-ai-pricing/); we land at $13 to 20 per camera equivalent with no hardware mark-up |
| Add-ons | Custom detection class: SAR 5,000 one-time; Odoo integration: SAR 3,000; second and later sites of the same brand get half-price setup; extra camera repositioning: cost plus 20% |
| Channels | Direct in Riyadh (Shabeeb, door-to-door); Code-Ox Odoo customers as warm leads; Odoo partners and CCTV integrators as resellers at 15 to 20% from phase 4 |
| Proof | Office demo site live on a public link; two case studies with real numbers from the pilots; loss calculator on the website |

## Decisions needed and open questions

Five decisions unlock phase 0; the rest can wait for the pilots.

**Decide now**

- [ ] Go / no-go on the lean plan (SAR \~230K to reach gate 2) and who signs off the budget
- [ ] Lean (reassign 3 developers) or full (dedicated team) staffing
- [ ] Hire a senior CV engineer full-time, or contract one for 6 months to lead and train the team
- [ ] Product name and whether it sits under Code-Ox or the new Saudi entity
- [ ] Which friendly customer hosts the first live site after the office demo

**Open questions to answer during phase 0 and the pilots**

- [ ] Real camera counts per site on our pipeline for each hardware tier (benchmark, do not trust vendor figures)
- [ ] Actual false-alert rate per use case after two weeks of tuning; what rate customers tolerate
- [ ] Whether the SAR 299 to 1,499 per-site tiers hold in pilots, and which tier most buyers land on
- [ ] Which in-Kingdom cloud provider onboards a small company fastest (CNTXT, Oracle, SCCC, stc)
- [ ] Exact MOI retention and site-class requirements from the primary regulation text (the 90-day figure comes from an integrator summary)
- [ ] Whether a hosted VLM (data leaves KSA for a snapshot) is acceptable to pilot customers, or whether we need the self-hosted Qwen3-VL from day one
- [ ] Whether to build on Frigate as the recording layer or keep recording entirely on the customer's NVR (simpler, less liability)
- [ ] Android-first or iOS-first for the mobile app, based on pilot managers' phones

**Sources used for this plan**

[RF-DETR](https://github.com/roboflow/rf-detr) · [Ultralytics licence](https://www.ultralytics.com/license) · [Supervision](https://github.com/roboflow/supervision) · [Frigate](https://docs.frigate.video/frigate/hardware) · [NVIDIA DeepStream performance](https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_Performance.html) · [Jetson price increase](https://cnx-software.com/2026/07/22/nvidia-increases-the-price-of-jetson-modules-and-devkits-by-up-to-101) · [Hailo-8 benchmarks](https://wiki.seeedstudio.com/benchmark_of_multistream_inference_on_raspberrypi5_with_hailo8/) · [RTSP URL list](https://help.nsoft.vision/hc/en-us/articles/4411595651345-List-of-RTSP-URLs-of-security-camera-manufacturers) · [WhatsApp pricing](https://developers.facebook.com/docs/whatsapp/pricing) · [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing) · [AWS UAE GPU pricing](https://www.devzero.io/instances/aws/g6.xlarge) · [RunPod](https://www.runpod.io/gpu-cloud/pricing) · [India salary benchmarks](https://jobrise.io/en/blog/salary-benchmarks-india-2026/) · [PDPL summary](https://www.dlapiperdataprotection.com/index.html?c=SA&t=law) · [Camera law summary](https://saudipedia.com/en/article/3315/government-and-politics/systems/law-of-the-use-of-security-surveillance-cameras-in-saudi-arabia) · [Spot AI pricing](https://getsafeandsound.com/blog/spot-ai-pricing/) · [Coram AI](https://us.fitgap.com/products/032483/coram-ai) · [Lumeo pricing](https://lumeo.com/pricing) · [RIME funding](https://bridgemena.com/news/saudi-based-rime-secures-over-2-million-seed-round-to-advance-ai-powered-enterprise-surveillance-solutions)
