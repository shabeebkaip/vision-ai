## Phase 11 — Office demo, friendly site and pilots (week 4, weeks 13 to 16, weeks 17 to 24)

About 25 days of PO, FLD and developer time. Three steps of growing realism: the office cameras (week 4), one friendly existing client for four weeks (weeks 13 to 16), then three free pilots at new customers (weeks 17 to 24). **Ramadan 2027 runs roughly 8 February to 9 March**, so the friendly site starts before it, and pilot installs are booked for the week after Eid al-Fitr (mid-March); Ramadan night trading at the friendly restaurant is a useful stress test.

**What we measure at every pilot**

| Measure | How | Target to convert |
| --- | --- | --- |
| Alerts marked "Correct" | WhatsApp buttons and dashboard feedback | 80% or more |
| Alerts acted on | Manager replied, or the situation cleared within 10 minutes of the alert | 50% or more |
| Missed events reported | Manager tells us, or found in spot checks | Under 2 per week per site |
| Manager rating | 1 to 5 at the end of the pilot | 4 or more |
| Willingness to pay | Asked at the stated per-site plan price | Signs or names a price within 20% |

| ID | Task | Owner | Days | Pri | Needs | Done when |
| --- | --- | --- | --- | --- | --- | --- |
| PIL-01 | Office demo (week 4): prototype services running on a laptop against the office cameras; Telegram (and WhatsApp if approved) alerts for queue, zone occupancy and after-hours; written 10-minute demo script | PO, LD | 1 | Must | EDG-01, SET-11 | Demo given to Code-Ox management |
| PIL-02 | Sales demo kit: 2-minute demo video in English and Arabic, a read-only demo organisation on staging, loss calculator sheet per industry, one-page brochure | PO | 2 | Must | PIL-01 | Kit used in the first three prospect meetings |
| PIL-03 | Friendly site agreement (weeks 10 to 12): an existing Code-Ox client, restaurant or warehouse; 4 weeks free; consent letter, signage, named manager as alert recipient | PO | 1 | Must | SEC-05 | Agreement signed |
| PIL-04 | Friendly site installation (week 13): survey with the checklist, box installed, cameras added, zones and rules from the industry template, field acceptance script run | FLD, PO | 1 | Must | HW-05, QA-14 | Acceptance sheet signed by the client |
| PIL-05 | Friendly site operation (weeks 13 to 16): weekly review call, tuning of thresholds and zones, every miss and false alert fed into the video library | PO, CV | 0.5 per week | Must | PIL-04 | Four weekly reviews held; scorecard trending up |
| PIL-06 | Pilot offer and agreement template (English and Arabic): one area, two weeks, free, on the customer's cameras, they keep the final report; conversion terms on the per-site plans and setup fee | PO | 1 | Must | SEC-05 | Lawyer-approved template |
| PIL-07 | Pilot pipeline: shortlist and book three pilots (restaurant, retail, logistics) from the Code-Ox Odoo client base and network; install dates after Eid al-Fitr | PO | 2 | Must | PIL-02 | Three signed pilot agreements with dates |
| PIL-08 | Pre-pilot survey per site: remote first (camera list, NVR model, photos of each view), then a site visit with the survey checklist; camera suitability check (DET-07) | FLD | 0.5 per site | Must | DET-07 | Survey report says which use cases each camera supports |
| PIL-09 | Pilot install and tuning per site: day 1 install and acceptance, days 2 to 4 tuning with the customer, days 5 to 14 measured run | FLD, CV | 2 per site | Must | PIL-08 | Measured run completed at all three sites |
| PIL-10 | Pilot measurement dashboard: the five measures above per pilot, filled automatically from events and feedback | BE | 1.5 | Must | CLD-11 | Numbers available daily during pilots |
| PIL-11 | Pilot final report generator: automatic PDF in English and Arabic with findings (busiest hours, longest queues, unattended periods, after-hours events, compliance gaps) for the customer to keep | BE | 2 | Must | CLD-14 | Report handed over at each pilot close |
| PIL-12 | Conversion meeting per pilot: present the report, offer the plan, record the outcome and objections | PO | 0.5 per site | Must | PIL-11 | Outcome recorded in the CRM |
| PIL-13 | Gate 2 decision meeting (week 24): did at least 2 of 3 pilots convert? Approve or stop V1 build, field engineer contract renewal, in-Kingdom hosting and hardware stock | PO + management | 0.5 | Must | PIL-12 | Written decision |
| PIL-14 | Two case studies with real numbers (with customer permission), English and Arabic, for the website and sales | PO | 2 | Should | PIL-12 | Published |

---
Full plan: [docs/development-task-plan.md](../../docs/development-task-plan.md) · All tasks as CSV: [tasks/tasks.csv](../tasks.csv)
