import { CheckCircle2, CircleDot, XCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { CameraStatus, EventState, Severity, Verdict } from '../../api/models';

const pill =
  'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap';

const SEVERITY: Record<Severity, string> = {
  critical: 'bg-red-50 text-sev-critical ring-1 ring-red-200',
  warning: 'bg-amber-50 text-sev-warning ring-1 ring-amber-200',
  info: 'bg-blue-50 text-sev-info ring-1 ring-blue-200',
};

const SEVERITY_DOT: Record<Severity, string> = {
  critical: 'bg-sev-critical',
  warning: 'bg-amber-500',
  info: 'bg-sev-info',
};

export const SEVERITY_BAR: Record<Severity, string> = {
  critical: 'bg-sev-critical',
  warning: 'bg-amber-500',
  info: 'bg-sev-info',
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  const { t } = useTranslation();
  return (
    <span className={`${pill} ${SEVERITY[severity]}`}>
      <span className={`size-1.5 rounded-full ${SEVERITY_DOT[severity]}`} aria-hidden />
      {t(`severity.${severity}`)}
    </span>
  );
}

export function StateBadge({ state }: { state: EventState }) {
  const { t } = useTranslation();
  return state === 'triggered' ? (
    <span className={`${pill} bg-red-600 text-white`}>
      <CircleDot className="size-3" aria-hidden />
      {t('eventState.triggered')}
    </span>
  ) : (
    <span className={`${pill} bg-ink-900/5 text-ink-700`}>{t('eventState.cleared')}</span>
  );
}

export function VerdictBadge({ verdict }: { verdict: Verdict | null }) {
  const { t } = useTranslation();
  if (!verdict)
    return (
      <span className={`${pill} bg-white text-ink-500 ring-1 ring-line`}>{t('verdict.none')}</span>
    );
  return verdict === 'correct' ? (
    <span className={`${pill} bg-emerald-50 text-emerald-800 ring-1 ring-emerald-200`}>
      <CheckCircle2 className="size-3" aria-hidden />
      {t('verdict.correct')}
    </span>
  ) : (
    <span className={`${pill} bg-ink-900/5 text-ink-700 ring-1 ring-line`}>
      <XCircle className="size-3" aria-hidden />
      {t('verdict.false_alarm')}
    </span>
  );
}

const STATUS: Record<CameraStatus, string> = {
  online: 'bg-emerald-50 text-emerald-800 ring-1 ring-emerald-200',
  degraded: 'bg-amber-50 text-amber-800 ring-1 ring-amber-200',
  offline: 'bg-red-50 text-sev-critical ring-1 ring-red-200',
};
const STATUS_DOT: Record<CameraStatus, string> = {
  online: 'bg-emerald-500',
  degraded: 'bg-amber-500',
  offline: 'bg-sev-critical',
};

export function CameraStatusBadge({ status }: { status: CameraStatus }) {
  const { t } = useTranslation();
  return (
    <span className={`${pill} ${STATUS[status]}`}>
      <span className={`size-1.5 rounded-full ${STATUS_DOT[status]}`} aria-hidden />
      {t(`cameraStatus.${status}`)}
    </span>
  );
}
