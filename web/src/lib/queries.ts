import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useApi } from '../api';
import type { CameraView, SiteSummary } from '../api/models';

export const qk = {
  sites: ['sites'] as const,
  cameras: (siteId?: string) => ['cameras', siteId ?? 'all'] as const,
  camera: (id: string) => ['camera', id] as const,
  events: (filters: object) => ['events', filters] as const,
  event: (id: string) => ['event', id] as const,
  overview: (siteId: string, date: string) => ['overview', siteId, date] as const,
  rules: (siteId: string) => ['rules', siteId] as const,
  recipients: (siteId: string) => ['recipients', siteId] as const,
};

export function useSites() {
  const api = useApi();
  return useQuery({ queryKey: qk.sites, queryFn: () => api.listSites(), staleTime: 60_000 });
}

export function useCameras(siteId?: string) {
  const api = useApi();
  return useQuery({
    queryKey: qk.cameras(siteId),
    queryFn: () => api.listCameras(siteId),
    staleTime: 30_000,
  });
}

/** Picks the Arabic display name when the UI is in Arabic and one exists. */
export function useLocalName() {
  const { i18n } = useTranslation();
  const ar = i18n.language === 'ar';
  return (
    item: { name: string; name_ar?: string | null } | undefined | null,
    fallback = '',
  ): string => {
    if (!item) return fallback;
    return (ar && item.name_ar) || item.name || fallback;
  };
}

export function indexById<T extends { id: string }>(items: T[] | undefined): Map<string, T> {
  return new Map((items ?? []).map((i) => [i.id, i]));
}

export type { CameraView, SiteSummary };
