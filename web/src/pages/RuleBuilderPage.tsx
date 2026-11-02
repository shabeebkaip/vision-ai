import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Bot, Check, Loader2, MessageSquareQuote, PenLine } from 'lucide-react';
import { useEffect, useId, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { useApi } from '../api';
import { ApiError } from '../api/client';
import type { Direction, Rule, RuleType, Severity } from '../api/models';
import { RULE_TYPES, SEVERITIES, ZONE_RULE_TYPES } from '../api/models';
import { RULE_ICONS } from '../components/EventBits';
import { Page, PageHeader } from '../components/layout/AppShell';
import { Button, ButtonLink } from '../components/ui/Button';
import { Field, SelectField } from '../components/ui/Field';
import { Spinner } from '../components/ui/States';
import { weekdayName } from '../lib/format';
import { useFormat } from '../lib/prefs';
import { qk, useCameras, useLocalName, useSites } from '../lib/queries';
import { WEEK_ORDER } from '../lib/rulePreview';
import { usePreviewBuilder, useRecipients } from '../lib/useRulePreview';

type ObjectKind = 'person' | 'vehicle';

export interface RuleForm {
  type: RuleType;
  name: string;
  cameraId: string;
  zoneId: string;
  lineId: string;
  objects: ObjectKind;
  threshold: number;
  durationMin: number;
  windowMin: number;
  direction: Direction;
  scheduleOn: boolean;
  days: number[];
  start: string;
  end: string;
  cooldownMin: number;
  severity: Severity;
  verify: boolean;
  recipientIds: string[];
}

const VEHICLE_CLASSES = ['car', 'truck', 'bus'];

/** Sensible starting values per rule type. */
export function defaultsFor(type: RuleType): Partial<RuleForm> {
  switch (type) {
    case 'queue_length_over':
      return {
        threshold: 5,
        durationMin: 2,
        scheduleOn: true,
        start: '09:00',
        end: '23:00',
        severity: 'warning',
        verify: false,
      };
    case 'zone_occupancy_over':
      return {
        threshold: 10,
        durationMin: 5,
        scheduleOn: false,
        severity: 'warning',
        verify: false,
      };
    case 'zone_empty':
      return {
        threshold: 0,
        durationMin: 5,
        scheduleOn: true,
        start: '09:00',
        end: '23:00',
        severity: 'warning',
        verify: false,
      };
    case 'dwell_over':
      return {
        threshold: 1,
        durationMin: 3,
        scheduleOn: false,
        severity: 'critical',
        verify: true,
      };
    case 'line_crossing':
      return {
        threshold: 20,
        windowMin: 10,
        direction: 'in',
        scheduleOn: false,
        severity: 'info',
        verify: false,
      };
    case 'presence_after_hours':
      return {
        threshold: 1,
        durationMin: 1,
        scheduleOn: true,
        start: '23:00',
        end: '06:00',
        severity: 'critical',
        verify: true,
      };
  }
}

/** Form state -> shared Rule (seconds, normalised ids, schedule as HH:MM:SS). */
export function toRule(f: RuleForm, id: string): Rule {
  const usesZone = ZONE_RULE_TYPES.has(f.type);
  return {
    id,
    name: f.name.trim(),
    type: f.type,
    camera_id: f.cameraId,
    zone_id: usesZone ? f.zoneId || null : null,
    line_id: f.type === 'line_crossing' ? f.lineId || null : null,
    classes: f.objects === 'person' ? ['person'] : VEHICLE_CLASSES,
    threshold: Math.max(0, Math.round(f.threshold)),
    min_duration_s: f.type === 'line_crossing' ? 0 : Math.max(0, Math.round(f.durationMin * 60)),
    window_s: f.type === 'line_crossing' ? Math.max(1, Math.round(f.windowMin * 60)) : 60,
    direction: f.type === 'line_crossing' ? f.direction : 'any',
    clear_after_s: 10,
    cooldown_s: Math.max(0, Math.round(f.cooldownMin * 60)),
    min_confidence: 0.4,
    schedule:
      f.scheduleOn || f.type === 'presence_after_hours'
        ? { days: [...f.days].sort((a, b) => a - b), start: `${f.start}:00`, end: `${f.end}:00` }
        : null,
    severity: f.severity,
    verify: f.verify,
    enabled: true,
  };
}

export function validateForm(f: RuleForm): Partial<Record<keyof RuleForm, string>> {
  const e: Partial<Record<keyof RuleForm, string>> = {};
  if (!f.name.trim()) e.name = 'rules.err.name';
  if (!f.cameraId) e.cameraId = 'rules.err.camera';
  if (ZONE_RULE_TYPES.has(f.type) && !f.zoneId) e.zoneId = 'rules.err.zone';
  if (f.type === 'line_crossing' && !f.lineId) e.lineId = 'rules.err.line';
  if (!Number.isFinite(f.threshold) || f.threshold < 0) e.threshold = 'rules.err.threshold';
  if ((f.scheduleOn || f.type === 'presence_after_hours') && f.days.length === 0)
    e.days = 'rules.err.days';
  if ((f.scheduleOn || f.type === 'presence_after_hours') && f.start === f.end)
    e.end = 'rules.err.window';
  return e;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="card p-4 sm:p-5">
      <h2 className="mb-4 font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function NumberField({
  label,
  value,
  onChange,
  min = 0,
  step = 1,
  suffix,
  error,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  step?: number;
  suffix?: string;
  error?: string | null;
}) {
  const id = useId();
  return (
    <Field label={label} htmlFor={id} error={error}>
      <div className="flex items-center gap-2">
        <input
          id={id}
          type="number"
          inputMode="decimal"
          min={min}
          step={step}
          className="input num w-28"
          value={Number.isFinite(value) ? value : ''}
          onChange={(e) => onChange(e.target.value === '' ? NaN : Number(e.target.value))}
        />
        {suffix && <span className="text-sm text-ink-500">{suffix}</span>}
      </div>
    </Field>
  );
}

