import { Pill, PenLine, Plus, Store, Warehouse, type LucideIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { CameraView, Industry, SiteSummary } from '../api/models';
import { Thumb } from '../components/EventBits';
import { Page, PageHeader } from '../components/layout/AppShell';
import { CameraStatusBadge } from '../components/ui/Badges';
import { ButtonLink } from '../components/ui/Button';
import { EmptyState, ErrorState, Spinner } from '../components/ui/States';
import { useFormat } from '../lib/prefs';
import { useCameras, useLocalName, useSites } from '../lib/queries';

export const INDUSTRY_ICONS: Partial<Record<Industry, LucideIcon>> = {
  restaurant: Store,
  pharmacy: Pill,
  warehouse: Warehouse,
};

function CameraActions({ camera }: { camera: CameraView }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap gap-2">
      <ButtonLink
        to={`/cameras/${encodeURIComponent(camera.id)}/zones`}
        size="sm"
        icon={<PenLine className="size-4" aria-hidden />}
      >
        {t('sites.editZones')}
      </ButtonLink>
      <ButtonLink
        to={`/rules/new?site=${encodeURIComponent(camera.site_id)}&camera=${encodeURIComponent(camera.id)}`}
        size="sm"
        variant="ghost"
        icon={<Plus className="size-4" aria-hidden />}
      >
        {t('sites.addRule')}
      </ButtonLink>
    </div>
  );
}

function SiteCard({ site, cameras }: { site: SiteSummary; cameras: CameraView[] }) {
  const { t } = useTranslation();
  const fmt = useFormat(site.timezone);
  const localName = useLocalName();
  const Icon = INDUSTRY_ICONS[site.industry] ?? Store;
  return (
    <section className="card overflow-hidden" aria-labelledby={`site-${site.id}`}>
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line p-4">
        <div className="flex min-w-0 items-center gap-3">
          <div className="grid size-10 shrink-0 place-items-center rounded-lg bg-brand-50 text-brand-700">
            <Icon className="size-5" aria-hidden />
          </div>
          <div className="min-w-0">
            <h2 id={`site-${site.id}`} className="truncate font-semibold">
              {localName(site)}
            </h2>
            <p className="text-sm text-ink-500">
              {t(`industry.${site.industry}`)} ·{' '}
              {t(`city.${site.city}`, { defaultValue: site.city })}
            </p>
          </div>
        </div>
        <dl className="flex gap-6 text-sm">
          <div>
            <dt className="text-xs text-ink-500">{t('sites.camerasOnline')}</dt>
            <dd className="num font-semibold">
              {fmt.number(site.cameras_online)} / {fmt.number(site.cameras_total)}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-ink-500">{t('sites.alertsToday')}</dt>
            <dd className="num font-semibold">{fmt.number(site.alerts_today)}</dd>
          </div>
        </dl>
      </header>

      {/* Table on wider screens */}
      <table className="hidden w-full text-sm md:table">
        <thead className="bg-canvas text-xs text-ink-500">
          <tr>
            <th scope="col" className="px-4 py-2 text-start font-medium">
              {t('sites.camera')}
            </th>
            <th scope="col" className="px-4 py-2 text-start font-medium">
              {t('sites.status')}
            </th>
            <th scope="col" className="px-4 py-2 text-start font-medium">
              {t('sites.lastFrame')}
            </th>
            <th scope="col" className="px-4 py-2 text-start font-medium">
              {t('sites.geometry')}
            </th>
            <th scope="col" className="px-4 py-2 text-end font-medium">
              <span className="sr-only">{t('sites.actions')}</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {cameras.map((c) => (
            <tr key={c.id}>
              <td className="px-4 py-3">
                <div className="flex items-center gap-3">
                  <Thumb src={c.snapshot_url} alt={localName(c)} className="w-24" />
                  <div>
                    <p className="font-medium">{localName(c)}</p>
                    <p className="num text-xs text-ink-500">
                      {t('sites.fps', { n: fmt.number(c.fps) })}
                    </p>
                  </div>
                </div>
              </td>
              <td className="px-4 py-3">
                <CameraStatusBadge status={c.status} />
              </td>
              <td className="num px-4 py-3 text-ink-700">
                {c.last_frame_at ? fmt.relative(c.last_frame_at) : t('sites.never')}
              </td>
              <td className="px-4 py-3 text-ink-700">
                {t('sites.zonesCount', { count: c.zones.length, n: fmt.number(c.zones.length) })} ·{' '}
                {t('sites.linesCount', { count: c.lines.length, n: fmt.number(c.lines.length) })}
              </td>
              <td className="px-4 py-3">
                <div className="flex justify-end">
                  <CameraActions camera={c} />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Cards on phones */}
      <ul className="divide-y divide-line md:hidden">
        {cameras.map((c) => (
          <li key={c.id} className="space-y-3 p-4">
            <div className="flex gap-3">
              <Thumb src={c.snapshot_url} alt={localName(c)} className="w-28 shrink-0" />
              <div className="min-w-0 space-y-1">
                <p className="font-medium">{localName(c)}</p>
                <CameraStatusBadge status={c.status} />
                <p className="num text-xs text-ink-500">
                  {c.last_frame_at ? fmt.relative(c.last_frame_at) : t('sites.never')} ·{' '}
                  {t('sites.zonesCount', { count: c.zones.length, n: fmt.number(c.zones.length) })}
                </p>
              </div>
            </div>
            <CameraActions camera={c} />
          </li>
        ))}
      </ul>
    </section>
  );
}

export function SitesPage() {
  const { t } = useTranslation();
  const sites = useSites();
  const cameras = useCameras();
  return (
    <Page wide>
      <PageHeader title={t('sites.title')} subtitle={t('sites.subtitle')} />
      {sites.isPending || cameras.isPending ? (
        <Spinner />
      ) : sites.isError || cameras.isError ? (
        <div className="card">
          <ErrorState
            error={sites.error ?? cameras.error}
            onRetry={() => {
              void sites.refetch();
              void cameras.refetch();
            }}
          />
        </div>
      ) : sites.data.length === 0 ? (
        <div className="card">
          <EmptyState title={t('sites.emptyTitle')} body={t('sites.emptyBody')} />
        </div>
      ) : (
        <div className="space-y-5">
          {sites.data.map((s) => (
            <SiteCard
              key={s.id}
              site={s}
              cameras={cameras.data.filter((c) => c.site_id === s.id)}
            />
          ))}
        </div>
      )}
    </Page>
  );
}
