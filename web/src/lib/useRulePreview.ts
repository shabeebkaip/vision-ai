import { useQuery } from '@tanstack/react-query';
import { useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useApi } from '../api';
import type { CameraView, Recipient, Rule, RuleWithRecipients } from '../api/models';
import { useFormat } from './prefs';
import { qk, useCameras, useLocalName } from './queries';
import { buildRulePreview } from './rulePreview';

export function useRules(siteId: string | undefined) {
  const api = useApi();
  return useQuery({
    queryKey: qk.rules(siteId ?? ''),
    queryFn: () => api.listRules(siteId!),
    enabled: !!siteId,
    staleTime: 30_000,
  });
}

export function useRecipients(siteId: string | undefined) {
  const api = useApi();
  return useQuery({
    queryKey: qk.recipients(siteId ?? ''),
    queryFn: () => api.listRecipients(siteId!),
    enabled: !!siteId,
    staleTime: 60_000,
  });
}

/** Turns a rule into its plain-language sentence using the camera's zone/line names. */
export function usePreviewBuilder(
  cameras: CameraView[] | undefined,
  recipients: Recipient[] | undefined,
) {
  const { t } = useTranslation();
  const fmt = useFormat();
  const localName = useLocalName();
  return useCallback(
    (rule: Rule, recipientIds: string[]) => {
      const cam = cameras?.find((c) => c.id === rule.camera_id);
      const byId = new Map((recipients ?? []).map((r) => [r.id, r]));
      return buildRulePreview(
        rule,
        {
          ...fmt.opts,
          zoneName: cam?.zones.find((z) => z.id === rule.zone_id)?.name,
          lineName: cam?.lines.find((l) => l.id === rule.line_id)?.name,
          recipients: recipientIds
            .map((id) => byId.get(id))
            .filter((r): r is Recipient => !!r)
            .map((r) => ({ name: localName(r), channel: r.channel })),
        },
        t,
      );
    },
    [cameras, recipients, fmt.opts, t, localName],
  );
}

/** Everything needed to describe the rules of one site. */
export function useSiteRules(siteId: string | undefined) {
  const rules = useRules(siteId);
  const recipients = useRecipients(siteId);
  const cameras = useCameras(siteId);
  const preview = usePreviewBuilder(cameras.data, recipients.data);
  const byId = useMemo(
    () => new Map<string, RuleWithRecipients>((rules.data ?? []).map((r) => [r.rule.id, r])),
    [rules.data],
  );
  return { rules, recipients, cameras, preview, byId };
}
