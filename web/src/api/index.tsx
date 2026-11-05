import { createContext, useContext, type ReactNode } from 'react';
import type { ApiClient } from './client';
import { sessionStore } from './client';
import { HttpApiClient } from './http';
import { MockApiClient } from './mock/mockClient';

/**
 * Picks the implementation from configuration: VITE_API_BASE_URL set -> real backend,
 * empty -> in-memory mock with demo data.
 */
export function createApiClient(env: { VITE_API_BASE_URL?: string } = import.meta.env): ApiClient {
  const base = (env.VITE_API_BASE_URL ?? '').trim();
  if (base) {
    return new HttpApiClient({
      baseUrl: base,
      getSession: () => sessionStore.load(),
      saveSession: (s) => sessionStore.save(s),
      onUnauthorized: () => {
        sessionStore.save(null);
        window.dispatchEvent(new CustomEvent('vision:unauthorized'));
      },
    });
  }
  return new MockApiClient({ live: true });
}

const ApiContext = createContext<ApiClient | null>(null);

export function ApiProvider({ client, children }: { client: ApiClient; children: ReactNode }) {
  return <ApiContext.Provider value={client}>{children}</ApiContext.Provider>;
}

export function useApi(): ApiClient {
  const client = useContext(ApiContext);
  if (!client) throw new Error('useApi must be used inside <ApiProvider>');
  return client;
}
