import {
  Bell,
  Cctv,
  Languages,
  LayoutDashboard,
  LogOut,
  Menu,
  SlidersHorizontal,
  X,
} from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { NavLink, Outlet } from 'react-router';
import { useApi } from '../../api';
import { useAuth } from '../../auth';
import { usePrefs } from '../../lib/prefs';
import { Logo } from './Logo';

const NAV = [
  { to: '/', key: 'nav.overview', icon: LayoutDashboard, end: true },
  { to: '/events', key: 'nav.events', icon: Bell, end: false },
  { to: '/sites', key: 'nav.sites', icon: Cctv, end: false },
  { to: '/rules', key: 'nav.rules', icon: SlidersHorizontal, end: false },
] as const;

export function LanguageToggle({ className = '' }: { className?: string }) {
  const { t, i18n } = useTranslation();
  const next = i18n.language === 'ar' ? 'en' : 'ar';
  return (
    <button
      type="button"
      onClick={() => void i18n.changeLanguage(next)}
      className={`inline-flex h-9 items-center gap-2 rounded-lg border border-line bg-white px-3 text-sm font-medium text-ink-700 hover:bg-canvas ${className}`}
      lang={next}
      aria-label={t('settings.switchLanguage')}
    >
      <Languages className="size-4" aria-hidden />
      {next === 'ar' ? 'العربية' : 'English'}
    </button>
  );
}

function DigitsToggle() {
  const { t } = useTranslation();
  const { digits, setDigits } = usePrefs();
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-ink-500">{t('settings.digits')}</p>
      <div className="inline-flex rounded-lg border border-line bg-white p-0.5" role="group">
        {(['latn', 'arab'] as const).map((d) => (
          <button
            key={d}
            type="button"
            aria-pressed={digits === d}
            onClick={() => setDigits(d)}
            className={`rounded-md px-3 py-1 text-sm ${digits === d ? 'bg-brand-700 text-white' : 'text-ink-700 hover:bg-canvas'}`}
          >
            {d === 'latn' ? '123' : '١٢٣'}
          </button>
        ))}
      </div>
    </div>
  );
}

function UserPanel() {
  const { t } = useTranslation();
  const { session, signOut } = useAuth();
  const api = useApi();
  return (
    <div className="space-y-4">
      {api.mode === 'mock' && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900 ring-1 ring-amber-200">
          {t('settings.mockNotice')}
        </p>
      )}
      <DigitsToggle />
      <div className="flex items-center justify-between gap-2 border-t border-line pt-4">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{session?.user.name}</p>
          <p className="truncate text-xs text-ink-500">
            {session ? t(`role.${session.user.role}`) : ''}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void signOut()}
          className="inline-flex h-9 items-center gap-1.5 rounded-lg px-2 text-sm text-ink-700 hover:bg-ink-900/5"
        >
          <LogOut className="size-4 rtl:-scale-x-100" aria-hidden />
          {t('auth.signOut')}
        </button>
      </div>
    </div>
  );
}

function SideNav() {
  const { t } = useTranslation();
  return (
    <nav aria-label={t('nav.main')} className="space-y-1">
      {NAV.map(({ to, key, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) =>
            `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium ${
              isActive ? 'bg-brand-50 text-brand-800' : 'text-ink-700 hover:bg-ink-900/5'
            }`
          }
        >
          <Icon className="size-[18px]" aria-hidden />
          {t(key)}
        </NavLink>
      ))}
    </nav>
  );
}

function BottomNav() {
  const { t } = useTranslation();
  return (
    <nav
      aria-label={t('nav.main')}
      className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-line bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
    >
      {NAV.map(({ to, key, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) =>
            `flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium ${isActive ? 'text-brand-700' : 'text-ink-500'}`
          }
        >
          <Icon className="size-5" aria-hidden />
          <span className="max-w-full truncate px-1">{t(`${key}Short`)}</span>
        </NavLink>
      ))}
    </nav>
  );
}

export function AppShell({ children }: { children?: ReactNode }) {
  const { t } = useTranslation();
  const [menuOpen, setMenuOpen] = useState(false);
  return (
    <div className="min-h-dvh lg:ps-64">
      <aside className="fixed inset-y-0 start-0 z-20 hidden w-64 flex-col justify-between overflow-y-auto border-e border-line bg-white p-4 lg:flex">
        <div className="space-y-6">
          <Logo />
          <SideNav />
        </div>
        <div className="space-y-4">
          <LanguageToggle className="w-full" />
          <UserPanel />
        </div>
      </aside>

      <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-line bg-white/95 px-4 backdrop-blur lg:hidden">
        <Logo compact />
        <div className="flex items-center gap-2">
          <LanguageToggle />
          <button
            type="button"
            className="grid size-9 place-items-center rounded-lg text-ink-700 hover:bg-ink-900/5"
            aria-label={menuOpen ? t('common.close') : t('nav.menu')}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((v) => !v)}
          >
            {menuOpen ? (
              <X className="size-5" aria-hidden />
            ) : (
              <Menu className="size-5" aria-hidden />
            )}
          </button>
        </div>
        {menuOpen && (
          <div className="absolute inset-x-0 top-14 border-b border-line bg-white p-4 shadow-lg">
            <UserPanel />
          </div>
        )}
      </header>

      <main className="min-w-0 pb-24 lg:pb-10">{children ?? <Outlet />}</main>
      <BottomNav />
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
  back,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  back?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        {back}
        <h1 className="text-xl font-semibold tracking-tight text-ink-900 sm:text-2xl">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-ink-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Page({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <div
      className={`mx-auto w-full px-4 py-5 sm:px-6 lg:px-8 lg:py-8 ${wide ? 'max-w-[1400px]' : 'max-w-6xl'}`}
    >
      {children}
    </div>
  );
}
