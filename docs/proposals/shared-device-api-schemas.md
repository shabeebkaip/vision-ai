# Proposal: device API schemas in `shared/` (for REP-04 owners; needed by EDG-12, EDG-13, EDG-10)

- Raised by: CLD-01..05 (cloud backend)
- Status: proposed — no change made to `shared/` in that pull request

The cloud backend uses `vision_shared.schemas.Event` and `SiteConfig` unchanged as the edge
contract. The rest of the device API has no shared types yet, so the cloud defines them in
`cloud/src/vision_cloud/contract.py`. The edge uploader (EDG-12) and agent (EDG-13) must speak the
same messages, so they should move to `shared/`. Field names below are already what the cloud
accepts and returns.

## 1. New module `shared/src/vision_shared/device_api.py`

Move these models from `vision_cloud/contract.py` unchanged (all `extra="forbid"`, timestamps
timezone-aware):

| Model | Direction | Used by |
| --- | --- | --- |
| `EnrolmentRequest` `{token, name, hardware_tier?, software_version?}` | edge → cloud | EDG-13 |
| `EnrolmentResponse` `{device_id, site_id, credential}` | cloud → edge | EDG-13 |
| `CameraHealth` `{camera_id, online, fps?, resolution?, codec?, last_frame_at?, error?}` | edge → cloud | EDG-02 health, EDG-13 |
| `Heartbeat` `{sent_at, software_version, model_version?, applied_config_version?, uptime_s?, cpu_percent?, gpu_percent?, ram_percent?, disk_percent?, temperature_c?, outbox_pending?, cameras[]}` | edge → cloud | EDG-13 |
| `HeartbeatResponse` `{server_time, config_version?, logs_requested}` | cloud → edge | EDG-13 |
| `UploadTarget` `{method, url, fields, key, expires_at, max_bytes}` | cloud → edge | EDG-12 |
| `EventReceipt` `{event_id, status: created\|updated\|duplicate, snapshot_upload?, clip_upload?}` | cloud → edge | EDG-12 |
| `EventBatch` `{events: [Event]}`, `EventBatchReceipt` `{receipts[], rejected[]}`, `RejectedItem` | both | EDG-12 |
| `MediaKind`, `MediaFinalised` | cloud → edge | EDG-12 |
| `AggregateMinute`, `AggregateBatch`, `AggregateReceipt` | edge → cloud | EDG-10, EDG-12 |
| `ModelReleaseInfo`, `LogUploadRequest`, `LogUploadResponse` | both | EDG-13, ML-08 |

`EventBatch.events` is typed `list[dict]` in the cloud so a bad item is rejected on its own instead
of failing the whole batch; in `shared/` it can be `list[Event]` for the edge side, with the cloud
keeping its lenient parsing.

## 2. Small changes to existing schemas

1. **`Event.snapshot_key` / `Event.clip_key` meaning.** Today the edge fills them with local outbox
   paths (`media/<id>.jpg`). The cloud treats them only as "media exists" and assigns its own
   storage key. Proposal: document this in the field descriptions (no type change), or rename to
   `has_snapshot: bool` / `has_clip: bool` in schema 1.1. Recommendation: document now, rename
   with the next breaking change.
2. **`Event.id` must be a UUID.** It is generated as `uuid4()` but typed `str`, so other strings
   pass validation on the edge and are only rejected by the cloud (`invalid_id`). Proposal: type
   it `uuid.UUID` (serialises to the same JSON) or add a validator.
3. **`SiteConfig.version`** is now the cloud's config version (monotonic per site). The edge
   should echo it in `Heartbeat.applied_config_version`; no change needed beyond a docstring.
4. **`SCHEMA_VERSION`**: bump to `"1.1"` when (1) or (2) lands; the cloud stores the version sent
   with each event.

## 3. Generated JSON Schema / TypeScript (REP-04)

When the device models move, add them to the JSON Schema and TypeScript generation so the
dashboard and any non-Python tooling see the same types.

## Migration plan

1. PR in `shared/`: add `device_api.py` (copy of `contract.py`), tests.
2. Same PR: `vision_cloud.contract` becomes `from vision_shared.device_api import *` (one line),
   and the edge starts importing from `vision_shared.device_api` in EDG-12/EDG-13.
