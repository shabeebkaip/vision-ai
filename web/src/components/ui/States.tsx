import { AlertTriangle, Inbox, Loader2, RefreshCw } from 'lucide-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../api/client';
import { Button } from './Button';

export function Spinner({ label }: { label?: string }) {
  const { t } = useTranslation();
  return (
    <div
      role="status"
      className="flex items-center justify-center gap-2 py-10 text-sm text-ink-500"
    >
      <Loader2 className="size-4 animate-spin" aria-hidden />
      <span>{label ?? t('common.loading')}</span>
    </div>
  );
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-ink-900/5 ${className}`} aria-hidden />;
}

export function EmptyState({
  title,
  body,
  action,
  icon,
}: {
  title: string;
  body?: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
      <div className="grid size-12 place-items-center rounded-full bg-brand-50 text-brand-700">
        {icon ?? <Inbox className="size-6" aria-hidden />}
      </div>
      <div>
        <p className="font-semibold text-ink-900">{title}</p>
        {body && <p className="mt-1 max-w-sm text-sm text-ink-500">{body}</p>}
      </div>
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useTranslation();
  const notFound = error instanceof ApiError && error.status === 404;
  return (
    <div
      role="alert"
      className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center"
    >
      <div className="grid size-12 place-items-center rounded-full bg-red-50 text-sev-critical">
        <AlertTriangle className="size-6" aria-hidden />
      </div>
      <div>
        <p className="font-semibold text-ink-900">
          {notFound ? t('errors.notFoundTitle') : t('errors.title')}
        </p>
        <p className="mt-1 max-w-sm text-sm text-ink-500">
          {notFound ? t('errors.notFoundBody') : t('errors.body')}
        </p>
      </div>
      {onRetry && !notFound && (
        <Button
          variant="secondary"
          onClick={onRetry}
          icon={<RefreshCw className="size-4" aria-hidden />}
        >
          {t('common.retry')}
        </Button>
      )}
    </div>
  );
}
