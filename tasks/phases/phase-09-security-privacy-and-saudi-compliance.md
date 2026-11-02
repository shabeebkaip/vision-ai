## Phase 9 — Security, privacy and Saudi compliance (weeks 4 to 16, launch check in week 36)

About 16 developer-days plus external legal and penetration-test work. Three promises drive this phase, and every one is enforced in code and written in the customer contract: **we never identify people** (no face recognition, no identity tracking), **video never leaves the customer's building** except short event clips the owner has authorised, and **the customer's own recordings are never touched** (we only read the stream; we never alter, delete or export NVR footage).

**Data retention defaults (customer can shorten; plan sets the maximum)**

| Data | Where | Default retention |
| --- | --- | --- |
| Live frames | Box memory only | Seconds, never stored |
| Rolling clip buffer | Box RAM disk | 30 seconds |
| Snapshots on the box | Box disk | 24 hours |
| Event clips | Cloud storage | 30 days (7 to 90 by plan) |
| Event snapshots | Cloud storage | 90 days |
| Events and feedback | Database | 12 months |
| Per-minute counts | Database | 3 years (no personal data) |
| Application logs | Log store | 90 days, personal data masked |

| ID | Task | Owner | Days | Pri | Needs | Done when |
| --- | --- | --- | --- | --- | --- | --- |
| SEC-01 | Threat model: what we protect (camera passwords, clips, events, device and user tokens), who might attack, how; mitigations mapped to tasks | LD, DO | 1 | Must |  | `docs/security/threat-model.md` reviewed |
| SEC-02 | Camera passwords and other customer secrets encrypted at rest with a key held outside the database; never written to logs | BE | 1 | Must | CLD-01 | Database dump shows no readable camera password |
| SEC-03 | Transport security: TLS on every connection; per-device credentials, rotated every 90 days; revoking a device cuts it off within 1 minute | BE, DO | 1 | Must | CLD-04 | Revoked test device is refused |
| SEC-04 | Retention jobs implementing the table above, per organisation settings, with deletion logs | BE | 1 | Must | CLD-06 | Retention test with a shortened clock passes |
| SEC-05 | PDPL document pack with a Saudi lawyer: customer privacy notice and signage text (Arabic and English), data-protection impact assessment template per deployment, data processing agreement (Code-Ox as processor), records of processing, data-subject request procedure, breach plan with 72-hour notice to SDAIA | PO + lawyer | 3 (+ external) | Must |  | Pack signed off by the lawyer before the first pilot |
| SEC-06 | Camera-law checklist built into the installer flow: signage present, no analysis of cameras in prohibited areas (changing rooms, toilets, clinical exam rooms, prayer rooms where applicable), site sensitivity class recorded, owner's written authority for clip upload | PO, FLD | 1 | Must | WEB-07 | A site cannot be activated until the checklist is complete |
| SEC-07 | No-face-recognition guarantee in code: face and re-identification models on the banned list, CI check, statement in the contract and on the website | LD | 0.5 | Must | REP-07 | CI blocks a test pull request adding a face model |
| SEC-08 | Access review: least privilege everywhere, 2FA compulsory for Code-Ox staff, support view read-only and audited, admin actions audited | BE | 1 | Must | CLD-02, CLD-16 | Review checklist signed by LD |
| SEC-09 | Dependency and image scanning in CI: Dependabot, `pip-audit`, `npm audit`, Trivy on Docker images; high findings block release | DO | 1 | Must | REP-06 | Weekly scan report in the dev channel |
| SEC-10 | External penetration test of the cloud API, dashboard and one edge box before launch; fix all high and medium findings | PO (+ vendor), BE | 2 (fixes) | Should | LCH-02 | Report with high and medium findings closed |
| SEC-11 | Backups and disaster recovery: database recovery point 24 h, recovery time 4 h; quarterly restore drill | DO | 1 | Must | CLD-20 | First drill passed and documented |
| SEC-12 | Data location: production hosted in Saudi Arabia from launch (LCH-02); pilot contracts state hosting location; the AI check sends a zone snapshot to an external API, so it is disclosed in the processing agreement and every site has an "in-Kingdom only" switch that uses the self-hosted model or no AI check | BE, PO | 1 | Must | CLD-12 | Switch tested: no external API call from a site with it on |
| SEC-13 | Security incident runbook: who is called, how to cut a device or a key, customer and SDAIA notification steps | DO, PO | 0.5 | Must | SEC-05 | Tabletop drill run once |
| SEC-14 | Log hygiene: phone numbers, emails and names masked in logs; no snapshots or clips in logs | BE | 0.5 | Must | REP-10 | Log scan finds no unmasked phone numbers |
| SEC-15 | Responsible-AI note (SDAIA AI Ethics principles): named owner at Code-Ox, a one-page description for customers of what the system does, its limits, expected error rates and how humans stay in control | PO, CV | 0.5 | Should | DET-20 | Published on the website and attached to contracts |

---
Full plan: [docs/development-task-plan.md](../../docs/development-task-plan.md) · All tasks as CSV: [tasks/tasks.csv](../tasks.csv)
