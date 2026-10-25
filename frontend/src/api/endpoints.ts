import { get, patch, post, qs, resetCsrf, request } from './client'
import type {
  AdvisorMode,
  AdvisorReport,
  BankCard,
  BankEvent,
  BankQueueItem,
  BankRevisionDetail,
  Company,
  CompanyDetail,
  Decision,
  Draft,
  DraftPatch,
  EventItem,
  ManualDecision,
  ManualInfoRequest,
  Page,
  Product,
  RetryResponse,
  Revision,
  Scenarios,
  ScenarioSet,
  ScenarioSetUpdate,
  Candidate,
  SessionResponse,
  Submission,
} from './types'

export const auth = {
  me: () => get<SessionResponse>('/api/auth/me', { silent401: true }),
  async login(email: string, password: string) {
    resetCsrf()
    const s = await post<SessionResponse>('/api/auth/login', { email, password }, { silent401: true })
    resetCsrf() // after login the server issues a session-bound CSRF token
    return s
  },
  activity: () => post<SessionResponse>('/api/auth/activity', {}, { silent401: true }),
  async logout() {
    try {
      await request<void>('POST', '/api/auth/logout', {}, { silent401: true })
    } finally {
      resetCsrf()
    }
  },
}

export const catalog = {
  companies: () => get<Page<Company>>('/api/companies?limit=100'),
  company: (id: string) => get<CompanyDetail>(`/api/companies/${id}`),
  products: () => get<Page<Product>>('/api/products?limit=100'),
}

export const applications = {
  list: (companyId?: string) => get<Page<Draft>>(`/api/applications${qs({ limit: 100, company_id: companyId })}`),
  get: (id: string) => get<Draft>(`/api/applications/${id}`),
  create: (company_id: string, product_id: string) => post<Draft>('/api/applications', { company_id, product_id }),
  patch: (id: string, body: DraftPatch) => patch<Draft>(`/api/applications/${id}`, body),
  /** Deletes a never-submitted draft (the backend archives it). */
  remove: (id: string, expected_version: number) => request<void>('DELETE', `/api/applications/${id}`, { expected_version }),
  events: (id: string) => get<{ items: EventItem[] }>(`/api/applications/${id}/events`),
  submit: (id: string, expected_version: number, submission_key: string) =>
    post<Submission>(`/api/applications/${id}/submit`, { expected_version, submission_key }),
  revision: (id: string, no: number) => get<Revision>(`/api/applications/${id}/revisions/${no}`),
  decision: (id: string) => get<Decision>(`/api/applications/${id}/decision`),
  scenarios: (id: string, expected_version: number) => post<Scenarios>(`/api/applications/${id}/scenarios`, { expected_version }),
  scenarioSet: (id: string) => get<ScenarioSet | null>(`/api/applications/${id}/scenario-set`),
  createScenarioSet: (id: string, expected_version: number, refresh = false) =>
    post<ScenarioSetUpdate>(`/api/applications/${id}/scenario-set`, { expected_version, refresh }),
  selectScenario: (id: string, expected_version: number, scenario_set_id: string, candidate_id: Candidate['candidate_id']) =>
    post<ScenarioSetUpdate>(`/api/applications/${id}/scenario-set/select`, { expected_version, scenario_set_id, candidate_id }),
  advisor: (id: string, expected_version: number, mode: AdvisorMode) =>
    post<AdvisorReport>(`/api/applications/${id}/advisor`, { expected_version, mode }),
  lastAdvisor: (id: string) => get<AdvisorReport>(`/api/applications/${id}/advisor`),
}

export const bank = {
  queue: (status?: string[], companyId?: string, limit = 100, offset = 0) =>
    get<Page<BankQueueItem>>(`/api/bank/applications${qs({ status, company_id: companyId, limit, offset })}`),
  card: (id: string) => get<BankCard>(`/api/bank/applications/${id}`),
  revision: (id: string, no: number) => get<BankRevisionDetail>(`/api/bank/applications/${id}/revisions/${no}`),
  events: (id: string) => get<{ items: BankEvent[] }>(`/api/bank/applications/${id}/events`),
  requestInfo: (id: string, body: ManualInfoRequest) => post<BankCard>(`/api/bank/applications/${id}/request-info`, body),
  decide: (id: string, body: ManualDecision) => post<BankCard>(`/api/bank/applications/${id}/decision`, body),
  retry: (id: string, expected_version: number) =>
    post<RetryResponse>(`/api/bank/applications/${id}/retry-processing`, { expected_version }),
  advisor: (id: string) => get<AdvisorReport>(`/api/bank/applications/${id}/advisor`),
}
