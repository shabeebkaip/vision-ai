import { useTranslation } from 'react-i18next';
import type { EventView, RuleType } from '../api/models';
import { describeDuration } from '../lib/rulePreview';
import { useFormat } from '../lib/prefs';
import {
  Armchair,
  Clock3,
  DoorOpen,
  ImageOff,
  MoonStar,
  UserX,
  Users,
  type LucideIcon,
} from 'lucide-react';

export const RULE_ICONS: Record<RuleType, LucideIcon> = {
  queue_length_over: Users,
  zone_occupancy_over: Armchair,
  zone_empty: UserX,
  presence_after_hours: MoonStar,
  dwell_over: Clock3,
  line_crossing: DoorOpen,
};

/** Short localized summary of what was measured, e.g. "7 people waiting". */
export function useEventSummary() {
  const { t } = useTranslation();
  const fmt = useFormat();
  return (
    e: Pick<EventView, 'rule_type' | 'value'> &
      Partial<Pick<EventView, 'condition_started_at' | 'triggered_at'>>,
  ): string => {
    const count = Math.round(e.value);
    // "Unattended": the edge sends the people count (0) as the value; how long the place was
    // empty is the time from the condition starting to the alert.
    const seconds =
      e.rule_type === 'zone_empty' && e.condition_started_at && e.triggered_at
        ? Math.max(0, (Date.parse(e.triggered_at) - Date.parse(e.condition_started_at)) / 1000)
        : e.value;
    const vars = {
      count,
      n: fmt.number(count),
      duration: describeDuration(seconds, t, fmt.opts),
    };
    return t(`eventValue.${e.rule_type}`, vars);
  };
}

export function RuleTypeLabel({ type, withIcon = true }: { type: RuleType; withIcon?: boolean }) {
  const { t } = useTranslation();
  const Icon = RULE_ICONS[type];
  return (
    <span className="inline-flex items-center gap-1.5">
      {withIcon && <Icon className="size-4 shrink-0 text-ink-500" aria-hidden />}
      {t(`ruleType.${type}`)}
    </span>
  );
}

export function Thumb({
  src,
  alt,
  className = '',
}: {
  src: string | null;
  alt: string;
  className?: string;
}) {
  const { t } = useTranslation();
  if (!src) {
    return (
      <div
        className={`grid aspect-video place-items-center rounded-lg bg-ink-900/5 text-ink-400 ${className}`}
        title={t('event.noSnapshot')}
      >
        <ImageOff className="size-5" aria-hidden />
      </div>
    );
  }
  return (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      decoding="async"
      className={`aspect-video rounded-lg bg-ink-900/10 object-cover ${className}`}
    />
  );
}
