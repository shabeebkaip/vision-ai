## Phase 6 — Detection use cases (MVP weeks 3 to 14, V1 weeks 18 to 32)

About 18 developer-days for the MVP set and 46 for the V1 set (CV and LD). Every use case is a combination of a model and a rule type from Phase 3, delivered with its test clips and an agreed pass mark. The MVP set needs **no training**: it uses the standard pretrained person and vehicle detector. The V1 set needs fine-tuned models (Phase 7) or the vision-language check (CLD-12).

**Pass marks, measured by the harness (VID-05) on the test library and on the 7-day office soak**

| Level | Caught (recall) | False alerts | Alert delay |
| --- | --- | --- | --- |
| MVP use case | 90% or more of expected events | No more than 1 per camera per 24 h | Under 60 s after the condition is met |
| V1 use case | 85% or more | After the AI check, 80% or more of alerts marked "Correct" by managers | Under 90 s (AI check included) |

**MVP set (pretrained detector, no training)**

| ID | Use case | Industries | How it works | Days | Pri | Needs | Pass mark |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DET-01 | People count and zone occupancy | Retail, clinics, hotels, restaurants | Person detector + tracker + `zone_occupancy_over` | 2 | Must | EDG-09 | MVP marks on 10 clips |
| DET-02 | Queue length and estimated wait | Tills, pharmacy, check-in, food counters | `queue_length_over` + average dwell of people leaving the queue zone | 3 | Must | EDG-09 | Count within ±1 person 90% of the time; MVP marks |
| DET-03 | Unattended station | Cashier, reception, kitchen station, security post | `zone_empty` with schedule | 2 | Must | EDG-09 | MVP marks, including staff briefly stepping out (must not fire under the minimum time) |
| DET-04 | After-hours presence | Every industry | `presence_after_hours` with site opening hours | 2 | Must | EDG-09 | MVP marks, night IR clips included |
| DET-05 | Footfall in and out | Retail entrances, malls, clinics | `line_crossing` counting per direction, per-minute aggregates | 3 | Must | EDG-10 | Daily count within 5% of a manual count on 2 hours of footage |
| DET-06 | Loitering and dwell | Back doors, cash office, docks, car parks | `dwell_over` for people or vehicles | 2 | Must | EDG-09 | MVP marks |
| DET-07 | Camera suitability check | All (installer tool) | From a 2-minute sample: median person height in pixels, lighting, fps achieved; warns if people are under 40 px tall or fps under target | 2 | Must | EDG-05 | Correctly warns on the far-away and fisheye test cameras |
| DET-08 | Industry rule templates | All | Ready-made rule sets for restaurant, retail, clinic, hotel, warehouse, factory, each with sensible thresholds and schedules, in English and Arabic | 2 | Must | WEB-09 | A new restaurant site is configured from its template in under 15 minutes |

**V1 set (fine-tuned models or AI check)**

| ID | Use case | Industries | How it works | Days | Pri | Needs | Pass mark |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DET-10 | Helmet and high-vis vest missing | Manufacturing, logistics, construction | RF-DETR Small fine-tuned on public PPE data plus our footage (classes: person, helmet, no-helmet, vest, no-vest); rule fires when a person in a PPE zone is without the item for 5 s; AI check on the crop | 6 | Should | ML-05 | V1 marks |
| DET-11 | Hairnet, gloves and uniform in kitchens | Restaurants, central kitchens, food factories | Fine-tuned head/hand classes plus AI check; compliance log per shift for municipality inspections | 6 | Should | ML-05 | V1 marks |
| DET-12 | Forklift too close to a person | Warehouses, factories | Fine-tuned forklift class; distance between boxes; optional 4-point floor calibration to measure metres; near-miss logged with clip | 6 | Should | ML-05 | V1 marks; no alert for a driver on his own forklift |
| DET-13 | Blocked aisle or fire exit | Warehouses, retail, hotels, hospitals | Object present in an exit zone for more than N minutes (boxes, pallets, trolleys) + AI check "is the exit path blocked?"; auto-clears when free | 4 | Should | CLD-12 | V1 marks |
| DET-14 | Empty shelf / gap on display | Supermarkets, pharmacies | Scheduled snapshot of shelf zones every 15 minutes during opening hours, AI check "are there visible empty gaps?"; later a fine-tuned gap detector | 5 | Should | CLD-12 | 80% of gaps flagged within 30 minutes; false alerts under 2 per shelf camera per day |
| DET-15 | Wet floor or spill | Supermarkets, malls, hotels, hospitals | Change detection on floor zones when no person is present + AI check; lower expectations documented | 5 | Should | CLD-12 | Recall 70%+ on spill clips; reported to customers as "assist", not guaranteed |
| DET-16 | Table needs clearing | Restaurants, cafés, food courts | Table zone empty of seated people for 2 minutes + AI check "dishes or rubbish left on the table?" | 3 | Should | CLD-12 | V1 marks |
| DET-17 | Cleaning round done | Restaurants, malls, hospitals, hotels | Person with mop or cleaning trolley present in a zone within each scheduled window; missed round alerts; compliance report | 4 | Should | ML-05 | V1 marks on staged cleaning clips |
| DET-18 | Dock dwell and truck waiting | Warehouses, distribution centres | Truck or van in a dock zone; dwell time per door per visit; alert when over the target | 3 | Should | DET-06 | Dwell within ±2 minutes of manual timing |
| DET-19 | Vehicle in pedestrian zone | Warehouses, factory yards, car parks | Vehicle class inside a pedestrian-only zone | 2 | Should | EDG-09 | V1 marks |
| DET-20 | Detection scorecard per customer | All | Monthly per-site precision and recall estimate from feedback, shown to the customer and to Code-Ox | 2 | Should | CLD-11 | Visible on the site overview |

---
Full plan: [docs/development-task-plan.md](../../docs/development-task-plan.md) · All tasks as CSV: [tasks/tasks.csv](../tasks.csv)
