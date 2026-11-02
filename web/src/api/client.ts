/**
 * The one typed interface every screen uses to talk to the cloud. Two implementations:
 *   - HttpApiClient: the real FastAPI backend at VITE_API_BASE_URL
 *   - MockApiClient: in-memory demo data (used when VITE_API_BASE_URL is empty)
 * Screens never call fetch directly, so switching is a configuration change only.
 */
import type {
  CameraView,
  EventFilters,
  EventView,
  GeometryUpdate,
  Page,
  Recipient,
  RuleWithRecipients,
  Session,
  SiteOverview,
  SiteSummary,
  Verdict,
} from './models';

export interface FeedbackInput {
  verdict: Verdict;
  note: string;
}

export interface ApiClient {
  readonly mode: 'http' | 'mock';
  login(email: string, password: string): Promise<Session>;
  logout(): Promise<void>;

  listSites(): Promise<SiteSummary[]>;
  getOverview(siteId: string, localDate: string): Promise<SiteOverview>;

  listCameras(siteId?: string): Promise<CameraView[]>;
  getCamera(cameraId: string): Promise<CameraView>;
  saveGeometry(cameraId: string, geometry: GeometryUpdate): Promise<CameraView>;

  listRules(siteId: string): Promise<RuleWithRecipients[]>;
  createRule(siteId: string, body: RuleWithRecipients): Promise<RuleWithRecipients>;
  listRecipients(siteId: string): Promise<Recipient[]>;

  listEvents(
    filters: EventFilters,
    cursor?: string | null,
    limit?: number,
  ): Promise<Page<EventView>>;
  getEvent(eventId: string): Promise<EventView>;
  submitFeedback(eventId: string, input: FeedbackInput): Promise<EventView>;
}

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/** Keeps the bearer token in memory and, when allowed, in localStorage across reloads. */
const TOKEN_KEY = 'vision.session';

export const sessionStore = {
  load(): Session | null {
    try {
      const raw = localStorage.getItem(TOKEN_KEY);
      return raw ? (JSON.parse(raw) as Session) : null;
    } catch {
      return null;
    }
  },
  save(session: Session | null): void {
    try {
      if (session) localStorage.setItem(TOKEN_KEY, JSON.stringify(session));
      else localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* private mode or blocked storage: the session simply lasts for this tab */
    }
  },
};
