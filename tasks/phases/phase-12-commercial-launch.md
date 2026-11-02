## Phase 12 — Commercial launch (weeks 25 to 38)

About 37 days of developer, DO and PO time, started only after gate 2 (two of three pilots convert). This phase turns a working system into a business: production hosting inside Saudi Arabia, monitoring with someone on call, billing that produces ZATCA-compliant invoices, a repeatable installation, support, the website and contracts. V1 detections (Phase 6) are built in parallel by CV and LD.

**Customer journey the launch must support**

Signed contract → organisation created and owner invited → remote then on-site survey → box prepared and shipped → one-day installation and acceptance → 2-week tuning period → live, first invoice → monthly summary and support.

| ID | Task | Owner | Days | Pri | Needs | Done when |
| --- | --- | --- | --- | --- | --- | --- |
| LCH-01 | Choose the in-Kingdom cloud (Google Cloud Dammam via CNTXT, Oracle Riyadh, Alibaba/SCCC, stc cloud, or the AWS Saudi region if live) on price, onboarding time and services; sign the agreement | PO, DO | 2 | Must | PIL-13 | Account open, agreement signed |
| LCH-02 | Production environment in that cloud, written as infrastructure code (OpenTofu): database with automated backups, object storage with lifecycle rules, Redis, container hosting for API, worker and web, separate production account and keys, staging kept separate | DO | 5 | Must | LCH-01 | Production stack rebuilt from code in under 2 hours |
| LCH-03 | Monitoring and on-call: metrics, logs and uptime checks for cloud and fleet (internal tools such as Prometheus, Grafana, Loki, Uptime Kuma); alerts to the ops Telegram group; on-call rota between LD, BE and DO | DO | 3 | Must | LCH-02 | A staged outage pages the on-call person within 5 minutes |
| LCH-04 | Billing through Code-Ox's own Odoo instead of building it: per-site plan products (Starter, Standard, Business, Enterprise), monthly and annual subscriptions, setup fee, ZATCA e-invoices; card payments through a Saudi gateway (e.g. Moyasar or HyperPay) or bank transfer; subscription status synced to the platform (active, grace, suspended) | BE | 4 | Must | CLD-18 | Test customer invoiced, paid, and suspended after the grace period, all automatically |
| LCH-05 | Plan management in the admin console: assign plan, upgrade or downgrade, grace period, suspension that stops alerts but keeps data for 30 days | BE | 1.5 | Must | LCH-04 | Plan change takes effect within 5 minutes |
| LCH-06 | Onboarding tracker in the admin console: each stage of the customer journey above with owner and date, visible to PO and FLD | BE, FE | 2 | Must | WEB-15 | First 5 customers tracked through it |
| LCH-07 | Installer kit and guide (English and Arabic, printed and PDF): survey steps, NVR sub-stream settings for Hikvision, Dahua and Uniview, network rules for the customer's IT team (one outbound HTTPS rule), box placement and cooling, enrolment, acceptance; plus a one-page sheet for the customer's IT | FLD, PO | 3 | Must | HW-05, QA-14 | A second installer completes a site from the guide alone |
| LCH-08 | Field engineer: hired by week 14, trained on the friendly site and the three pilots, then installs independently | PO | 1 | Must |  | Engineer completes a solo installation |
| LCH-09 | Support process: WhatsApp support number, hours (Sunday to Thursday, 9:00 to 18:00), tickets in Odoo Helpdesk, response times per plan, escalation to the developer on call | PO | 2 | Must | LCH-03 | First 20 tickets handled within the promised times |
| LCH-10 | Help centre in English and Arabic: how rules work, how to give feedback, what the AI check is, privacy questions, top 20 questions from pilots | PO | 2 | Must | PIL-12 | Published and linked from every alert's event page |
| LCH-11 | Product website (`vision.code-ox.com`): one page per industry, per-site pricing table, loss calculator, demo booking, privacy and responsible-AI page, case studies | FE, PO | 4 | Must | PIL-14 | Live with Arabic and English versions |
| LCH-12 | Contracts with the lawyer: subscription agreement, data processing agreement, service levels (99% cloud availability; faulty box replaced within 2 working days in Riyadh), hardware and setup-fee terms | PO + lawyer | 2 | Must | SEC-05 | Templates approved |
| LCH-13 | Hardware stock and logistics: initial stock of 5 tier-S and 3 tier-M boxes, spare pool, shipping to Jeddah and Dammam, return and replacement process | PO | 1 | Must | HW-12 | Stock in office, replacement process written |
| LCH-14 | Launch readiness review (week 36): penetration test closed, restore drill passed, on-call live, support ready, help centre live, 5 paying sites | PO, LD | 0.5 | Must | SEC-10, SEC-11 | Signed checklist |
| LCH-15 | Internal product analytics: active sites, alerts per site per day, feedback rate, false-alert rate, sites with no logins in 14 days (churn warning) | BE | 2 | Should | CLD-11 | Weekly product report to management |
| LCH-16 | Reseller programme basics: partner agreement, 25% partner discount, installer certification for partners using LCH-07 | PO | 2 | Should | LCH-07 | First partner signed |

---
Full plan: [docs/development-task-plan.md](../../docs/development-task-plan.md) · All tasks as CSV: [tasks/tasks.csv](../tasks.csv)
