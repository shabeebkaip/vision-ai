import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Bot, Check, Loader2, MapPin, Pencil, ThumbsDown, ThumbsUp } from 'lucide-react';
import { useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router';
import { useApi } from '../api';
import type { AiCheck, EventView, Verdict } from '../api/models';
import { RuleTypeLabel, useEventSummary } from '../components/EventBits';
import { EventMedia } from '../components/MediaViewer';
import { Page } from '../components/layout/AppShell';
import { SeverityBadge, StateBadge, VerdictBadge } from '../components/ui/Badges';
import { Button, ButtonLink } from '../components/ui/Button';
import { ErrorState, Spinner } from '../components/ui/States';
import { useFormat } from '../lib/prefs';
import { qk, useLocalName, useSites } from '../lib/queries';
import { useSiteRules } from '../lib/useRulePreview';

function aiCheckOf(e: EventView): AiCheck | null {
  const v = e.attributes.ai_check as Partial<AiCheck> | undefined;
  if (!v || typeof v !== 'object' || typeof v.verdict !== 'string') return null;
  return {
    verdict: v.verdict as AiCheck['verdict'],
    reason: typeof v.reason === 'string' ? v.reason : '',
  };
}

function FeedbackCard({ event }: { event: EventView }) {
  const { t } = useTranslation();
  const api = useApi();
  const fmt = useFormat();
  const queryClient = useQueryClient();
  const noteId = useId();
  const [verdict, setVerdict] = useState<Verdict | null>(event.feedback?.verdict ?? null);
  const [note, setNote] = useState(event.feedback?.note ?? '');
  const [editing, setEditing] = useState(!event.feedback);
  useEffect(() => {
    setVerdict(event.feedback?.verdict ?? null);
    setNote(event.feedback?.note ?? '');
    setEditing(!event.feedback);
  }, [event.id, event.feedback]);

  const mutation = useMutation({
    mutationFn: (v: Verdict) => api.submitFeedback(event.id, { verdict: v, note }),
    onSuccess: (updated) => {
      queryClient.setQueryData(qk.event(event.id), updated);
      void queryClient.invalidateQueries({ queryKey: ['events'] });
      void queryClient.invalidateQueries({ queryKey: ['overview'] });
      setEditing(false);
    },
  });

  return (
    <section className="card p-4" aria-labelledby="feedback-title">
      <h2 id="feedback-title" className="font-semibold">
        {t('feedback.title')}
      </h2>
      <p className="mt-0.5 text-sm text-ink-500">{t('feedback.help')}</p>

      {event.feedback && !editing ? (
        <div className="mt-4 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <VerdictBadge verdict={event.feedback.verdict} />
            <span className="text-xs text-ink-500">
              {event.feedback.by
                ? t('feedback.by', {
                    name: event.feedback.by,
                    time: fmt.dateTime(event.feedback.at),
                  })
                : t('feedback.at', { time: fmt.dateTime(event.feedback.at) })}
            </span>
          </div>
          {event.feedback.note && (
            <p dir="auto" className="rounded-lg bg-canvas p-3 text-sm text-ink-700">
              {event.feedback.note}
            </p>
          )}
          <Button
            variant="secondary"
            size="sm"
            icon={<Pencil className="size-4" aria-hidden />}
            onClick={() => setEditing(true)}
          >
            {t('feedback.change')}
          </Button>
        </div>
      ) : (
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <Button
              variant={verdict === 'correct' ? 'success' : 'secondary'}
              size="lg"
              aria-pressed={verdict === 'correct'}
              disabled={mutation.isPending}
              onClick={() => setVerdict('correct')}
              icon={<ThumbsUp className="size-5" aria-hidden />}
            >
              {t('feedback.correct')}
            </Button>
            <Button
              variant={verdict === 'false_alarm' ? 'danger' : 'secondary'}
              size="lg"
              aria-pressed={verdict === 'false_alarm'}
              disabled={mutation.isPending}
              onClick={() => setVerdict('false_alarm')}
              icon={<ThumbsDown className="size-5" aria-hidden />}
            >
              {t('feedback.falseAlarm')}
            </Button>
          </div>
          <div>
            <label htmlFor={noteId} className="field-label">
              {t('feedback.note')}
            </label>
            <textarea
              id={noteId}
              dir="auto"
              rows={3}
              maxLength={500}
              className="input resize-y"
              placeholder={t('feedback.notePlaceholder')}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
            <p className="mt-1 text-xs text-ink-500">{t('feedback.noteHint')}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              className="flex-1 sm:flex-none"
              disabled={!verdict || mutation.isPending}
              onClick={() => verdict && mutation.mutate(verdict)}
              icon={
                mutation.isPending ? (
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                ) : undefined
              }
            >
              {mutation.isPending ? t('common.saving') : t('feedback.save')}
            </Button>
            {event.feedback && (
              <Button variant="ghost" onClick={() => setEditing(false)}>
                {t('common.cancel')}
              </Button>
            )}
          </div>
          {mutation.isError && (
            <p role="alert" className="text-sm text-sev-critical">
              {t('errors.saveFailed')}
            </p>
          )}
        </div>
      )}
      {mutation.isSuccess && !editing && (
        <p className="mt-3 flex items-center gap-1.5 text-sm text-emerald-700" role="status">
          <Check className="size-4" aria-hidden /> {t('feedback.saved')}
        </p>
      )}
    </section>
  );
}

function AiCheckCard({ event }: { event: EventView }) {
  const { t } = useTranslation();
  const check = aiCheckOf(event);
  const tone =
    check?.verdict === 'confirmed'
      ? 'bg-emerald-50 text-emerald-800 ring-emerald-200'
      : check?.verdict === 'rejected'
        ? 'bg-amber-50 text-amber-900 ring-amber-200'
        : 'bg-canvas text-ink-700 ring-line';
  return (
    <section className="card p-4">
      <h2 className="flex items-center gap-2 font-semibold">
        <Bot className="size-4 text-ink-500" aria-hidden />
        {t('aiCheck.title')}
      </h2>
      {!event.needs_verification ? (
        <p className="mt-2 text-sm text-ink-500">{t('aiCheck.off')}</p>
      ) : check ? (
        <div className={`mt-3 rounded-lg p-3 text-sm ring-1 ${tone}`}>
          <p className="font-medium">{t(`aiCheck.${check.verdict}`)}</p>
          {check.reason && (
            <p className="mt-1" dir="auto">
              {check.reason}
            </p>
          )}
        </div>
      ) : (
        <p className="mt-2 text-sm text-ink-500">{t('aiCheck.pending')}</p>
      )}
    </section>
  );
}

export function EventDetailPage() {
  const { eventId = '' } = useParams();
  const { t } = useTranslation();
  const api = useApi();
  const localName = useLocalName();
  const summary = useEventSummary();
  const query = useQuery({ queryKey: qk.event(eventId), queryFn: () => api.getEvent(eventId) });
  const event = query.data;
  const sites = useSites();
  const site = sites.data?.find((s) => s.id === event?.site_id);
  const fmt = useFormat(site?.timezone);
  const { cameras, byId, preview } = useSiteRules(event?.site_id);
  const camera = cameras.data?.find((c) => c.id === event?.camera_id);
  const rr = event ? byId.get(event.rule_id) : undefined;

  const back = (
    <Link
      to="/events"
      className="mb-2 inline-flex items-center gap-1.5 text-sm text-ink-500 hover:text-ink-900"
    >
      <ArrowLeft className="size-4 rtl:-scale-x-100" aria-hidden />
      {t('event.back')}
    </Link>
  );

  if (query.isPending)
    return (
      <Page>
        {back}
        <Spinner />
      </Page>
    );
  if (query.isError || !event)
    return (
      <Page>
        {back}
        <div className="card">
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        </div>
      </Page>
    );

  const timeline: { label: string; at: string | null }[] = [
    { label: t('event.conditionStarted'), at: event.condition_started_at },
    { label: t('event.triggered'), at: event.triggered_at },
    { label: t('event.cleared'), at: event.cleared_at },
  ];

  return (
    <Page wide>
      {back}
      <header className="mb-5">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
            <RuleTypeLabel type={event.rule_type} withIcon={false} />
          </h1>
          <SeverityBadge severity={event.severity} />
          <StateBadge state={event.state} />
        </div>
        <p className="mt-1 text-ink-700">{summary(event)}</p>
        <p className="mt-1 flex flex-wrap items-center gap-x-2 text-sm text-ink-500">
          <MapPin className="size-4" aria-hidden />
          <span>{localName(site, event.site_id)}</span>
          <span aria-hidden>·</span>
          <span>{localName(camera, event.camera_id)}</span>
          <span aria-hidden>·</span>
          <time dateTime={event.triggered_at} className="num">
            {fmt.dateTime(event.triggered_at)}
          </time>
        </p>
      </header>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 lg:col-start-1 lg:row-start-1">
          <EventMedia
            event={event}
            camera={camera}
            zoneId={rr?.rule.zone_id}
            lineId={rr?.rule.line_id}
          />
        </div>

        <aside className="space-y-4 lg:col-start-2 lg:row-span-2 lg:row-start-1">
          <FeedbackCard event={event} />
          <AiCheckCard event={event} />
          <section className="card p-4">
            <h2 className="font-semibold">{t('event.rule')}</h2>
            {rr ? (
              <>
                <p className="mt-1 text-sm font-medium text-ink-700" dir="auto">
                  {rr.rule.name}
                </p>
                <p className="mt-2 rounded-lg bg-brand-50 p-3 text-sm leading-relaxed text-brand-900">
                  {preview(rr.rule, rr.recipient_ids)}
                </p>
              </>
            ) : (
              <p className="mt-2 text-sm text-ink-500">
                {t('event.ruleUnknown', { id: event.rule_id })}
              </p>
            )}
            {camera && (
              <ButtonLink
                to={`/cameras/${encodeURIComponent(camera.id)}/zones`}
                variant="ghost"
                size="sm"
                className="-ms-3 mt-2"
              >
                {t('event.openCamera')}
              </ButtonLink>
            )}
          </section>
        </aside>

        <section className="card p-4 lg:col-start-1 lg:row-start-2">
          <h2 className="font-semibold">{t('event.details')}</h2>
          <ol className="mt-3 grid gap-3 sm:grid-cols-3">
            {timeline.map((item) => (
              <li key={item.label} className="rounded-lg bg-canvas p-3">
                <p className="text-xs text-ink-500">{item.label}</p>
                <p className="num mt-0.5 text-sm font-medium">
                  {item.at ? fmt.dateTimeSeconds(item.at) : t('event.stillActive')}
                </p>
              </li>
            ))}
          </ol>
          {event.message && (
            <div className="mt-4">
              <p className="text-xs font-medium text-ink-500">{t('event.message')}</p>
              <p
                dir="auto"
                className="mt-1 rounded-lg border border-line p-3 font-mono text-[13px] text-ink-700"
              >
                {event.message}
              </p>
            </div>
          )}
        </section>
      </div>
    </Page>
  );
}
