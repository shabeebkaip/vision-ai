import { Eye, EyeOff, Image as ImageIcon, Play, VideoOff } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { CameraView, EventView, NormBox } from '../api/models';
import { inwardNormal, type Point } from '../lib/geometry';

// Overlay drawing space: 16:9 like the stream, so arrows keep their angle.
const VW = 1600;
const VH = 900;

const ZONE_COLOURS = ['#14b8a6', '#f59e0b', '#a855f7', '#3b82f6', '#ef4444', '#22c55e'];

export function zoneColour(index: number): string {
  return ZONE_COLOURS[index % ZONE_COLOURS.length]!;
}

function isNormBox(v: unknown): v is NormBox {
  return (
    Array.isArray(v) && v.length === 4 && v.every((n) => typeof n === 'number' && n >= 0 && n <= 1)
  );
}

export function eventBoxes(event: EventView): NormBox[] {
  const raw = event.attributes.boxes;
  return Array.isArray(raw) ? raw.filter(isNormBox) : [];
}

/** Snapshot with the rule's zone or line and the detected boxes drawn on top (normalised SVG). */
export function SnapshotOverlay({
  src,
  alt,
  camera,
  highlightZoneId,
  highlightLineId,
  boxes,
  showOverlay,
}: {
  src: string;
  alt: string;
  camera?: CameraView;
  highlightZoneId?: string | null;
  highlightLineId?: string | null;
  boxes: NormBox[];
  showOverlay: boolean;
}) {
  const zones = camera?.zones.filter((z) => !highlightZoneId || z.id === highlightZoneId) ?? [];
  const lines = camera?.lines.filter((l) => !highlightLineId || l.id === highlightLineId) ?? [];
  return (
    <div className="relative" dir="ltr">
      <img
        src={src}
        alt={alt}
        className="block aspect-video w-full rounded-lg bg-ink-900 object-cover"
      />
      {showOverlay && (
        <svg
          viewBox={`0 0 ${VW} ${VH}`}
          preserveAspectRatio="none"
          className="pointer-events-none absolute inset-0 size-full"
          aria-hidden
        >
          {zones.map((z, i) => (
            <polygon
              key={z.id}
              points={z.polygon.map(([x, y]) => `${x * VW},${y * VH}`).join(' ')}
              fill={zoneColour(i)}
              fillOpacity={0.18}
              stroke={zoneColour(i)}
              strokeWidth={2}
              vectorEffect="non-scaling-stroke"
            />
          ))}
          {lines.map((l) => {
            const a: Point = [l.start[0] * VW, l.start[1] * VH];
            const b: Point = [l.end[0] * VW, l.end[1] * VH];
            const [nx, ny] = inwardNormal(a, b);
            const mx = (a[0] + b[0]) / 2;
            const my = (a[1] + b[1]) / 2;
            return (
              <g key={l.id}>
                <line
                  x1={a[0]}
                  y1={a[1]}
                  x2={b[0]}
                  y2={b[1]}
                  stroke="#f59e0b"
                  strokeWidth={3}
                  vectorEffect="non-scaling-stroke"
                />
                <line
                  x1={mx}
                  y1={my}
                  x2={mx + nx * 70}
                  y2={my + ny * 70}
                  stroke="#f59e0b"
                  strokeWidth={2}
                  strokeDasharray="4 3"
                  vectorEffect="non-scaling-stroke"
                />
              </g>
            );
          })}
          {boxes.map((b, i) => (
            <rect
              key={i}
              x={b[0] * VW}
              y={b[1] * VH}
              width={(b[2] - b[0]) * VW}
              height={(b[3] - b[1]) * VH}
              fill="none"
              stroke="#ef4444"
              strokeWidth={2}
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </svg>
      )}
    </div>
  );
}

export function ClipPlayer({ src, poster }: { src: string; poster?: string | null }) {
  const { t } = useTranslation();
  // The mock API serves animated SVG stand-ins; the real API serves H.264 MP4 clips.
  if (src.startsWith('data:image/svg')) {
    return (
      <figure>
        <img
          src={src}
          alt={t('event.clipAlt')}
          className="block aspect-video w-full rounded-lg bg-ink-900 object-cover"
        />
        <figcaption className="mt-2 text-xs text-ink-500">{t('event.mockClip')}</figcaption>
      </figure>
    );
  }
  return (
    <video
      src={src}
      poster={poster ?? undefined}
      controls
      playsInline
      preload="metadata"
      className="block aspect-video w-full rounded-lg bg-ink-900"
    >
      {t('event.videoUnsupported')}
    </video>
  );
}

export function EventMedia({
  event,
  camera,
  zoneId,
  lineId,
}: {
  event: EventView;
  camera?: CameraView;
  zoneId?: string | null;
  lineId?: string | null;
}) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<'snapshot' | 'clip'>('snapshot');
  const [overlay, setOverlay] = useState(true);
  const tabClass = (active: boolean) =>
    `inline-flex h-9 items-center gap-1.5 rounded-md px-3 text-sm font-medium ${
      active ? 'bg-white text-ink-900 shadow-sm' : 'text-ink-500 hover:text-ink-900'
    }`;
  return (
    <div className="card p-3 sm:p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div role="tablist" className="inline-flex rounded-lg bg-ink-900/5 p-1">
          <button
            role="tab"
            type="button"
            aria-selected={tab === 'snapshot'}
            className={tabClass(tab === 'snapshot')}
            onClick={() => setTab('snapshot')}
          >
            <ImageIcon className="size-4" aria-hidden />
            {t('event.snapshot')}
          </button>
          <button
            role="tab"
            type="button"
            aria-selected={tab === 'clip'}
            className={tabClass(tab === 'clip')}
            onClick={() => setTab('clip')}
          >
            <Play className="size-4" aria-hidden />
            {t('event.clip')}
          </button>
        </div>
        {tab === 'snapshot' && event.snapshot_url && (
          <button
            type="button"
            onClick={() => setOverlay((v) => !v)}
            aria-pressed={overlay}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg px-2 text-sm text-ink-700 hover:bg-ink-900/5"
          >
            {overlay ? (
              <Eye className="size-4" aria-hidden />
            ) : (
              <EyeOff className="size-4" aria-hidden />
            )}
            {t('event.overlay')}
          </button>
        )}
      </div>
      {tab === 'snapshot' ? (
        event.snapshot_url ? (
          <SnapshotOverlay
            src={event.snapshot_url}
            alt={t('event.snapshotAlt', { camera: camera?.name ?? event.camera_id })}
            camera={camera}
            highlightZoneId={zoneId}
            highlightLineId={lineId}
            boxes={eventBoxes(event)}
            showOverlay={overlay}
          />
        ) : (
          <NoMedia text={t('event.noSnapshot')} />
        )
      ) : event.clip_url ? (
        <ClipPlayer src={event.clip_url} poster={event.snapshot_url} />
      ) : (
        <NoMedia text={t('event.noClip')} />
      )}
    </div>
  );
}

function NoMedia({ text }: { text: string }) {
  return (
    <div className="grid aspect-video place-items-center rounded-lg bg-ink-900/5 text-sm text-ink-500">
      <span className="flex items-center gap-2">
        <VideoOff className="size-5" aria-hidden />
        {text}
      </span>
    </div>
  );
}
