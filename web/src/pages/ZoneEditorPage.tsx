import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  ArrowLeftRight,
  Check,
  Loader2,
  Minus,
  MousePointer2,
  Pentagon,
  RotateCcw,
  Save,
  Trash2,
} from 'lucide-react';
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router';
import { useApi } from '../api';
import { ApiError } from '../api/client';
import type { CameraView, Line, Zone } from '../api/models';
import { Page } from '../components/layout/AppShell';
import { zoneColour } from '../components/MediaViewer';
import { CameraStatusBadge } from '../components/ui/Badges';
import { Button } from '../components/ui/Button';
import { ErrorState, Spinner } from '../components/ui/States';
import { ZoneCanvas, type Selection, type Tool } from '../components/zone-editor/ZoneCanvas';
import { fitStage, isValidPolygon, type Point, type Size } from '../lib/geometry';
import { useFormat } from '../lib/prefs';
import { qk, useLocalName } from '../lib/queries';

function nextId(prefix: string, taken: Set<string>): string {
  for (let i = 1; ; i++) {
    const id = `${prefix}-${i}`;
    if (!taken.has(id)) return id;
  }
}

function useStageSize(aspect: number): [React.RefObject<HTMLDivElement | null>, Size] {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<Size>({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setSize(fitStage(aspect, el.clientWidth, window.innerHeight * 0.68));
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    window.addEventListener('resize', update);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', update);
    };
  }, [aspect]);
  return [ref, size];
}

