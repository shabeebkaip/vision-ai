import { QueryClient } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MockApiClient } from '../api/mock/mockClient';
import { Providers } from '../App';
import { createI18n, type AppLang } from '../i18n';
import { EventFeedPage, FEED_POLL_MS, filtersFromParams } from './EventFeedPage';

const NOW = new Date('2026-11-02T15:00:00Z');

function renderFeed(url = '/events', lang: AppLang = 'en') {
  const api = new MockApiClient({ latencyMs: 0, now: () => NOW });
  const listEvents = vi.spyOn(api, 'listEvents');
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: '/events', element: <EventFeedPage /> },
      { path: '/events/:eventId', element: <p>detail</p> },
    ],
    { initialEntries: [url] },
  );
  render(
    <Providers api={api} i18n={createI18n(lang)} queryClient={queryClient}>
      <RouterProvider router={router} />
    </Providers>,
  );
  return { api, listEvents, router };
}

afterEach(() => {
  vi.useRealTimers();
});

describe('EventFeedPage', () => {
  it('lists the newest alerts with thumbnails, site and camera names, and a link to each', async () => {
    renderFeed();
    const list = await screen.findByRole('list', { name: 'Alerts, newest first' });
    const rows = within(list).getAllByRole('listitem');
    expect(rows).toHaveLength(20); // first page
    const times = rows.map((r) => r.querySelector('time')!.getAttribute('datetime')!);
    expect([...times].sort().reverse()).toEqual(times);
    expect(within(rows[0]!).getByRole('img')).toHaveAttribute(
      'src',
      expect.stringContaining('data:image/svg+xml'),
    );
    expect(within(rows[0]!).getByRole('link')).toHaveAttribute(
      'href',
      expect.stringMatching(/^\/events\/evt-/),
    );
    expect(screen.getAllByText(/Najd Grill House – Al Malqa ·/).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Load more' })).toBeInTheDocument();
  });

  it('applies filters from the URL', async () => {
    const { listEvents } = renderFeed('/events?type=zone_empty&severity=critical');
    const list = await screen.findByRole('list', { name: 'Alerts, newest first' });
    expect(listEvents).toHaveBeenCalledWith(
      { rule_type: 'zone_empty', severity: 'critical' },
      null,
      20,
    );
    for (const row of within(list).getAllByRole('listitem')) {
      expect(row).toHaveTextContent('Station unattended');
      expect(row).toHaveTextContent('Critical');
    }
    expect(screen.getByRole('button', { name: 'Clear filters' })).toBeInTheDocument();
  });

  it('shows an empty state when nothing matches', async () => {
    renderFeed('/events?from=2020-01-01&to=2020-01-02');
    expect(await screen.findByText('No alerts match these filters')).toBeInTheDocument();
  });

  it('polls for new alerts every 10 seconds', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { listEvents } = renderFeed();
    await screen.findByRole('list', { name: 'Alerts, newest first' });
    const before = listEvents.mock.calls.length;
    await vi.advanceTimersByTimeAsync(FEED_POLL_MS + 50);
    expect(listEvents.mock.calls.length).toBeGreaterThan(before);
  });

  it('renders right-to-left labels in Arabic', async () => {
    renderFeed('/events?type=queue_length_over', 'ar');
    const list = await screen.findByRole('list', { name: 'التنبيهات، الأحدث أولًا' });
    expect(within(list).getAllByText('طابور طويل').length).toBeGreaterThan(0);
  });
});

describe('filtersFromParams', () => {
  it('turns Riyadh local days into a UTC range and ignores unknown values', () => {
    const f = filtersFromParams(
      new URLSearchParams('from=2026-11-02&to=2026-11-02&type=bogus&verdict=none'),
    );
    expect(f).toEqual({
      from: '2026-11-01T21:00:00.000Z',
      to: '2026-11-02T21:00:00.000Z',
      verdict: 'none',
    });
  });
});
