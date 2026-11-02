import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

export function LogoMark({ className = 'size-8' }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <rect width="32" height="32" rx="8" fill="#0b5d57" />
      <path
        d="M6 16c2.8-4.7 6.1-7 10-7s7.2 2.3 10 7c-2.8 4.7-6.1 7-10 7s-7.2-2.3-10-7z"
        fill="none"
        stroke="#fff"
        strokeWidth="2.2"
      />
      <circle cx="16" cy="16" r="3.6" fill="#5eead4" />
    </svg>
  );
}

export function Logo({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation();
  return (
    <Link to="/" className="flex items-center gap-2.5" aria-label={t('app.name')}>
      <LogoMark />
      <span className="leading-tight">
        <span className="block text-[15px] font-semibold text-ink-900">{t('app.name')}</span>
        {!compact && <span className="block text-xs text-ink-500">{t('app.tagline')}</span>}
      </span>
    </Link>
  );
}
