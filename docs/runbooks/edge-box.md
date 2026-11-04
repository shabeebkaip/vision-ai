# Connecting an edge box to the cloud

How a box is enrolled, kept in sync and supervised (EDG-12, EDG-13). Packaging for Jetson and
mini-PC images is HW-*.

## Processes on a box

| Process | Command | What it does |
| --- | --- | --- |
| Agent (one per box) | `vision-edge agent` | Heartbeat every 60 s (CPU, RAM, disk, temperature, uptime, cameras, versions, outbox backlog); pulls the site config when the cloud's ETag changes and writes `state/site.json` |
| Camera (one per camera) | `vision-edge run --camera <id>` | Reads `state/site.json`, runs the pipeline, reloads the config when the file changes, uploads events through its outbox |

They share `VISION_STATE_DIR` (default `var/state`):

```
state/device.json            cloud URL, device id, site id, device token (mode 0600)
state/site.json              site config from the cloud (written atomically)
state/site.etag
state/status/<camera>.json   per-camera status, read by the agent for the heartbeat
```

## First start

1. In the dashboard (or `POST /api/v1/sites/{site}/devices`), create a device for the site. The
   one-time enrolment token is shown once and expires after 24 hours.
2. On the box:

   ```bash
   vision-edge enrol cxe_... --cloud-url https://api.vision.code-ox.com
   vision-edge agent --once        # first heartbeat and config pull; prints the config version
   vision-edge agent               # keep running (supervised)
   vision-edge run --camera <camera-id>   # one per camera (supervised)
   ```

   Camera ids are the cloud's ids, from `state/site.json`.

## Changing things in the cloud

- **Rules, zones, lines, schedules:** the agent sees the new ETag at its next heartbeat (within
  60 s), writes the file, and each camera process applies it within 2 s without restarting.
  Rules that did not change keep their timers and open alerts; an open alert whose rule changed or
  was removed is closed as "cleared" (`attributes.cleared_by = "config_change"`).
- **A camera's stream URL or fps:** the camera process exits with code 3 and its supervisor
  (Docker restart policy, systemd) starts it again with the new stream.

## When the link is down

- The agent keeps the last config and retries every interval.
- Camera processes keep detecting and queue events in their outbox; nothing is lost. Clips beyond
  the quota are dropped oldest first; events never.
- `vision-edge upload --once --outbox <dir>` reports what is still waiting.

## Revoked or wrong token

The agent and uploaders log `unauthorised` and keep retrying at the longest backoff. Create a new
device in the cloud and run `vision-edge enrol` again.
