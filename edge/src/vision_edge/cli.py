"""`vision-edge` command line.

vision-edge validate examples/office-demo/site.yaml
vision-edge run examples/office-demo/site.yaml --camera counter --detector replay
vision-edge detect-file clip.mp4 --out clip.detections.jsonl --fps 5
vision-edge check-camera rtsp://user:pass@192.168.1.64:554/Streaming/Channels/102
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

import cv2

from vision_edge.agent import Agent, CameraStatusFile, DeviceState, EnrolmentError, enrol
from vision_edge.config_watch import ConfigWatcher, RestartRequired
from vision_edge.detection import build_detector
from vision_edge.ingest import FileSource, open_source
from vision_edge.logs import configure_logging
from vision_edge.outbox import Outbox
from vision_edge.pipeline import CameraPipeline
from vision_edge.settings import EdgeSettings
from vision_edge.sinks import ConsoleSink, EventSink, OutboxSink, TelegramSink
from vision_edge.survey import format_report, survey_frames
from vision_edge.uploader import CloudClient, RetryLater, Uploader, UploaderThread
from vision_shared.io import load_site


def _open_outbox(settings: EdgeSettings, directory: Path) -> Outbox:
    return Outbox(
        directory,
        clip_quota_bytes=settings.outbox_clip_quota_mb * 1024 * 1024,
        retention_s=settings.outbox_retention_days * 24 * 3600,
    )


def _cloud_credentials(settings: EdgeSettings) -> tuple[str, str] | None:
    """Cloud URL and device token: from the environment, else from `vision-edge enrol`."""
    if settings.cloud_url and settings.device_token:
        return settings.cloud_url, settings.device_token.get_secret_value()
    device = DeviceState.load(settings.state_dir)
    if device is not None:
        return device.cloud_url, device.device_token
    return None


def _uploader(settings: EdgeSettings, outbox: Outbox) -> Uploader | None:
    """The cloud uploader, or None when no cloud is configured (local-only / offline mode)."""
    creds = _cloud_credentials(settings)
    if creds is None:
        return None
    client = CloudClient(*creds)
    return Uploader(outbox, client, batch_size=settings.upload_batch_size)


def _sinks(settings: EdgeSettings, outbox: Outbox, telegram: bool) -> list[EventSink]:
    sinks: list[EventSink] = [ConsoleSink(), OutboxSink(outbox.dir, outbox)]
    if telegram:
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            sys.exit("--telegram needs VISION_TELEGRAM_BOT_TOKEN and VISION_TELEGRAM_CHAT_ID")
        sinks.append(
            TelegramSink(settings.telegram_bot_token.get_secret_value(), settings.telegram_chat_id)
        )
    return sinks


def cmd_validate(args: argparse.Namespace) -> int:
    site = load_site(args.config)
    print(f"OK: site '{site.id}' with {len(site.cameras)} camera(s) and {len(site.rules)} rule(s)")
    for cam in site.cameras:
        rules = site.rules_for(cam.id)
        print(
            f"  camera {cam.id}: {len(cam.zones)} zone(s), {len(cam.lines)} line(s), {len(rules)} rule(s)"
        )
    return 0


def cmd_run(args: argparse.Namespace, settings: EdgeSettings) -> int:
    if args.config is None:  # the config the agent pulls from the cloud
        args.config = str(settings.state_dir / "site.json")
        if not Path(args.config).is_file():
            sys.exit(f"no site config at {args.config}: run `vision-edge agent` first")
    site = load_site(args.config)
    cameras = [site.camera(args.camera)] if args.camera else [c for c in site.cameras if c.enabled]
    if len(cameras) != 1:
        sys.exit("run one camera per process for now: pass --camera <id>")
    camera = cameras[0]
    source_str = args.source or camera.source
    if not source_str.startswith(("rtsp", "http")) and not Path(source_str).is_absolute():
        source_str = str((Path(args.config).parent / source_str).resolve())
    detector_kind = args.detector or (
        "replay" if source_str.endswith(".jsonl") else settings.detector
    )
    classes = {c for r in site.rules_for(camera.id) for c in r.classes}
    detector = build_detector(
        detector_kind,
        model=args.model or settings.model_path,
        threshold=settings.detector_threshold,
        classes=classes,
    )
    outbox_dir = Path(args.outbox or settings.outbox_dir)
    outbox = _open_outbox(settings, outbox_dir)
    pipeline = CameraPipeline(
        site=site,
        camera=camera,
        detector=detector,
        sinks=_sinks(settings, outbox, args.telegram),
        media_dir=outbox_dir / "media",
        clip_pre_s=settings.clip_pre_s,
        clip_post_s=settings.clip_post_s,
    )
    status = CameraStatusFile(settings.state_dir, camera.id)
    status.set_config_version(site.version)
    pipeline.after_frame.append(lambda _p, frame: status.mark_frame(frame.ts))
    if not args.no_watch:
        pipeline.after_frame.append(
            ConfigWatcher(Path(args.config), on_applied=status.set_config_version)
        )
    source = open_source(
        source_str, camera.id, camera.fps, max_seconds=args.max_seconds, video=args.video
    )
    uploader = _uploader(settings, outbox)
    thread = UploaderThread(uploader) if uploader else None
    if thread:
        thread.start()
    try:
        stats = pipeline.run(source)
    except RestartRequired as exc:
        print(f"restart needed: {exc}")
        return 3  # the supervisor (Docker restart policy) starts us again with the new config
    finally:
        if thread:
            thread.stop()
    print(
        f"done: {stats.frames} frames, {stats.seconds_of_video:.1f}s of video, {stats.events} event(s), "
        f"{stats.fps:.1f} frames/s; outbox: {outbox_dir}"
    )
    return 0


def cmd_upload(args: argparse.Namespace, settings: EdgeSettings) -> int:
    """Ship an outbox to the cloud: once (`--once`, exit 1 if anything is left) or keep running."""
    outbox = _open_outbox(settings, Path(args.outbox or settings.outbox_dir))
    uploader = _uploader(settings, outbox)
    if uploader is None:
        sys.exit("upload needs `vision-edge enrol` or VISION_CLOUD_URL and VISION_DEVICE_TOKEN")
    if args.once:
        try:
            res = uploader.drain()
        except RetryLater as exc:
            print(f"cloud unreachable: {exc}")
        else:
            print(f"sent {res.events_sent} event(s) and {res.media_sent} media file(s)")
        s = outbox.stats()
        print(
            f"pending: {s.pending_events} event(s), {s.pending_media} media; "
            f"refused: {s.failed}; dropped media: {s.dropped}"
        )
        return 1 if s.pending_events or s.pending_media else 0
    stop = threading.Event()
    try:
        uploader.run_forever(stop)
    except KeyboardInterrupt:
        stop.set()
    return 0


def cmd_enrol(args: argparse.Namespace, settings: EdgeSettings) -> int:
    cloud_url = args.cloud_url or settings.cloud_url
    if not cloud_url:
        sys.exit("enrol needs --cloud-url or VISION_CLOUD_URL")
    try:
        device = enrol(
            cloud_url, args.token, settings.state_dir, hardware_tier=settings.hardware_tier
        )
    except EnrolmentError as exc:
        print(f"FAIL: {exc}")
        return 1
    print(f"OK: enrolled as device {device.device_id} for site {device.site_id}")
    print(f"credentials saved to {DeviceState.path(settings.state_dir)}")
    return 0


def cmd_agent(args: argparse.Namespace, settings: EdgeSettings) -> int:
    device = DeviceState.load(settings.state_dir)
    if device is None:
        sys.exit("this box is not enrolled: run `vision-edge enrol <token> --cloud-url ...`")
    root = Path(settings.outbox_dir)
    outboxes = [root, *sorted(p for p in root.glob("*") if p.is_dir())] if root.is_dir() else []
    agent = Agent(settings.state_dir, device, outbox_dirs=outboxes)
    if args.once:
        agent.tick()
        config = agent.current_config()
        print(f"OK: heartbeat sent; config version {config.version if config else '-'}")
        return 0
    stop = threading.Event()
    try:
        agent.run_forever(stop, interval_s=args.interval or settings.heartbeat_interval_s)
    except KeyboardInterrupt:
        stop.set()
    return 0


def cmd_detect_file(args: argparse.Namespace, settings: EdgeSettings) -> int:
    """Run the detector once over a video and cache detections as JSONL for fast re-scoring."""
    classes = set(args.classes.split(",")) if args.classes else None
    detector = build_detector(
        args.detector or settings.detector, model=args.model or settings.model_path,
        threshold=args.threshold, classes=classes,
    )  # fmt: skip
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    t0 = time.perf_counter()
    with out.open("w", encoding="utf-8") as fh:
        for frame in FileSource(args.video, "file", fps=args.fps, max_seconds=args.max_seconds):
            dets = detector.detect([frame])[0]
            fh.write(
                json.dumps(
                    {
                        "t": round(frame.video_time_s, 3),
                        "w": frame.width,
                        "h": frame.height,
                        "detections": [d.model_dump(exclude={"track_id"}) for d in dets],
                    }
                )
                + "\n"
            )
            n += 1
    dt = time.perf_counter() - t0
    print(f"wrote {n} frames to {out} ({n / dt:.1f} frames/s with {detector.name})")
    return 0


def cmd_check_camera(args: argparse.Namespace) -> int:
    cap = cv2.VideoCapture(args.url, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        print("FAIL: cannot open stream (check URL, credentials, network, RTSP port)")
        return 1
    frames, t0 = 0, time.perf_counter()
    w = h = 0
    while time.perf_counter() - t0 < args.seconds:
        ok, img = cap.read()
        if not ok:
            break
        frames += 1
        h, w = img.shape[:2]
    cap.release()
    dt = time.perf_counter() - t0
    if frames == 0:
        print("FAIL: connected but no frames decoded (codec? sub-stream disabled?)")
        return 1
    print(f"OK: {w}x{h}, {frames / dt:.1f} fps received over {dt:.1f}s")
    if w < 640:
        print("WARN: resolution below 640 px wide; set the sub-stream to 1280x720 or 704x576")
    return 0


def cmd_survey(args: argparse.Namespace, settings: EdgeSettings) -> int:
    """Camera suitability check (DET-07) on a short sample of a stream or file."""
    kind = args.detector or ("replay" if args.source.endswith(".jsonl") else settings.detector)
    detector = build_detector(
        kind, model=args.model or settings.model_path, threshold=0.35, classes={"person"}
    )
    source = open_source(
        args.source, "survey", args.fps, max_seconds=args.seconds, video=args.video
    )
    frames = []
    dets = []
    t0 = time.perf_counter()
    for frame in source:
        frames.append(frame)
        dets.append(detector.detect([frame])[0])
        if time.perf_counter() - t0 >= args.seconds and args.source.startswith(("rtsp", "http")):
            break
    elapsed = frames[-1].video_time_s if frames else 0.0
    report = survey_frames(frames, dets, args.source, max(elapsed, 1e-6), args.fps)
    print(format_report(report))
    if args.json:
        Path(args.json).write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return 0 if report.verdict.value != "fail" else 1


def cmd_new_site(args: argparse.Namespace) -> int:
    """Starter site.yaml from an industry template (DET-08)."""
    from datetime import time as dtime

    import yaml

    from vision_shared.templates import OpeningHours, load_template, site_skeleton

    oh, om = (int(x) for x in args.open.split(":"))
    ch, cm = (int(x) for x in args.close.split(":"))
    data = site_skeleton(
        load_template(args.industry), args.site_id, args.camera, args.source,
        opening=OpeningHours(start=dtime(oh, om), end=dtime(ch, cm)), language=args.language,
    )  # fmt: skip
    text = (
        f"# Generated from the '{args.industry}' template. Reshape the placeholder zones in the\n"
        "# dashboard zone editor (or edit the 0-1 coordinates here), then: vision-edge validate <file>\n"
        + yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    )
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vision-edge", description="Code-Ox Vision edge pipeline")
    sub = p.add_subparsers(dest="command", required=True)

    v = sub.add_parser("validate", help="validate a site config")
    v.add_argument("config")

    r = sub.add_parser("run", help="run the pipeline for one camera of a site config")
    r.add_argument(
        "config", nargs="?", help="site config (default: the one the agent pulled, state/site.json)"
    )
    r.add_argument("--camera")
    r.add_argument(
        "--source", help="override the camera source (file, RTSP URL or detections JSONL)"
    )
    r.add_argument("--detector", help="replay | rfdetr-nano | rfdetr-small | ... | onnx")
    r.add_argument("--model", help="weights or ONNX path")
    r.add_argument(
        "--video", help="video to pair with a replayed detections JSONL (for snapshots/clips)"
    )
    r.add_argument("--max-seconds", type=float)
    r.add_argument("--outbox")
    r.add_argument("--telegram", action="store_true", help="also send alerts to Telegram")
    r.add_argument("--no-watch", action="store_true", help="do not reload the config on change")

    en = sub.add_parser("enrol", help="register this box with the cloud (EDG-13)")
    en.add_argument("token", help="one-time enrolment token from the dashboard")
    en.add_argument("--cloud-url")

    ag = sub.add_parser("agent", help="heartbeat and site config from the cloud (EDG-13)")
    ag.add_argument("--once", action="store_true", help="one heartbeat and config pull, then exit")
    ag.add_argument("--interval", type=float, help="seconds between heartbeats (default 60)")

    u = sub.add_parser("upload", help="send an outbox to the cloud (EDG-12)")
    u.add_argument("--outbox")
    u.add_argument("--once", action="store_true", help="one pass, then report what is left")

    d = sub.add_parser("detect-file", help="cache detections for a video as JSONL")
    d.add_argument("video")
    d.add_argument("--out", required=True)
    d.add_argument("--fps", type=float, default=5.0)
    d.add_argument("--detector")
    d.add_argument("--model")
    d.add_argument("--threshold", type=float, default=0.25)
    d.add_argument("--classes", help="comma-separated, e.g. person,truck")
    d.add_argument("--max-seconds", type=float)

    sv = sub.add_parser("survey", help="camera suitability check for an installer (DET-07)")
    sv.add_argument("source", help="RTSP URL or video file")
    sv.add_argument("--seconds", type=float, default=120.0)
    sv.add_argument("--fps", type=float, default=5.0)
    sv.add_argument("--detector")
    sv.add_argument("--model")
    sv.add_argument("--json", help="also write the report as JSON")
    sv.add_argument("--video", help="video to pair with a cached detections JSONL source")

    ns = sub.add_parser("new-site", help="starter site config from an industry template")
    ns.add_argument(
        "industry", choices=["restaurant", "retail", "clinic", "hotel", "warehouse", "factory"]
    )
    ns.add_argument("--site-id", default="new-site")
    ns.add_argument("--camera", default="cam1")
    ns.add_argument("--source", default="rtsp://USER:PASS@NVR_IP:554/Streaming/Channels/102")
    ns.add_argument("--open", default="09:00", help="opening time HH:MM")
    ns.add_argument("--close", default="23:00", help="closing time HH:MM")
    ns.add_argument("--language", choices=["en", "ar"], default="en")
    ns.add_argument("--out")

    c = sub.add_parser("check-camera", help="test an RTSP URL")
    c.add_argument("url")
    c.add_argument("--seconds", type=float, default=5.0)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = EdgeSettings()
    configure_logging(json_output=settings.log_json)
    if args.command == "validate":
        return cmd_validate(args)
    if args.command == "run":
        return cmd_run(args, settings)
    if args.command == "enrol":
        return cmd_enrol(args, settings)
    if args.command == "agent":
        return cmd_agent(args, settings)
    if args.command == "upload":
        return cmd_upload(args, settings)
    if args.command == "detect-file":
        return cmd_detect_file(args, settings)
    if args.command == "new-site":
        return cmd_new_site(args)
    if args.command == "survey":
        return cmd_survey(args, settings)
    if args.command == "check-camera":
        return cmd_check_camera(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
