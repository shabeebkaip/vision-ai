import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { Navigate, useLocation } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { sessionStore } from './api/client';
import { useApi } from './api';
import type { Session } from './api/models';

interface AuthValue {
  session: Session | null;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({
  children,
  initial,
}: {
  children: ReactNode;
  initial?: Session | null;
}) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [session, setSession] = useState<Session | null>(() =>
    initial !== undefined ? initial : sessionStore.load(),
  );

  useEffect(() => {
    const onUnauthorized = () => setSession(null);
    window.addEventListener('vision:unauthorized', onUnauthorized);
    return () => window.removeEventListener('vision:unauthorized', onUnauthorized);
  }, []);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const s = await api.login(email, password);
      sessionStore.save(s);
      setSession(s);
    },
    [api],
  );

  const signOut = useCallback(async () => {
    await api.logout();
    sessionStore.save(null);
    queryClient.clear();
    setSession(null);
  }, [api, queryClient]);

  const value = useMemo(() => ({ session, signIn, signOut }), [session, signIn, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const v = useContext(AuthContext);
  if (!v) throw new Error('useAuth must be used inside <AuthProvider>');
  return v;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { session } = useAuth();
  const location = useLocation();
  if (!session) {
    return <Navigate to="/sign-in" replace state={{ from: location.pathname + location.search }} />;
  }
  return <>{children}</>;
}
