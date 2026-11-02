import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { i18n as I18n } from 'i18next';
import { lazy, Suspense, useState, type ReactNode } from 'react';
import { I18nextProvider } from 'react-i18next';
import { createBrowserRouter, Outlet, RouterProvider, type RouteObject } from 'react-router';
import { ApiProvider } from './api';
import type { ApiClient } from './api/client';
import { AuthProvider, RequireAuth } from './auth';
import { AppShell } from './components/layout/AppShell';
import { Spinner } from './components/ui/States';
import { PrefsProvider } from './lib/prefs';
import { EventDetailPage } from './pages/EventDetailPage';
import { EventFeedPage } from './pages/EventFeedPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { RuleBuilderPage } from './pages/RuleBuilderPage';
import { RulesPage } from './pages/RulesPage';
import { SignInPage } from './pages/SignInPage';
import { SitesPage } from './pages/SitesPage';

// Heavier screens (charts, canvas) load on demand to keep the first bundle small.
const OverviewPage = lazy(() => import('./pages/OverviewPage'));
const ZoneEditorPage = lazy(() => import('./pages/ZoneEditorPage'));

function Lazy({ children }: { children: ReactNode }) {
  return <Suspense fallback={<Spinner />}>{children}</Suspense>;
}

export const routes: RouteObject[] = [
  {
    element: (
      <AuthProvider>
        <Outlet />
      </AuthProvider>
    ),
    children: [
      { path: '/sign-in', element: <SignInPage /> },
      {
        element: (
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        ),
        children: [
          {
            index: true,
            element: (
              <Lazy>
                <OverviewPage />
              </Lazy>
            ),
          },
          { path: 'events', element: <EventFeedPage /> },
          { path: 'events/:eventId', element: <EventDetailPage /> },
          { path: 'sites', element: <SitesPage /> },
          {
            path: 'cameras/:cameraId/zones',
            element: (
              <Lazy>
                <ZoneEditorPage />
              </Lazy>
            ),
          },
          { path: 'rules', element: <RulesPage /> },
          { path: 'rules/new', element: <RuleBuilderPage /> },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
];

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: 1, refetchOnWindowFocus: true, staleTime: 5_000 },
    },
  });
}

export function Providers({
  api,
  i18n,
  queryClient,
  children,
}: {
  api: ApiClient;
  i18n: I18n;
  queryClient: QueryClient;
  children: ReactNode;
}) {
  return (
    <I18nextProvider i18n={i18n}>
      <PrefsProvider>
        <ApiProvider client={api}>
          <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        </ApiProvider>
      </PrefsProvider>
    </I18nextProvider>
  );
}

const router = createBrowserRouter(routes);

export function App({ api, i18n }: { api: ApiClient; i18n: I18n }) {
  const [queryClient] = useState(makeQueryClient);
  return (
    <Providers api={api} i18n={i18n} queryClient={queryClient}>
      <RouterProvider router={router} />
    </Providers>
  );
}
