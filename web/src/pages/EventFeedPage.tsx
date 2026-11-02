import { useInfiniteQuery } from '@tanstack/react-query';
import { ChevronRight, Filter, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router';
import { useApi } from '../api';
import type {
  EventFilters,
  EventView,
  RuleType,
  Severity,
  EventState,
  Verdict,
} from '../api/models';
import { EVENT_STATES, RULE_TYPES, SEVERITIES } from '../api/models';
import { RuleTypeLabel, Thumb, useEventSummary } from '../components/EventBits';
import { Page, PageHeader } from '../components/layout/AppShell';
import { SEVERITY_BAR, SeverityBadge, StateBadge, VerdictBadge } from '../components/ui/Badges';
import { Button } from '../components/ui/Button';
import { Field, SelectField } from '../components/ui/Field';
import { EmptyState, ErrorState, Skeleton } from '../components/ui/States';
import { useFormat } from '../lib/prefs';
import { indexById, qk, useCameras, useLocalName, useSites } from '../lib/queries';
import { DEFAULT_TZ, localDayRangeUtc } from '../lib/time';

export const FEED_POLL_MS = 10_000;
const PAGE_SIZE = 20;
const FILTER_KEYS = [
  'site',
  'camera',
  'type',
  'severity',
  'state',
  'verdict',
  'from',
  'to',
] as const;

/** URL search params -> API filters. Dates are local days in Asia/Riyadh. */
export function filtersFromParams(params: URLSearchParams, tz = DEFAULT_TZ): EventFilters {
  const f: EventFilters = {};
  const site = params.get('site');
  const camera = params.get('camera');
  const type = params.get('type');
  const severity = params.get('severity');
  const state = params.get('state');
  const verdict = params.get('verdict');
  const from = params.get('from');
  const to = params.get('to');
  if (site) f.site_id = site;
  if (camera) f.camera_id = camera;
  if (type && (RULE_TYPES as readonly string[]).includes(type)) f.rule_type = type as RuleType;
  if (severity && (SEVERITIES as readonly string[]).includes(severity))
    f.severity = severity as Severity;
  if (state && (EVENT_STATES as readonly string[]).includes(state)) f.state = state as EventState;
  if (verdict === 'correct' || verdict === 'false_alarm' || verdict === 'none')
    f.verdict = verdict as Verdict | 'none';
  if (from && /^\d{4}-\d{2}-\d{2}$/.test(from)) f.from = localDayRangeUtc(from, tz)[0];
  if (to && /^\d{4}-\d{2}-\d{2}$/.test(to)) f.to = localDayRangeUtc(to, tz)[1];
  return f;
}

function EventRow({
  event,
  siteName,
  cameraName,
}: {
  event: EventView;
  siteName: string;
  cameraName: string;
}) {
  const { t } = useTranslation();
  const fmt = useFormat();
  const summary = useEventSummary();
  return (
    <li>
      <Link
        to={`/events/${encodeURIComponent(event.id)}`}
        className="group relative flex gap-3 overflow-hidden p-3 hover:bg-canvas focus-visible:bg-canvas sm:gap-4 sm:p-4"
      >
        <span
          className={`absolute inset-y-0 start-0 w-1 ${SEVERITY_BAR[event.severity]}`}
          aria-hidden
        />
        <Thumb
          src={event.snapshot_url}
          alt={t('event.snapshotAlt', { camera: cameraName })}
          className="w-28 shrink-0 sm:w-40"
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-semibold text-ink-900">
              <RuleTypeLabel type={event.rule_type} withIcon={false} />
            </span>
            <SeverityBadge severity={event.severity} />
            {event.state === 'triggered' && <StateBadge state="triggered" />}
          </div>
          <p className="mt-0.5 text-sm text-ink-700">{summary(event)}</p>
          <p className="mt-1 truncate text-xs text-ink-500">
            {siteName} · {cameraName}
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-ink-500">
            <time
              dateTime={event.triggered_at}
              title={fmt.dateTime(event.triggered_at)}
              className="num"
            >
              {fmt.relative(event.triggered_at)} · {fmt.time(event.triggered_at)}
            </time>
            <span className="sm:hidden">
              <VerdictBadge verdict={event.feedback?.verdict ?? null} />
            </span>
          </div>
        </div>
        <div className="hidden shrink-0 flex-col items-end justify-between sm:flex">
          <VerdictBadge verdict={event.feedback?.verdict ?? null} />
          <ChevronRight
            className="size-5 text-ink-400 group-hover:text-ink-700 rtl:-scale-x-100"
            aria-hidden
          />
        </div>
      </Link>
    </li>
  );
}

export function EventFeedPage() {
  const { t } = useTranslation();
  const api = useApi();
  const fmt = useFormat();
  const localName = useLocalName();
  const [params, setParams] = useSearchParams();
  const [showFilters, setShowFilters] = useState(false);
  const filters = useMemo(() => filtersFromParams(params), [params]);
  const sites = useSites();
  const cameras = useCameras();
  const siteById = useMemo(() => indexById(sites.data), [sites.data]);
  const cameraById = useMemo(() => indexById(cameras.data), [cameras.data]);

  const query = useInfiniteQuery({
    queryKey: qk.events(filters),
    queryFn: ({ pageParam }) => api.listEvents(filters, pageParam, PAGE_SIZE),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    refetchInterval: FEED_POLL_MS,
    refetchIntervalInBackground: false,
  });

  const events = useMemo(() => query.data?.pages.flatMap((p) => p.items) ?? [], [query.data]);
  const activeCount = FILTER_KEYS.filter((k) => params.get(k)).length;

  const sentinel = useRef<HTMLDivElement>(null);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = query;
  useEffect(() => {
    const el = sentinel.current;
    if (!el || typeof IntersectionObserver === 'undefined') return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting) && hasNextPage && !isFetchingNextPage)
        void fetchNextPage();
    });
    io.observe(el);
    return () => io.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  function setParam(key: (typeof FILTER_KEYS)[number], value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key === 'site') next.delete('camera');
    setParams(next, { replace: true });
  }

  const cameraOptions = (cameras.data ?? [])
    .filter((c) => !filters.site_id || c.site_id === filters.site_id)
    .map((c) => ({ value: c.id, label: localName(c) }));

  const filterPanel = (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <SelectField
        label={t('filters.site')}
        value={params.get('site') ?? ''}
        onChange={(e) => setParam('site', e.target.value)}
        placeholder={t('filters.allSites')}
        options={(sites.data ?? []).map((s) => ({ value: s.id, label: localName(s) }))}
      />
      <SelectField
        label={t('filters.camera')}
        value={params.get('camera') ?? ''}
        onChange={(e) => setParam('camera', e.target.value)}
        placeholder={t('filters.allCameras')}
        options={cameraOptions}
      />
      <SelectField
        label={t('filters.ruleType')}
        value={params.get('type') ?? ''}
        onChange={(e) => setParam('type', e.target.value)}
        placeholder={t('filters.allTypes')}
        options={RULE_TYPES.map((r) => ({ value: r, label: t(`ruleType.${r}`) }))}
      />
      <SelectField
        label={t('filters.severity')}
        value={params.get('severity') ?? ''}
        onChange={(e) => setParam('severity', e.target.value)}
        placeholder={t('filters.any')}
        options={SEVERITIES.map((s) => ({ value: s, label: t(`severity.${s}`) }))}
      />
      <SelectField
        label={t('filters.state')}
        value={params.get('state') ?? ''}
        onChange={(e) => setParam('state', e.target.value)}
        placeholder={t('filters.any')}
        options={EVENT_STATES.map((s) => ({ value: s, label: t(`eventState.${s}`) }))}
      />
      <SelectField
        label={t('filters.verdict')}
        value={params.get('verdict') ?? ''}
        onChange={(e) => setParam('verdict', e.target.value)}
        placeholder={t('filters.any')}
        options={[
          { value: 'none', label: t('verdict.none') },
          { value: 'correct', label: t('verdict.correct') },
          { value: 'false_alarm', label: t('verdict.false_alarm') },
        ]}
      />
      <Field label={t('filters.from')} htmlFor="filter-from">
        <input
          id="filter-from"
          type="date"
          className="input"
          value={params.get('from') ?? ''}
          max={params.get('to') ?? undefined}
          onChange={(e) => setParam('from', e.target.value)}
        />
      </Field>
      <Field label={t('filters.to')} htmlFor="filter-to">
        <input
          id="filter-to"
          type="date"
          className="input"
          value={params.get('to') ?? ''}
          min={params.get('from') ?? undefined}
          onChange={(e) => setParam('to', e.target.value)}
        />
      </Field>
    </div>
  );

  return (
    <Page wide>
      <PageHeader
        title={t('feed.title')}
        subtitle={
          <span className="inline-flex items-center gap-2">
            <span className="relative flex size-2">
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-60" />
              <span className="relative inline-flex size-2 rounded-full bg-emerald-500" />
            </span>
            <span className="num">
              {query.dataUpdatedAt
                ? t('feed.updated', { time: fmt.time(new Date(query.dataUpdatedAt)) })
                : t('common.loading')}
            </span>
            <span className="hidden sm:inline">· {t('feed.autoRefresh')}</span>
          </span>
        }
        actions={
          <>
            {activeCount > 0 && (
              <Button
                variant="ghost"
                size="sm"
                icon={<X className="size-4" aria-hidden />}
                onClick={() => setParams(new URLSearchParams(), { replace: true })}
              >
                {t('filters.clear')}
              </Button>
            )}
            <Button
              variant="secondary"
              size="sm"
              className="lg:hidden"
              aria-expanded={showFilters}
              icon={<Filter className="size-4" aria-hidden />}
              onClick={() => setShowFilters((v) => !v)}
            >
              {activeCount ? t('filters.titleCount', { count: activeCount }) : t('filters.title')}
            </Button>
          </>
        }
      />

      <div className={`card mb-4 p-4 ${showFilters ? '' : 'hidden lg:block'}`}>{filterPanel}</div>

      <div className="card overflow-hidden">
        {query.isPending ? (
          <ul className="divide-y divide-line">
            {Array.from({ length: 6 }, (_, i) => (
              <li key={i} className="flex gap-4 p-4">
                <Skeleton className="aspect-video w-28 sm:w-40" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-4 w-1/3" />
                  <Skeleton className="h-3 w-1/2" />
                  <Skeleton className="h-3 w-1/4" />
                </div>
              </li>
            ))}
          </ul>
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : events.length === 0 ? (
          <EmptyState
            title={activeCount ? t('feed.emptyFilteredTitle') : t('feed.emptyTitle')}
            body={activeCount ? t('feed.emptyFilteredBody') : t('feed.emptyBody')}
            action={
              activeCount ? (
                <Button
                  variant="secondary"
                  onClick={() => setParams(new URLSearchParams(), { replace: true })}
                >
                  {t('filters.clear')}
                </Button>
              ) : undefined
            }
          />
        ) : (
          <>
            <ul className="divide-y divide-line" aria-label={t('feed.listLabel')}>
              {events.map((e) => (
                <EventRow
                  key={e.id}
                  event={e}
                  siteName={localName(siteById.get(e.site_id), e.site_id)}
                  cameraName={localName(cameraById.get(e.camera_id), e.camera_id)}
                />
              ))}
            </ul>
            <div ref={sentinel} className="flex justify-center border-t border-line p-4">
              {query.hasNextPage ? (
                <Button
                  variant="secondary"
                  disabled={query.isFetchingNextPage}
                  onClick={() => void query.fetchNextPage()}
                >
                  {query.isFetchingNextPage ? t('common.loading') : t('feed.loadMore')}
                </Button>
              ) : (
                <p className="text-xs text-ink-500">
                  {t('feed.end', { count: events.length, n: fmt.number(events.length) })}
                </p>
              )}
            </div>
          </>
        )}
      </div>
    </Page>
  );
}
