import { QueryClient } from '@tanstack/react-query';
import { renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';
import { MockApiClient } from '../api/mock/mockClient';
import { Providers } from '../App';
import { createI18n } from '../i18n';
import { useEventSummary } from './EventBits';

function summary() {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <Providers
      api={new MockApiClient({ latencyMs: 0 })}
      i18n={createI18n('en')}
      queryClient={new QueryClient()}
    >
      {children}
    </Providers>
  );
  return renderHook(() => useEventSummary(), { wrapper }).result.current;
}

describe('useEventSummary', () => {
  it('takes how long a place was empty from the timestamps, not the people count', () => {
    // What the edge sends for "unattended": value = people in the zone (0).
    const text = summary()({
      rule_type: 'zone_empty',
      value: 0,
      condition_started_at: '2026-11-05T06:17:35Z',
      triggered_at: '2026-11-05T06:18:35Z',
    });
    expect(text).toBe('Empty for 1 minute');
  });

  it('uses the value for counts and for dwell time', () => {
    const s = summary();
    expect(s({ rule_type: 'queue_length_over', value: 6 })).toBe('6 people waiting');
    expect(s({ rule_type: 'dwell_over', value: 95 })).toMatch(/^Stayed 1 minute/);
  });
});