function Editor({ camera }: { camera: CameraView }) {
  const { t } = useTranslation();
  const api = useApi();
  const fmt = useFormat();
  const localName = useLocalName();
  const queryClient = useQueryClient();
  const [zones, setZones] = useState<Zone[]>(camera.zones);
  const [lines, setLines] = useState<Line[]>(camera.lines);
  const [tool, setTool] = useState<Tool>('select');
  const [selected, setSelected] = useState<Selection>(null);
  const [draft, setDraft] = useState<Point[]>([]);
  const [dirty, setDirty] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const aspect = camera.resolution[0] / camera.resolution[1] || 16 / 9;
  const [containerRef, size] = useStageSize(aspect);

  const changeZones = useCallback((z: Zone[]) => {
    setZones(z);
    setDirty(true);
  }, []);
  const changeLines = useCallback((l: Line[]) => {
    setLines(l);
    setDirty(true);
  }, []);

  const taken = new Set([...zones.map((z) => z.id), ...lines.map((l) => l.id)]);

  const finishZone = (polygon: Point[]) => {
    if (!isValidPolygon(polygon)) return;
    const id = nextId('zone', taken);
    changeZones([...zones, { id, name: t('editor.newZone', { n: zones.length + 1 }), polygon }]);
    setDraft([]);
    setTool('select');
    setSelected({ kind: 'zone', id });
  };
  const finishLine = (start: Point, end: Point) => {
    const id = nextId('line', taken);
    changeLines([...lines, { id, name: t('editor.newLine', { n: lines.length + 1 }), start, end }]);
    setDraft([]);
    setTool('select');
    setSelected({ kind: 'line', id });
  };
  const removeSelected = useCallback(() => {
    if (!selected) return;
    if (selected.kind === 'zone') changeZones(zones.filter((z) => z.id !== selected.id));
    else changeLines(lines.filter((l) => l.id !== selected.id));
    setSelected(null);
  }, [selected, zones, lines, changeZones, changeLines]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)) return;
      if (e.key === 'Escape') {
        setDraft([]);
        setTool('select');
        setSelected(null);
      } else if (e.key === 'Enter' && tool === 'zone' && draft.length >= 3) {
        finishZone(draft);
      } else if ((e.key === 'Delete' || e.key === 'Backspace') && selected) {
        e.preventDefault();
        removeSelected();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const save = useMutation({
    mutationFn: () => api.saveGeometry(camera.id, { zones, lines }),
    onSuccess: (updated) => {
      queryClient.setQueryData(qk.camera(camera.id), updated);
      void queryClient.invalidateQueries({ queryKey: ['cameras'] });
      setDirty(false);
      setSavedAt(Date.now());
    },
  });

  const discard = () => {
    setZones(camera.zones);
    setLines(camera.lines);
    setDraft([]);
    setSelected(null);
    setDirty(false);
  };

  const pickTool = (next: Tool) => {
    setTool(next);
    setDraft([]);
    if (next !== 'select') setSelected(null);
  };

  const toolBtn = (id: Tool, label: string, Icon: typeof MousePointer2) => (
    <button
      type="button"
      onClick={() => pickTool(id)}
      aria-pressed={tool === id}
      className={`inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium sm:flex-none ${
        tool === id ? 'bg-brand-700 text-white shadow-sm' : 'text-ink-700 hover:bg-white'
      }`}
    >
      <Icon className="size-4" aria-hidden />
      {label}
    </button>
  );

  const help =
    tool === 'zone'
      ? draft.length >= 3
        ? t('editor.helpZoneClose')
        : t('editor.helpZone')
      : tool === 'line'
        ? draft.length
          ? t('editor.helpLineEnd')
          : t('editor.helpLine')
        : selected
          ? t('editor.helpSelected')
          : t('editor.helpSelect');

  const selZone = selected?.kind === 'zone' ? zones.find((z) => z.id === selected.id) : undefined;
  const selLine = selected?.kind === 'line' ? lines.find((l) => l.id === selected.id) : undefined;
  const coord = (p: readonly number[]) =>
    `(${fmt.number(p[0]!, { maximumFractionDigits: 3 })}, ${fmt.number(p[1]!, { maximumFractionDigits: 3 })})`;

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div
            className="flex w-full rounded-lg bg-ink-900/5 p-1 sm:w-auto"
            role="toolbar"
            aria-label={t('editor.tools')}
          >
            {toolBtn('select', t('editor.select'), MousePointer2)}
            {toolBtn('zone', t('editor.drawZone'), Pentagon)}
            {toolBtn('line', t('editor.drawLine'), Minus)}
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              disabled={!selected}
              onClick={removeSelected}
              icon={<Trash2 className="size-4" aria-hidden />}
            >
              {t('editor.delete')}
            </Button>
          </div>
        </div>

        <div
          ref={containerRef}
          dir="ltr"
          className="overflow-hidden rounded-lg bg-ink-900 select-none"
        >
          {size.width > 0 && (
            <ZoneCanvas
              size={size}
              snapshotUrl={camera.snapshot_url}
              zones={zones}
              lines={lines}
              tool={tool}
              selected={selected}
              draft={draft}
              onSelect={setSelected}
              onZonesChange={changeZones}
              onLinesChange={changeLines}
              onDraftChange={setDraft}
              onFinishZone={finishZone}
              onFinishLine={finishLine}
              fontFamily="IBM Plex Sans Arabic, sans-serif"
            />
          )}
        </div>
        <p className="rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-900" aria-live="polite">
          {help}
        </p>
        <p className="text-xs text-ink-500">{t('editor.normalisedNote')}</p>
      </div>

      <aside className="space-y-4">
        <section className="card p-4">
          <div className="flex items-center justify-between gap-2">
            <h2 className="font-semibold">{t('editor.zones')}</h2>
            <span className="num text-xs text-ink-500">{fmt.number(zones.length)}</span>
          </div>
          {zones.length === 0 ? (
            <p className="mt-2 text-sm text-ink-500">{t('editor.noZones')}</p>
          ) : (
            <ul className="mt-3 space-y-2">
              {zones.map((z, i) => (
                <li
                  key={z.id}
                  className={`flex items-center gap-2 rounded-lg border p-2 ${selected?.id === z.id ? 'border-brand-400 bg-brand-50' : 'border-line'}`}
                >
                  <button
                    type="button"
                    className="size-4 shrink-0 rounded"
                    style={{ background: zoneColour(i) }}
                    aria-label={t('editor.selectShape', { name: z.name || z.id })}
                    onClick={() => {
                      pickTool('select');
                      setSelected({ kind: 'zone', id: z.id });
                    }}
                  />
                  <input
                    dir="auto"
                    className="input h-8 py-1"
                    value={z.name}
                    aria-label={t('editor.zoneName')}
                    onFocus={() => setSelected({ kind: 'zone', id: z.id })}
                    onChange={(e) =>
                      changeZones(
                        zones.map((zz) => (zz.id === z.id ? { ...zz, name: e.target.value } : zz)),
                      )
                    }
                  />
                  <span className="num shrink-0 text-xs text-ink-500" title={t('editor.points')}>
                    {fmt.number(z.polygon.length)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card p-4">
          <div className="flex items-center justify-between gap-2">
            <h2 className="font-semibold">{t('editor.lines')}</h2>
            <span className="num text-xs text-ink-500">{fmt.number(lines.length)}</span>
          </div>
          {lines.length === 0 ? (
            <p className="mt-2 text-sm text-ink-500">{t('editor.noLines')}</p>
          ) : (
            <ul className="mt-3 space-y-2">
              {lines.map((l) => (
                <li
                  key={l.id}
                  className={`flex items-center gap-2 rounded-lg border p-2 ${selected?.id === l.id ? 'border-amber-400 bg-amber-50' : 'border-line'}`}
                >
                  <button
                    type="button"
                    className="h-1 w-4 shrink-0 rounded bg-amber-500"
                    aria-label={t('editor.selectShape', { name: l.name || l.id })}
                    onClick={() => {
                      pickTool('select');
                      setSelected({ kind: 'line', id: l.id });
                    }}
                  />
                  <input
                    dir="auto"
                    className="input h-8 py-1"
                    value={l.name}
                    aria-label={t('editor.lineName')}
                    onFocus={() => setSelected({ kind: 'line', id: l.id })}
                    onChange={(e) =>
                      changeLines(
                        lines.map((ll) => (ll.id === l.id ? { ...ll, name: e.target.value } : ll)),
                      )
                    }
                  />
                  <button
                    type="button"
                    className="grid size-8 shrink-0 place-items-center rounded-md text-ink-500 hover:bg-ink-900/5"
                    title={t('editor.reverse')}
                    aria-label={t('editor.reverse')}
                    onClick={() =>
                      changeLines(
                        lines.map((ll) =>
                          ll.id === l.id ? { ...ll, start: ll.end, end: ll.start } : ll,
                        ),
                      )
                    }
                  >
                    <ArrowLeftRight className="size-4" aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 text-xs text-ink-500">{t('editor.arrowHelp')}</p>
        </section>

        {(selZone || selLine) && (
          <section className="card p-4 text-sm">
            <h2 className="font-semibold">{t('editor.coordinates')}</h2>
            <p className="mt-1 text-xs text-ink-500">{selZone?.name || selLine?.name}</p>
            <ol
              dir="ltr"
              className="num mt-2 max-h-40 space-y-0.5 overflow-auto font-mono text-xs text-ink-700"
            >
              {selZone && selZone.polygon.map((p, i) => <li key={i}>{coord(p)}</li>)}
              {selLine && (
                <>
                  <li>start {coord(selLine.start)}</li>
                  <li>end {coord(selLine.end)}</li>
                </>
              )}
            </ol>
          </section>
        )}

        <div className="card sticky bottom-20 space-y-2 p-4 lg:bottom-4">
          {save.isError && (
            <p role="alert" className="text-sm text-sev-critical">
              {save.error instanceof ApiError && save.error.status === 409
                ? t('editor.inUse', { detail: save.error.message })
                : t('errors.saveFailed')}
            </p>
          )}
          {!dirty && savedAt && (
            <p role="status" className="flex items-center gap-1.5 text-sm text-emerald-700">
              <Check className="size-4" aria-hidden /> {t('editor.saved')}
            </p>
          )}
          {dirty && <p className="text-sm text-amber-800">{t('editor.unsaved')}</p>}
          <div className="flex gap-2">
            <Button
              className="flex-1"
              disabled={!dirty || save.isPending}
              onClick={() => save.mutate()}
              icon={
                save.isPending ? (
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                ) : (
                  <Save className="size-4" aria-hidden />
                )
              }
            >
              {t('common.save')}
            </Button>
            <Button
              variant="secondary"
              disabled={!dirty || save.isPending}
              onClick={discard}
              icon={<RotateCcw className="size-4" aria-hidden />}
            >
              {t('editor.discard')}
            </Button>
          </div>
          <p className="text-xs text-ink-500">
            {t('editor.cameraLabel', { name: localName(camera) })}
          </p>
        </div>
      </aside>
    </div>
  );
}

export default function ZoneEditorPage() {
  const { cameraId = '' } = useParams();
  const { t } = useTranslation();
  const api = useApi();
  const localName = useLocalName();
  const camera = useQuery({
    queryKey: qk.camera(cameraId),
    queryFn: () => api.getCamera(cameraId),
    staleTime: Infinity,
  });
  return (
    <Page wide>
      <Link
        to="/sites"
        className="mb-2 inline-flex items-center gap-1.5 text-sm text-ink-500 hover:text-ink-900"
      >
        <ArrowLeft className="size-4 rtl:-scale-x-100" aria-hidden />
        {t('editor.back')}
      </Link>
      {camera.isPending ? (
        <Spinner />
      ) : camera.isError ? (
        <div className="card">
          <ErrorState error={camera.error} onRetry={() => void camera.refetch()} />
        </div>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
              {t('editor.title', { camera: localName(camera.data) })}
            </h1>
            <CameraStatusBadge status={camera.data.status} />
          </div>
          <Editor key={camera.data.id} camera={camera.data} />
        </>
      )}
    </Page>
  );
}
