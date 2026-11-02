## Phase 2 — Video test library and evaluation harness (weeks 1 to 4, then ongoing)

All Must, about 16 developer-days plus PO time to collect and stage footage. This is our test suite: a folder of real CCTV clips, each with the alerts it should and should not produce, and one command that scores the whole system against them. It is built first so every later change is measured, and it grows every week from office recordings, client footage and every pilot mistake.

**What a test clip carries (manifest entry)**

```yaml
- id: rest-queue-001
  file: s3://cv-test-videos/rest-queue-001.mp4
  source: friendly-client-A (consent letter on file)
  scene: restaurant counter
  angle: ceiling corner, 3 m
  lighting: day
  resolution: 1280x720
  fps: 10
  duration_s: 300
  zones:
    counter_queue: [[0.12,0.55],[0.48,0.52],[0.52,0.95],[0.10,0.98]]
  rules: [queue_length_over]          # rules to run on this clip
  expected:
    - rule: queue_length_over
      start_s: 84
      end_s: 190
      tolerance_s: 15
  must_not_fire: [after_hours_presence]
  notes: thobes and abayas, glass reflection on left
```

**Minimum library before each gate**

| Gate | Clips | Mix |
| --- | --- | --- |
| Office demo (week 4) | 30 | 5 MVP rule types × 3 positive + 3 negative |
| MVP done (week 16) | 80 | Plus night/IR, crowded, overhead fisheye, reflections, 2 real client sites |
| V1 launch (week 38) | 200+ | Every V1 detection × 10 positive + 10 hard negatives, every pilot site represented |

| ID | Task | Owner | Days | Needs | Done when |
| --- | --- | --- | --- | --- | --- |
| VID-01 | Write the clip catalogue: for each MVP and V1 rule type, the positive scenes, the hard negatives (looks similar but must not fire) and the conditions to cover (day, night IR, crowded, empty, overhead, side angle, glass reflections) | PO, CV | 1 |  | Catalogue table in `test-videos/README.md` |
| VID-02 | Manifest schema (above) as a pydantic model in `shared/`, with validation in CI | LD | 0.5 | REP-04 | A malformed manifest entry fails CI |
| VID-03 | Clip storage: private bucket `cv-test-videos` on MinIO (dev) and S3-compatible storage (staging), `make fetch-videos` downloads with checksums; clips never committed to Git | DO | 0.5 | SET-09 | A new developer fetches all clips with one command |
| VID-04 | Staged office recordings: write a short script per scenario and act it out on the office cameras (queue forming and clearing, entering a restricted zone, loitering, after-hours entry, line crossing in both directions, helmet and vest on/off, hairnet on/off, boxes blocking an exit, wet-floor sign). Buy props: 3 helmets, 3 high-vis vests, hairnets, gloves, wet-floor sign, cardboard boxes (about SAR 400) | PO, QA | 3 | SET-11 | 40 staged clips recorded at 720p sub-stream and 1080p main stream |
| VID-05 | Evaluation harness `ml/eval/run.py`: runs the real edge pipeline on each clip through a file source (same code path as live), collects events, matches them to `expected` within tolerance, and reports per rule type: caught, missed, false alerts, precision, recall, false alerts per camera-hour, alert delay, and frames per second processed. Outputs JSON plus a Markdown scorecard and a diff against the last baseline | LD, CV | 4 | VID-02, EDG-09 | `/test-videos` prints the scorecard for all clips in under 15 minutes on a laptop |
| VID-06 | Event-marking tool `ml/tools/mark_events.py`: play a clip, press keys to mark event start/end per rule, draw zones with the mouse, write the manifest entry | CV | 1.5 | VID-02 | Marking a 5-minute clip takes under 10 minutes |
| VID-07 | Client footage intake: receive files, check consent letter, convert to 720p H.264 at 10 fps with FFmpeg, cut into 2 to 10 minute clips, mark events, upload | QA | 2 | SET-15, VID-06 | Clips from at least 2 client sites in the library |
| VID-08 | Public footage, licence-checked: free commercial-use stock CCTV-style videos (e.g. Pexels) for variety; academic datasets (MOT, VIRAT) only if their licence allows commercial evaluation, otherwise skipped | CV | 1 | VID-02 | Each external clip has its licence recorded in the manifest |
| VID-09 | Saudi-specific coverage: people in thobes, abayas and niqab, families with children, prayer-time empty stores, Ramadan night crowds, mirrored shop fronts, harsh midday sun through glass | PO, QA | 1 | VID-04 | At least 15 clips tagged `saudi-context` |
| VID-10 | Baseline and regression thresholds: record the first baseline; the nightly run fails if any rule's recall drops more than 3 points or false alerts per camera-hour rise more than 20% | LD | 0.5 | VID-05, REP-06 | A deliberately broken threshold turns the nightly run red |
| VID-11 | Library privacy: access limited to the dev team, consent letters linked per source, deletion on client request within 7 days, an optional face-blur script for clips used in sales demos | DO, PO | 1 | VID-03 | Access list and deletion runbook in `docs/` |
| VID-12 | Ongoing intake (weekly, from week 13): every confirmed miss and every false alert from the friendly site and pilots becomes a new clip with expected results | QA | 0.5/week | PIL-05 | Library grows every week; scorecard trend tracked |

---
Full plan: [docs/development-task-plan.md](../../docs/development-task-plan.md) · All tasks as CSV: [tasks/tasks.csv](../tasks.csv)
