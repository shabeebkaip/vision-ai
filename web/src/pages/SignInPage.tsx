import { AlertCircle, Loader2, ShieldCheck } from 'lucide-react';
import { useId, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Navigate, useLocation, useNavigate } from 'react-router';
import { useApi } from '../api';
import { ApiError } from '../api/client';
import { MOCK_PASSWORD } from '../api/mock/mockClient';
import { useAuth } from '../auth';
import { LanguageToggle } from '../components/layout/AppShell';
import { LogoMark } from '../components/layout/Logo';
import { Button } from '../components/ui/Button';

export function SignInPage() {
  const { t } = useTranslation();
  const api = useApi();
  const { session, signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? '/';
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const emailId = useId();
  const passwordId = useId();

  if (session) return <Navigate to={from} replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!email.trim() || !password) {
      setError(t('auth.missingFields'));
      return;
    }
    setBusy(true);
    try {
      await signIn(email.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401 ? t('auth.invalid') : t('errors.body'),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-dvh lg:grid-cols-[1fr_minmax(0,560px)]">
      <section className="relative hidden overflow-hidden bg-brand-800 p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="flex items-center gap-3">
          <LogoMark className="size-10" />
          <span className="text-lg font-semibold">{t('app.name')}</span>
        </div>
        <div className="max-w-md">
          <h2 className="text-3xl leading-snug font-semibold">{t('auth.heroTitle')}</h2>
          <p className="mt-4 text-brand-100">{t('auth.heroBody')}</p>
        </div>
        <p className="flex items-center gap-2 text-sm text-brand-200">
          <ShieldCheck className="size-4" aria-hidden />
          {t('auth.privacy')}
        </p>
        <svg
          className="pointer-events-none absolute -end-24 -top-24 size-[420px] opacity-10"
          viewBox="0 0 100 100"
          aria-hidden
        >
          <circle cx="50" cy="50" r="48" fill="none" stroke="white" strokeWidth="0.6" />
          <circle cx="50" cy="50" r="34" fill="none" stroke="white" strokeWidth="0.6" />
          <circle cx="50" cy="50" r="20" fill="none" stroke="white" strokeWidth="0.6" />
        </svg>
      </section>

      <section className="flex flex-col px-4 py-6 sm:px-10">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 lg:invisible">
            <LogoMark />
            <span className="font-semibold">{t('app.name')}</span>
          </div>
          <LanguageToggle />
        </div>
        <div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center py-10">
          <h1 className="text-2xl font-semibold tracking-tight">{t('auth.title')}</h1>
          <p className="mt-1 text-sm text-ink-500">{t('auth.subtitle')}</p>
          <form className="mt-8 space-y-4" onSubmit={onSubmit} noValidate>
            <div>
              <label htmlFor={emailId} className="field-label">
                {t('auth.email')}
              </label>
              <input
                id={emailId}
                type="email"
                autoComplete="username"
                inputMode="email"
                dir="ltr"
                className="input h-11 text-start rtl:text-end"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@company.sa"
              />
            </div>
            <div>
              <div className="flex items-center justify-between">
                <label htmlFor={passwordId} className="field-label">
                  {t('auth.password')}
                </label>
                <span className="mb-1 text-xs text-ink-400">{t('auth.forgotSoon')}</span>
              </div>
              <input
                id={passwordId}
                type="password"
                autoComplete="current-password"
                dir="ltr"
                className="input h-11"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            {error && (
              <p
                role="alert"
                className="flex items-center gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-sev-critical"
              >
                <AlertCircle className="size-4 shrink-0" aria-hidden />
                {error}
              </p>
            )}
            <Button type="submit" size="lg" className="w-full" disabled={busy}>
              {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
              {t('auth.signIn')}
            </Button>
          </form>
          {api.mode === 'mock' && (
            <div className="mt-6 rounded-lg border border-dashed border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
              <p className="font-medium">{t('auth.demoTitle')}</p>
              <p className="mt-0.5">
                {t('auth.demoBody')}{' '}
                <code dir="ltr" className="rounded bg-white px-1.5 py-0.5 font-mono text-xs">
                  {MOCK_PASSWORD}
                </code>
              </p>
            </div>
          )}
        </div>
        <p className="text-center text-xs text-ink-400">{t('auth.footer')}</p>
      </section>
    </div>
  );
}
