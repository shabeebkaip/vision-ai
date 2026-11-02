import type Konva from 'konva';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Arrow,
  Circle,
  Group,
  Image as KImage,
  Label,
  Layer,
  Line as KLine,
  Stage,
  Tag,
  Text,
} from 'react-konva';
import type { Line, Zone } from '../../api/models';
import {
  centroid,
  flatten,
  inwardNormal,
  polygonToPixels,
  toNormalised,
  toPixels,
  translateWithin,
  type Point,
  type Size,
} from '../../lib/geometry';
import { zoneColour } from '../MediaViewer';

export type Tool = 'select' | 'zone' | 'line';
export type Selection = { kind: 'zone' | 'line'; id: string } | null;

const LINE_COLOUR = '#f59e0b';
const HANDLE = 7;

function useHtmlImage(src: string | null): HTMLImageElement | null {
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  useEffect(() => {
    if (!src) return;
    const i = new window.Image();
    i.onload = () => setImg(i);
    i.src = src;
    return () => {
      i.onload = null;
    };
  }, [src]);
  return img;
}

export interface ZoneCanvasProps {
  size: Size;
  snapshotUrl: string | null;
  zones: Zone[];
  lines: Line[];
  tool: Tool;
  selected: Selection;
  draft: Point[];
  onSelect: (s: Selection) => void;
  onZonesChange: (zones: Zone[]) => void;
  onLinesChange: (lines: Line[]) => void;
  onDraftChange: (draft: Point[]) => void;
  onFinishZone: (polygon: Point[]) => void;
  onFinishLine: (start: Point, end: Point) => void;
  fontFamily: string;
}

