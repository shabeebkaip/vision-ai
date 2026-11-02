# ADR 003: No face recognition or identity tracking

Status: accepted (2 Nov 2026)

**Decision.** The product never recognises, embeds, matches or re-identifies faces or people.
Tracker ids are anonymous, in memory only, and reset when a track ends. Reports name a zone and a
role, never a person.

**Why.** Under PDPL, biometric data is sensitive data needing explicit consent, a DPIA and a DPO;
that is impractical for shoppers and patients. Operational alerts do not need identity. "We never
identify anyone" is also a selling point.

**Consequences.** Use cases that need identity (staff attendance, VIP recognition) are out of scope.
