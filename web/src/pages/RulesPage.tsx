import { Plus } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router';
import { RULE_ICONS } from '../components/EventBits';
import { Page, PageHeader } from '../components/layout/AppShell';
import { SeverityBadge } from '../components/ui/Badges';
import { ButtonLink } from '../components/ui/Button';
import { EmptyState, ErrorState, Spinner } from '../components/ui/States';
import { useLocalName, useSites } from '../lib/queries';
import { useSiteRules } from '../lib/useRulePreview';

export function RulesPage() {
  const { t } = useTranslation();
  const localName = useLocalName();
  const [params, setParams] = useSearchParams();
  const sites = useSites();
  const siteId = params.get('site') ?? sites.data?.[0]?.id;
  const { rules, cameras, preview } = useSiteRules(siteId);

  return (
    <Page wide>
      <PageHeader
        title={t('rules.title')}
        subtitle={t('rules.subtitle')}
        actions={
          <>
            <select
              aria-label={t('filters.site')}
              className="input h-10 w-auto min-w-56 pe-8"
              value={siteId ?? ''}
              onChange={(e) => setParams({ site: e.target.value }, { replace: true })}
            >
              {(sites.data ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {localName(s)}
                </option>
              ))}
            </select>
            <ButtonLink
              to={`/rules/new${siteId ? `?site=${encodeURIComponent(siteId)}` : ''}`}
              variant="primary"
              icon={<Plus className="size-4" aria-hidden />}
            >
              {t('rules.new')}
            </ButtonLink>
          </>
        }
      />
      {rules.isPending || sites.isPending ? (
        <Spinner />
      ) : rules.isError ? (
        <div className="card">
          <ErrorState error={rules.error} onRetry={() => void rules.refetch()} />
        </div>
      ) : rules.data.length === 0 ? (
        <div className="card">
          <EmptyState title={t('rules.emptyTitle')} body={t('rules.emptyBody')} />
        </div>
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {rules.data.map(({ rule, recipient_ids }) => {
            const Icon = RULE_ICONS[rule.type];
            const cam = cameras.data?.find((c) => c.id === rule.camera_id);
            return (
              <li key={rule.id} className="card flex flex-col gap-3 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-start gap-3">
                    <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-brand-50 text-brand-700">
                      <Icon className="size-[18px]" aria-hidden />
                    </span>
                    <div className="min-w-0">
                      <p className="truncate font-semibold" dir="auto">
                        {rule.name}
                      </p>
                      <p className="text-xs text-ink-500">
                        {t(`ruleType.${rule.type}`)} · {localName(cam, rule.camera_id)}
                      </p>
                    </div>
                  </div>
                  <SeverityBadge severity={rule.severity} />
                </div>
                <p className="rounded-lg bg-canvas p-3 text-sm leading-relaxed text-ink-700">
                  {preview(rule, recipient_ids)}
                </p>
              </li>
            );
          })}
        </ul>
      )}
    </Page>
  );
}