export function ZoneCanvas(props: ZoneCanvasProps) {
  const { size, zones, lines, tool, selected, draft, fontFamily } = props;
  const image = useHtmlImage(props.snapshotUrl);
  const [hover, setHover] = useState<Point | null>(null);
  const [dragOrigin, setDragOrigin] = useState<Point[] | null>(null);
  // Konva can report a click on the stage when a drag ends; ignore it so the shape stays selected.
  const lastDragEnd = useRef(0);
  // Our own double-click test: Konva reports any two quick clicks on the stage as a double
  // click, which would close a zone early when an installer places points quickly.
  const lastClick = useRef<{ t: number; p: Point } | null>(null);

  const pointer = (e: Konva.KonvaEventObject<Event>): Point | null => {
    const p = e.target.getStage()?.getPointerPosition();
    return p ? toNormalised([p.x, p.y], size) : null;
  };

  const clampDrag = (pos: { x: number; y: number }) => ({
    x: Math.min(size.width, Math.max(0, pos.x)),
    y: Math.min(size.height, Math.max(0, pos.y)),
  });

  function onStageClick(e: Konva.KonvaEventObject<MouseEvent | TouchEvent>) {
    if (Date.now() - lastDragEnd.current < 300) return;
    const p = pointer(e);
    if (!p) return;
    const here = toPixels(p, size);
    const prev = lastClick.current;
    lastClick.current = { t: Date.now(), p: here };
    if (tool === 'zone') {
      const isDouble =
        prev &&
        Date.now() - prev.t < 400 &&
        Math.hypot(prev.p[0] - here[0], prev.p[1] - here[1]) <= 6;
      if (isDouble && draft.length >= 3) {
        // The first click of the double click already added this point.
        props.onFinishZone(draft);
        return;
      }
      if (draft.length >= 3) {
        const first = toPixels(draft[0]!, size);
        if (Math.hypot(first[0] - here[0], first[1] - here[1]) <= HANDLE * 2) {
          props.onFinishZone(draft);
          return;
        }
      }
      props.onDraftChange([...draft, p]);
    } else if (tool === 'line') {
      if (draft.length === 0) props.onDraftChange([p]);
      else if (p[0] !== draft[0]![0] || p[1] !== draft[0]![1]) props.onFinishLine(draft[0]!, p);
    } else if (e.target === e.target.getStage() || e.target.name() === 'background') {
      props.onSelect(null);
    }
  }

  const draftPx = useMemo(() => polygonToPixels(draft, size), [draft, size]);
  const hoverPx = hover ? toPixels(hover, size) : null;
  const interactive = tool === 'select';

  return (
    <Stage
      width={size.width}
      height={size.height}
      onClick={onStageClick}
      onTap={onStageClick}
      onMouseMove={(e) => setHover(pointer(e))}
      onMouseLeave={() => setHover(null)}
      onDragEnd={() => {
        lastDragEnd.current = Date.now();
      }}
      style={{ cursor: tool === 'select' ? 'default' : 'crosshair', touchAction: 'none' }}
    >
      <Layer listening={tool === 'select'}>
        {image && (
          <KImage image={image} width={size.width} height={size.height} name="background" />
        )}
      </Layer>
      <Layer listening={interactive}>
        {zones.map((z, i) => {
          const pts = polygonToPixels(z.polygon as Point[], size);
          const isSel = selected?.kind === 'zone' && selected.id === z.id;
          const c = centroid(pts);
          return (
            <Group key={z.id}>
              <KLine
                points={flatten(pts)}
                closed
                fill={zoneColour(i)}
                opacity={isSel ? 0.42 : 0.28}
                stroke={zoneColour(i)}
                strokeWidth={isSel ? 3 : 2}
                draggable={interactive}
                onMouseDown={() => props.onSelect({ kind: 'zone', id: z.id })}
                onTap={() => props.onSelect({ kind: 'zone', id: z.id })}
                onDragStart={() => {
                  props.onSelect({ kind: 'zone', id: z.id });
                  setDragOrigin(z.polygon as Point[]);
                }}
                onDragMove={(e) => {
                  lastDragEnd.current = Date.now();
                  const node = e.target;
                  const origin = dragOrigin ?? (z.polygon as Point[]);
                  const moved = translateWithin(
                    origin,
                    node.x() / size.width,
                    node.y() / size.height,
                  );
                  node.position({ x: 0, y: 0 });
                  props.onZonesChange(
                    zones.map((zz) => (zz.id === z.id ? { ...zz, polygon: moved } : zz)),
                  );
                }}
                onDragEnd={() => setDragOrigin(null)}
              />
              <Label x={c[0]} y={c[1]} listening={false}>
                <Tag fill="rgba(15,27,36,0.72)" cornerRadius={4} pointerDirection="none" />
                <Text
                  text={z.name || z.id}
                  fill="#fff"
                  fontSize={13}
                  padding={5}
                  fontFamily={fontFamily}
                />
              </Label>
            </Group>
          );
        })}

        {lines.map((l) => {
          const a = toPixels(l.start as Point, size);
          const b = toPixels(l.end as Point, size);
          const [nx, ny] = inwardNormal(a, b);
          const m: Point = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
          const isSel = selected?.kind === 'line' && selected.id === l.id;
          return (
            <Group key={l.id}>
              <KLine
                points={[...a, ...b]}
                stroke={LINE_COLOUR}
                strokeWidth={isSel ? 5 : 4}
                hitStrokeWidth={20}
                lineCap="round"
                draggable={interactive}
                onMouseDown={() => props.onSelect({ kind: 'line', id: l.id })}
                onTap={() => props.onSelect({ kind: 'line', id: l.id })}
                onDragStart={() => {
                  props.onSelect({ kind: 'line', id: l.id });
                  setDragOrigin([l.start as Point, l.end as Point]);
                }}
                onDragMove={(e) => {
                  lastDragEnd.current = Date.now();
                  const node = e.target;
                  const origin = dragOrigin ?? [l.start as Point, l.end as Point];
                  const [s, en] = translateWithin(
                    origin,
                    node.x() / size.width,
                    node.y() / size.height,
                  );
                  node.position({ x: 0, y: 0 });
                  props.onLinesChange(
                    lines.map((ll) => (ll.id === l.id ? { ...ll, start: s!, end: en! } : ll)),
                  );
                }}
                onDragEnd={() => setDragOrigin(null)}
              />
              <Arrow
                points={[m[0], m[1], m[0] + nx * 36, m[1] + ny * 36]}
                stroke={LINE_COLOUR}
                fill={LINE_COLOUR}
                strokeWidth={3}
                pointerLength={9}
                pointerWidth={9}
                listening={false}
              />
              <Label x={a[0]} y={a[1] - 26} listening={false}>
                <Tag fill="rgba(15,27,36,0.72)" cornerRadius={4} />
                <Text
                  text={l.name || l.id}
                  fill="#fff"
                  fontSize={13}
                  padding={5}
                  fontFamily={fontFamily}
                />
              </Label>
            </Group>
          );
        })}

        {/* Vertex handles of the selected shape */}
        {selected?.kind === 'zone' &&
          zones
            .filter((z) => z.id === selected.id)
            .flatMap((z) => {
              const pts = polygonToPixels(z.polygon as Point[], size);
              const handles = pts.map((p, idx) => (
                <Circle
                  key={`v-${idx}`}
                  x={p[0]}
                  y={p[1]}
                  radius={HANDLE}
                  fill="#ffffff"
                  stroke="#0b5d57"
                  strokeWidth={2}
                  draggable
                  dragBoundFunc={clampDrag}
                  onDragMove={(e) => {
                    lastDragEnd.current = Date.now();
                    const np = toNormalised([e.target.x(), e.target.y()], size);
                    const poly = (z.polygon as Point[]).map((q, k) => (k === idx ? np : q));
                    props.onZonesChange(
                      zones.map((zz) => (zz.id === z.id ? { ...zz, polygon: poly } : zz)),
                    );
                  }}
                  onDblClick={() => {
                    if (z.polygon.length <= 3) return;
                    const poly = (z.polygon as Point[]).filter((_, k) => k !== idx);
                    props.onZonesChange(
                      zones.map((zz) => (zz.id === z.id ? { ...zz, polygon: poly } : zz)),
                    );
                  }}
                />
              ));
              // Midpoint handles: click to insert a vertex there.
              const mids = pts.map((p, idx) => {
                const q = pts[(idx + 1) % pts.length]!;
                const mp: Point = [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2];
                const insert = () => {
                  const poly = [...(z.polygon as Point[])];
                  poly.splice(idx + 1, 0, toNormalised(mp, size));
                  props.onZonesChange(
                    zones.map((zz) => (zz.id === z.id ? { ...zz, polygon: poly } : zz)),
                  );
                };
                return (
                  <Circle
                    key={`m-${idx}`}
                    x={mp[0]}
                    y={mp[1]}
                    radius={HANDLE - 2}
                    fill="#0b5d57"
                    opacity={0.65}
                    onClick={insert}
                    onTap={insert}
                  />
                );
              });
              return [...mids, ...handles];
            })}
        {selected?.kind === 'line' &&
          lines
            .filter((l) => l.id === selected.id)
            .flatMap((l) =>
              (['start', 'end'] as const).map((end) => {
                const p = toPixels(l[end] as Point, size);
                return (
                  <Circle
                    key={end}
                    x={p[0]}
                    y={p[1]}
                    radius={HANDLE}
                    fill="#ffffff"
                    stroke="#b45309"
                    strokeWidth={2}
                    draggable
                    dragBoundFunc={clampDrag}
                    onDragMove={(e) => {
                      lastDragEnd.current = Date.now();
                      const np = toNormalised([e.target.x(), e.target.y()], size);
                      props.onLinesChange(
                        lines.map((ll) => (ll.id === l.id ? { ...ll, [end]: np } : ll)),
                      );
                    }}
                  />
                );
              }),
            )}
      </Layer>

      {/* Drawing in progress */}
      <Layer listening={false}>
        {draftPx.length > 0 && (
          <KLine
            points={flatten(hoverPx ? [...draftPx, hoverPx] : draftPx)}
            stroke={tool === 'line' ? LINE_COLOUR : '#14b8a6'}
            strokeWidth={2}
            dash={[8, 6]}
          />
        )}
        {draftPx.map((p, i) => (
          <Circle
            key={i}
            x={p[0]}
            y={p[1]}
            radius={i === 0 && tool === 'zone' && draftPx.length >= 3 ? HANDLE + 3 : HANDLE - 2}
            fill={i === 0 ? '#ffffff' : '#14b8a6'}
            stroke="#0b5d57"
            strokeWidth={2}
          />
        ))}
      </Layer>
    </Stage>
  );
}