export function RuleBuilderPage() {
  const { t } = useTranslation();
  const api = useApi();
  const fmt = useFormat();
  const localName = useLocalName();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  const sites = useSites();
  const [siteId, setSiteId] = useState(params.get('site') ?? '');
  useEffect(() => {
    if (!siteId && sites.data?.[0]) setSiteId(sites.data[0].id);
  }, [siteId, sites.data]);
  const cameras = useCameras(siteId || undefined);
  const recipients = useRecipients(siteId || undefined);
  const preview = usePreviewBuilder(cameras.data, recipients.data);

  const [form, setForm] = useState<RuleForm>(() => ({
    type: 'queue_length_over',
    name: '',
    cameraId: params.get('camera') ?? '',
    zoneId: '',
    lineId: '',
    objects: 'person',
    threshold: 5,
    durationMin: 2,
    windowMin: 10,
    direction: 'in',
    scheduleOn: true,
    days: [1, 2, 3, 4, 5, 6, 7],
    start: '09:00',
    end: '23:00',
    cooldownMin: 10,
    severity: 'warning',
    verify: false,
    recipientIds: [],
  }));
  const [touched, setTouched] = useState(false);
  const set = <K extends keyof RuleForm>(k: K, v: RuleForm[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const camera = cameras.data?.find((c) => c.id === form.cameraId);
  // Pick the first camera / zone / line / recipient automatically when the choice is obvious.
  useEffect(() => {
    if (!cameras.data?.length) return;
    if (!cameras.data.some((c) => c.id === form.cameraId)) set('cameraId', cameras.data[0]!.id);
  }, [cameras.data, form.cameraId]);
  useEffect(() => {
    if (!camera) return;
    setForm((f) => ({
      ...f,
      zoneId: camera.zones.some((z) => z.id === f.zoneId) ? f.zoneId : (camera.zones[0]?.id ?? ''),
      lineId: camera.lines.some((l) => l.id === f.lineId) ? f.lineId : (camera.lines[0]?.id ?? ''),
    }));
  }, [camera]);
  useEffect(() => {
    if (recipients.data?.length)
      setForm((f) =>
        f.recipientIds.length ? f : { ...f, recipientIds: [recipients.data[0]!.id] },
      );
  }, [recipients.data]);

  const chooseType = (type: RuleType) => setForm((f) => ({ ...f, type, ...defaultsFor(type) }));

  const errors = validateForm(form);
  const ruleId = useMemo(() => `rule-${Date.now().toString(36)}`, []);
  const rule = toRule(form, ruleId);
  const sentence = preview(rule, form.recipientIds);

  const save = useMutation({
    mutationFn: () => api.createRule(siteId, { rule, recipient_ids: form.recipientIds }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.rules(siteId) });
      navigate(`/rules?site=${encodeURIComponent(siteId)}`);
    },
  });

  const submit = () => {
    setTouched(true);
    if (Object.keys(errors).length === 0) save.mutate();
  };
  const err = (k: keyof RuleForm) => (touched && errors[k] ? t(errors[k]!) : null);

  if (sites.isPending)
    return (
      <Page>
        <Spinner />
      </Page>
    );

  const usesZone = ZONE_RULE_TYPES.has(form.type);
  const needsGeometry =
    camera &&
    ((usesZone && camera.zones.length === 0) ||
      (form.type === 'line_crossing' && camera.lines.length === 0));
  const scheduleLocked = form.type === 'presence_after_hours';
  const thresholdLabel =
    form.type === 'line_crossing'
      ? t('rules.form.crossings')
      : form.type === 'presence_after_hours'
        ? t('rules.form.atLeast')
        : t('rules.form.moreThan');

  return (
    <Page wide>
      <Link
        to="/rules"
        className="mb-2 inline-flex items-center gap-1.5 text-sm text-ink-500 hover:text-ink-900"
      >
        <ArrowLeft className="size-4 rtl:-scale-x-100" aria-hidden />
        {t('rules.back')}
      </Link>
      <PageHeader title={t('rules.newTitle')} subtitle={t('rules.newSubtitle')} />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
          noValidate
        >
          <Section title={t('rules.form.whatTitle')}>
            <div
              className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3"
              role="radiogroup"
              aria-label={t('rules.form.type')}
            >
              {RULE_TYPES.map((type) => {
                const Icon = RULE_ICONS[type];
                const active = form.type === type;
                return (
                  <button
                    key={type}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() => chooseType(type)}
                    className={`flex items-start gap-3 rounded-lg border p-3 text-start transition-colors ${
                      active
                        ? 'border-brand-500 bg-brand-50 ring-1 ring-brand-500'
                        : 'border-line hover:bg-canvas'
                    }`}
                  >
                    <Icon
                      className={`mt-0.5 size-5 shrink-0 ${active ? 'text-brand-700' : 'text-ink-500'}`}
                      aria-hidden
                    />
                    <span>
                      <span className="block text-sm font-medium">{t(`ruleType.${type}`)}</span>
                      <span className="block text-xs text-ink-500">
                        {t(`ruleTypeHelp.${type}`)}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </Section>

          <Section title={t('rules.form.whereTitle')}>
            <div className="grid gap-4 sm:grid-cols-2">
              <SelectField
                label={t('filters.site')}
                value={siteId}
                onChange={(e) => {
                  setSiteId(e.target.value);
                  setForm((f) => ({ ...f, cameraId: '', recipientIds: [] }));
                }}
                options={(sites.data ?? []).map((s) => ({ value: s.id, label: localName(s) }))}
              />
              <SelectField
                label={t('filters.camera')}
                value={form.cameraId}
                onChange={(e) => set('cameraId', e.target.value)}
                options={(cameras.data ?? []).map((c) => ({ value: c.id, label: localName(c) }))}
              />
              {usesZone && camera && camera.zones.length > 0 && (
                <SelectField
                  label={t('rules.form.zone')}
                  value={form.zoneId}
                  onChange={(e) => set('zoneId', e.target.value)}
                  options={camera.zones.map((z) => ({ value: z.id, label: z.name || z.id }))}
                />
              )}
              {form.type === 'line_crossing' && camera && camera.lines.length > 0 && (
                <SelectField
                  label={t('rules.form.line')}
                  value={form.lineId}
                  onChange={(e) => set('lineId', e.target.value)}
                  options={camera.lines.map((l) => ({ value: l.id, label: l.name || l.id }))}
                />
              )}
              <SelectField
                label={t('rules.form.objects')}
                value={form.objects}
                onChange={(e) => set('objects', e.target.value as ObjectKind)}
                options={[
                  { value: 'person', label: t('rules.form.people') },
                  { value: 'vehicle', label: t('rules.form.vehicles') },
                ]}
              />
            </div>
            {needsGeometry && (
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900 ring-1 ring-amber-200">
                <span>{usesZone ? t('rules.form.noZones') : t('rules.form.noLines')}</span>
                <ButtonLink
                  to={`/cameras/${encodeURIComponent(camera.id)}/zones`}
                  size="sm"
                  icon={<PenLine className="size-4" aria-hidden />}
                >
                  {t('sites.editZones')}
                </ButtonLink>
              </div>
            )}
          </Section>

          <Section title={t('rules.form.whenTitle')}>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {form.type !== 'zone_empty' && form.type !== 'dwell_over' && (
                <NumberField
                  label={thresholdLabel}
                  value={form.threshold}
                  onChange={(v) => set('threshold', v)}
                  suffix={
                    form.objects === 'person'
                      ? t('rules.form.peopleUnit')
                      : t('rules.form.vehiclesUnit')
                  }
                  error={err('threshold')}
                />
              )}
              {form.type !== 'line_crossing' ? (
                <NumberField
                  label={
                    form.type === 'dwell_over'
                      ? t('rules.form.stayLonger')
                      : t('rules.form.forAtLeast')
                  }
                  value={form.durationMin}
                  step={0.5}
                  onChange={(v) => set('durationMin', v)}
                  suffix={t('rules.form.minutes')}
                />
              ) : (
                <>
                  <NumberField
                    label={t('rules.form.within')}
                    value={form.windowMin}
                    min={1}
                    onChange={(v) => set('windowMin', v)}
                    suffix={t('rules.form.minutes')}
                  />
                  <SelectField
                    label={t('rules.form.direction')}
                    value={form.direction}
                    onChange={(e) => set('direction', e.target.value as Direction)}
                    options={(['in', 'out', 'any'] as const).map((d) => ({
                      value: d,
                      label: t(`direction.${d}`),
                    }))}
                  />
                </>
              )}
            </div>

            <div className="mt-5 border-t border-line pt-4">
              <label className="flex items-center gap-2 text-sm font-medium">
                <input
                  type="checkbox"
                  className="size-4 accent-brand-700"
                  checked={form.scheduleOn || scheduleLocked}
                  disabled={scheduleLocked}
                  onChange={(e) => set('scheduleOn', e.target.checked)}
                />
                {scheduleLocked ? t('rules.form.afterHoursWindow') : t('rules.form.onlyDuring')}
              </label>
              {(form.scheduleOn || scheduleLocked) && (
                <div className="mt-3 space-y-3">
                  <div
                    className="flex flex-wrap gap-1.5"
                    role="group"
                    aria-label={t('rules.form.days')}
                  >
                    {WEEK_ORDER.map((d) => {
                      const on = form.days.includes(d);
                      return (
                        <button
                          key={d}
                          type="button"
                          aria-pressed={on}
                          onClick={() =>
                            set('days', on ? form.days.filter((x) => x !== d) : [...form.days, d])
                          }
                          className={`h-9 min-w-12 rounded-lg border px-2 text-sm ${on ? 'border-brand-600 bg-brand-700 text-white' : 'border-line bg-white text-ink-700 hover:bg-canvas'}`}
                        >
                          {weekdayName(d, fmt.opts)}
                        </button>
                      );
                    })}
                  </div>
                  {err('days') && <p className="text-xs text-sev-critical">{err('days')}</p>}
                  <div className="flex flex-wrap items-end gap-3">
                    <Field label={t('rules.form.from')} htmlFor="sched-start">
                      <input
                        id="sched-start"
                        type="time"
                        className="input num w-32"
                        value={form.start}
                        onChange={(e) => set('start', e.target.value)}
                      />
                    </Field>
                    <Field label={t('rules.form.to')} htmlFor="sched-end" error={err('end')}>
                      <input
                        id="sched-end"
                        type="time"
                        className="input num w-32"
                        value={form.end}
                        onChange={(e) => set('end', e.target.value)}
                      />
                    </Field>
                    <p className="pb-2 text-xs text-ink-500">{t('rules.form.tzNote')}</p>
                  </div>
                </div>
              )}
            </div>
          </Section>

          <Section title={t('rules.form.alertTitle')}>
            <fieldset>
              <legend className="field-label">{t('rules.form.recipients')}</legend>
              {recipients.data?.length ? (
                <div className="grid gap-2 sm:grid-cols-2">
                  {recipients.data.map((r) => {
                    const on = form.recipientIds.includes(r.id);
                    return (
                      <label
                        key={r.id}
                        className={`flex items-center gap-3 rounded-lg border p-3 text-sm ${on ? 'border-brand-500 bg-brand-50' : 'border-line'}`}
                      >
                        <input
                          type="checkbox"
                          className="size-4 accent-brand-700"
                          checked={on}
                          onChange={() =>
                            set(
                              'recipientIds',
                              on
                                ? form.recipientIds.filter((x) => x !== r.id)
                                : [...form.recipientIds, r.id],
                            )
                          }
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block font-medium">{localName(r)}</span>
                          <span className="block text-xs text-ink-500">
                            {t(`channel.${r.channel}`)}
                          </span>
                        </span>
                      </label>
                    );
                  })}
                </div>
              ) : (
                <p className="text-sm text-ink-500">{t('rules.form.noRecipients')}</p>
              )}
            </fieldset>
            <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              <SelectField
                label={t('filters.severity')}
                value={form.severity}
                onChange={(e) => set('severity', e.target.value as Severity)}
                options={SEVERITIES.map((s) => ({ value: s, label: t(`severity.${s}`) }))}
              />
              <NumberField
                label={t('rules.form.cooldown')}
                value={form.cooldownMin}
                onChange={(v) => set('cooldownMin', v)}
                suffix={t('rules.form.minutes')}
              />
            </div>
            <label className="mt-4 flex items-start gap-3 rounded-lg border border-line p-3 text-sm">
              <input
                type="checkbox"
                className="mt-0.5 size-4 accent-brand-700"
                checked={form.verify}
                onChange={(e) => set('verify', e.target.checked)}
              />
              <span>
                <span className="flex items-center gap-1.5 font-medium">
                  <Bot className="size-4 text-ink-500" aria-hidden />
                  {t('rules.form.verify')}
                </span>
                <span className="block text-xs text-ink-500">{t('rules.form.verifyHelp')}</span>
              </span>
            </label>
          </Section>

          <Section title={t('rules.form.nameTitle')}>
            <Field
              label={t('rules.form.name')}
              htmlFor="rule-name"
              error={err('name')}
              hint={t('rules.form.nameHint')}
            >
              <input
                id="rule-name"
                dir="auto"
                className="input"
                value={form.name}
                maxLength={80}
                placeholder={t(`ruleType.${form.type}`)}
                onChange={(e) => set('name', e.target.value)}
              />
            </Field>
          </Section>
        </form>

        <aside className="lg:sticky lg:top-6 lg:self-start">
          <div className="card space-y-4 p-4 sm:p-5">
            <h2 className="flex items-center gap-2 font-semibold">
              <MessageSquareQuote className="size-4 text-brand-700" aria-hidden />
              {t('rules.preview')}
            </h2>
            <p
              className="rounded-lg bg-brand-50 p-4 text-[15px] leading-relaxed text-brand-900"
              data-testid="rule-preview"
              aria-live="polite"
            >
              {sentence}
            </p>
            {touched && Object.keys(errors).length > 0 && (
              <ul role="alert" className="list-inside list-disc text-sm text-sev-critical">
                {Object.values(errors).map((k) => (
                  <li key={k}>{t(k)}</li>
                ))}
              </ul>
            )}
            {save.isError && (
              <p role="alert" className="text-sm text-sev-critical">
                {save.error instanceof ApiError ? save.error.message : t('errors.saveFailed')}
              </p>
            )}
            <Button
              size="lg"
              className="w-full"
              disabled={save.isPending || !siteId}
              onClick={submit}
              icon={
                save.isPending ? (
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                ) : (
                  <Check className="size-4" aria-hidden />
                )
              }
            >
              {t('rules.create')}
            </Button>
            <p className="text-xs text-ink-500">{t('rules.createHint')}</p>
          </div>
        </aside>
      </div>
    </Page>
  );
}
