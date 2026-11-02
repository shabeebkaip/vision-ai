import { useQuery } from '@tanstack/react-query';
import { ArrowRight, BellRing, Cctv, Footprints, ShieldCheck } from 'lucide-react';
import { useMemo, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router';
import { useApi } from '../api';
import { RULE_TYPES } from '../api/models';
import { RULE_ICONS, Thumb, useEventSummary } from '../components/EventBits';
import { FootfallChart } from '../components/FootfallChart';
import { Page, PageHeader } from '../components/layout/AppShell';
import { CameraStatusBadge, SeverityBadge } from '../components/ui/Badges';
import { ButtonLink } from '../components/ui/Button';
import { EmptyState, ErrorState, Skeleton, Spinner } from '../components/ui/States';
import { useFormat } from '../lib/prefs';
import { qk, useCameras, useLocalName, useSites } from '../lib/queries';
import { DEFAULT_TZ, localDateString, localDayRangeUtc } from '../lib/time';

function Kpi({
  label,
  value,
  hint,
  icon,
  tone = 'brand',
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  icon: ReactNode;
  tone?: 'brand' | 'warn';
}) {
  return (
    <div className="card p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-ink-500">{label}</p>
        <span
          className={`grid size-8 place-items-center rounded-lg ${tone === 'warn' ? 'bg-amber-50 text-amber-700' : 'bg-brand-50 text-brand-700'}`}
        >
          {icon}
        </span>
      </div>
      <p className="num mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">{value}</p>
      {hint && <p className="mt-1 text-xs text-ink-500">{hint}</p>}
    </div>
  );
}

export default function OverviewPage() {
  const { t } = useTranslation();
  const api = useApi();
  const localName = useLocalName();
  const summary = useEventSummary();
  const [params, setParams] = useSearchParams();
  const sites = useSites();
  const siteId = params.get('site') ?? sites.data?.[0]?.id;
  const site = sites.data?.find((s) => s.id === siteId);
  const tz = site?.timezone ?? DEFAULT_TZ;
  const fmt = useFormat(tz);
  const today = localDateString(new Date(), tz);

  const overview = useQuery({
    queryKey: qk.overview(siteId ?? '', today),
    queryFn: () => api.getOverview(siteId!, today),
    enabled: !!siteId,
    refetchInterval: 60_000,
  });
  const cameras = useCameras(siteId);
  const recentFilters = useMemo(
    () => ({ site_id: siteId, from: localDayRangeUtc(today, tz)[0] }),
    [siteId, today, tz],
  );
  const recent = useQuery({
    queryKey: qk.events({ ...recentFilters, limit: 5 }),
    queryFn: () => api.listEvents(recentFilters, null, 5),
    enabled: !!siteId,
    refetchInterval: 10_000,
  });

  if (sites.isPending)
    return (
      <Page>
        <Spinner />
      </Page>
    );
  if (sites.isError)
    return (
      <Page>
        <div className="card">
          <ErrorState error={sites.error} onRetry={() => void sites.refetch()} />
        </div>
      </Page>
    );
  if (!site)
    return (
      <Page>
        <div className="card">
          <EmptyState title={t('sites.emptyTitle')} body={t('sites.emptyBody')} />
        </div>
      </Page>
    );

  const o = overview.data;
  const maxByType = o ? Math.max(1, ...Object.values(o.alerts_by_type)) : 1;
  const footfallTotal = o?.footfall_by_hour.reduce((s, h) => s + h.in, 0) ?? 0;
  const typeRows = o
    ? [...RULE_TYPES].sort((a, b) => o.alerts_by_type[b] - o.alerts_by_type[a])
    : [];

  return (
    <Page wide>
      <PageHeader
        title={t('overview.title')}
        subtitle={t('overview.subtitle', { date: fmt.day(new Date().toISOString()) })}
        actions={
          <label className="flex items-center gap-2 text-sm">
            <span className="sr-only sm:not-sr-only sm:text-ink-500">{t('filters.site')}</span>
            <select
              className="input h-10 w-auto min-w-56 pe-8"
              value={site.id}
              onChange={(e) => setParams({ site: e.target.value }, { replace: true })}
            >
              {sites.data.map((s) => (
                <option key={s.id} value={s.id}>
                  {localName(s)}
                </option>
              ))}
            </select>
          </label>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {o ? (
          <>
            <Kpi
              label={t('overview.alertsToday')}
              value={fmt.number(o.alerts_total)}
              icon={<BellRing className="size-4" aria-hidden />}
              hint={
                <Link
                  to={`/events?site=${site.id}&from=${today}`}
                  className="text-brand-700 hover:underline"
                >
                  {t('overview.viewAll')}
                </Link>
              }
            />
            <Kpi
              label={t('overview.falseRate')}
              value={o.false_alert_rate_7d === null ? '—' : fmt.percent(o.false_alert_rate_7d)}
              icon={<ShieldCheck className="size-4" aria-hidden />}
              tone={
                o.false_alert_rate_7d !== null && o.false_alert_rate_7d > 0.2 ? 'warn' : 'brand'
              }
              hint={t('overview.reviewed', { count: o.reviewed_7d, n: fmt.number(o.reviewed_7d) })}
            />
            <Kpi
              label={t('overview.camerasOnline')}
              value={`${fmt.number(o.cameras_online)} / ${fmt.number(o.cameras_total)}`}
              icon={<Cctv className="size-4" aria-hidden />}
              tone={o.cameras_online < o.cameras_total ? 'warn' : 'brand'}
              hint={
                o.cameras_online < o.cameras_total
                  ? t('overview.camerasNeedAttention')
                  : t('overview.allOnline')
              }
            />
            <Kpi
              label={t('overview.footfallToday')}
              value={fmt.number(footfallTotal)}
              icon={<Footprints className="size-4" aria-hidden />}
              hint={t('overview.footfallHint')}
            />
          </>
        ) : overview.isError ? (
          <div className="card col-span-full">
            <ErrorState error={overview.error} onRetry={() => void overview.refetch()} />
          </div>
        ) : (
          Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-28" />)
        )}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <section className="card p-4">
          <h2 className="font-semibold">{t('overview.byType')}</h2>
          <p className="text-xs text-ink-500">{t('overview.byTypeHint')}</p>
          {o ? (
            <ul className="mt-4 space-y-3">
              {typeRows.map((type) => {
                const Icon = RULE_ICONS[type];
                const n = o.alerts_by_type[type];
                return (
                  <li key={type}>
                    <Link
                      to={`/events?site=${site.id}&type=${type}&from=${today}`}
                      className="group block rounded-md focus-visible:outline-2"
                    >
                      <div className="flex items-center justify-between gap-2 text-sm">
                        <span className="flex items-center gap-2 text-ink-700 group-hover:text-ink-900">
                          <Icon className="size-4 text-ink-500" aria-hidden />
                          {t(`ruleType.${type}`)}
                        </span>
                        <span className="num font-semibold">{fmt.number(n)}</span>
                      </div>
                      <div className="mt-1 h-2 rounded-full bg-ink-900/5">
                        <div
                          className="h-2 rounded-full bg-[#0f9488]"
                          style={{ width: `${n === 0 ? 0 : Math.max(4, (n / maxByType) * 100)}%` }}
                        />
                      </div>
                    </Link>
                  </li>
                );
              })}
            </ul>
          ) : (
            <Skeleton className="mt-4 h-48" />
          )}
        </section>

        <section className="card p-4">
          <h2 className="font-semibold">{t('overview.footfall')}</h2>
          <p className="mb-3 text-xs text-ink-500">{t('overview.footfallSub')}</p>
          {o ? (
            o.footfall_by_hour.length ? (
              <FootfallChart data={o.footfall_by_hour} />
            ) : (
              <EmptyState title={t('overview.noFootfall')} />
            )
          ) : (
            <Skeleton className="h-64" />
          )}
        </section>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <section className="card overflow-hidden">
          <div className="flex items-center justify-between gap-2 border-b border-line p-4">
            <h2 className="font-semibold">{t('overview.latest')}</h2>
            <ButtonLink
              to={`/events?site=${site.id}`}
              size="sm"
              variant="ghost"
              icon={<ArrowRight className="size-4 rtl:-scale-x-100" aria-hidden />}
            >
              {t('overview.viewAll')}
            </ButtonLink>
          </div>
          {recent.data ? (
            recent.data.items.length ? (
              <ul className="divide-y divide-line">
                {recent.data.items.map((e) => (
                  <li key={e.id}>
                    <Link
                      to={`/events/${e.id}`}
                      className="flex items-center gap-3 p-3 hover:bg-canvas"
                    >
                      <Thumb src={e.snapshot_url} alt="" className="w-20 shrink-0" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">
                          {t(`ruleType.${e.rule_type}`)}
                        </p>
                        <p className="truncate text-xs text-ink-500">{summary(e)}</p>
                      </div>
                      <div className="flex flex-col items-end gap-1">
                        <SeverityBadge severity={e.severity} />
                        <span className="num text-xs text-ink-500">{fmt.time(e.triggered_at)}</span>
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title={t('overview.quietTitle')} body={t('overview.quietBody')} />
            )
          ) : (
            <Spinner />
          )}
        </section>

        <section className="card overflow-hidden">
          <div className="flex items-center justify-between gap-2 border-b border-line p-4">
            <h2 className="font-semibold">{t('overview.cameras')}</h2>
            <ButtonLink
              to="/sites"
              size="sm"
              variant="ghost"
              icon={<ArrowRight className="size-4 rtl:-scale-x-100" aria-hidden />}
            >
              {t('nav.sites')}
            </ButtonLink>
          </div>
          {cameras.data ? (
            <ul className="divide-y divide-line">
              {cameras.data.map((c) => (
                <li key={c.id} className="flex items-center justify-between gap-3 p-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <Thumb src={c.snapshot_url} alt="" className="w-20 shrink-0" />
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{localName(c)}</p>
                      <p className="num text-xs text-ink-500">
                        {c.last_frame_at
                          ? t('overview.lastFrame', { time: fmt.relative(c.last_frame_at) })
                          : t('sites.never')}
                      </p>
                    </div>
                  </div>
                  <CameraStatusBadge status={c.status} />
                </li>
              ))}
            </ul>
          ) : (
            <Spinner />
          )}
        </section>
      </div>
    </Page>
  );
}
