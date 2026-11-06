/**
 * OmniDoc API client and shared response types.
 *
 * In development Vite proxies /api to the FastAPI server (see vite.config.ts),
 * so the default base is same-origin. Set VITE_API_BASE to point elsewhere.
 */
import { createPasskey, signWithPasskey } from './lib/webauthn';
import { solvePow } from './lib/pow';
import type { PowChallenge } from './lib/pow';

export interface User {
  id: string;
  /** Empty for accounts made with a passkey until they link GitHub or Google */
  email: string;
  name: string;
  provider: string;
  avatar_url?: string;
  kind?: 'user' | 'guest';
  totp_enabled?: boolean;
  /** An administrator of this server (always true on a local install). */
  admin?: boolean;
}

export interface AuthMethods {
  /** false: a local single-user install (no sign-in) */
  accounts: boolean;
  email: boolean;
  google: boolean;
  github: boolean;
  passkey?: boolean;
  /** "Try it without signing in": a read-only guest session on the sample library */
  demo?: boolean;
}

export interface AccountInfo {
  user: User;
  accounts: boolean;
  admin: boolean;
  guest?: boolean;
  usage: { questions: number; uploads: number };
  storage_bytes: number;
  limits: { questions_per_day: number; uploads_per_day: number; storage_mb: number } | null;
  security?: { passkeys: number; totp: boolean; recovery_codes_left: number; email: string };
  /** Free answers on the server's keys (null: no trial applies, e.g. an administrator) */
  trial?: { limit: number; used: number } | null;
  /** Providers with a key kept on the server, and the providers whose own key answered this request */
  own_keys?: { server: string[]; in_use: string[] };
}

export interface KeyProvider {
  name: string;
  label: string;
  sign_up: string;
  free_note: string;
  model: string;
}

export interface ServerKey {
  provider: string;
  last4: string;
  added_at: number;
}

export interface Passkey {
  id: string;
  label: string;
  created_at: number;
  last_used_at: number | null;
}

export interface DeviceSession {
  id: string;
  device: string;
  ip: string;
  created_at: string;
  last_used_at: number | null;
  current: boolean;
}

export interface Notice {
  id: number;
  kind: 'security' | 'release' | string;
  title: string;
  body?: string;
  url?: string | null;
  created_at: number;
  read: boolean;
}

export interface TotpSetup {
  challenge_id: string;
  secret: string;
  uri: string;
  qr_svg: string;
}

/** Sign-in either finishes (a user) or, for an account with an authenticator app, asks for a code. */
export type SignInResult = { user: User; recoveryCodes?: string[] } | { mfa: string };

export interface ChatSession {
  id: string;
  title: string;
  document_id?: string | null;
  created_at: string;
  updated_at: string;
  message_count?: number;
  last_message?: string;
}

/** One numbered piece of evidence. Answers cite it inline as [n]. */
export interface Source {
  n: number;
  kind: 'chunk' | 'graph' | 'table' | 'summary' | 'math' | 'visual' | 'web' | 'conflict' | string;
  doc_id: string;
  doc_title?: string;
  chunk_id?: string;
  page?: number | null;
  section?: string;
  title?: string;
  snippet: string;
  score?: number | null;
  /** Web results */
  url?: string;
  site?: string;
  published?: string;
  /** Table results: the SQL table the figures were computed from */
  table?: string;
}

/** A SQL query the table agent ran over a table extracted from a document. */
export interface TableResult {
  table: string;
  table_id?: string;
  title: string;
  doc_id: string;
  page?: number | null;
  question?: string;
  /** The part of the question the query answers; "all rows" for a small table given whole */
  purpose?: string;
  sql: string;
  columns: string[];
  rows: Array<Array<string | number | null>>;
  row_count: number;
  truncated?: boolean;
}

export interface MathResult {
  task: string;
  formula?: string;
  exact_result?: number | string | null;
  units?: string | null;
  inputs?: Record<string, unknown>;
  assumptions?: string[];
  code_executed?: string;
}

export interface ChartTrace {
  type?: string;
  name?: string;
  x?: Array<string | number>;
  y?: Array<number | string>;
  labels?: Array<string | number>;
  values?: Array<number | string>;
}

export interface ChartArtifact {
  chart_type: 'bar' | 'line' | 'scatter' | 'pie' | string;
  title: string;
  caption?: string;
  plotly_spec?: {
    data?: ChartTrace[];
    layout?: { xaxis?: { title?: unknown }; yaxis?: { title?: unknown }; title?: unknown };
  };
  underlying_data?: Array<Record<string, unknown>>;
  source_ns?: number[];
}

export interface ConflictItem {
  conflicting_claim: string;
  resolution_status?: string;
  rationale?: string;
  confidence?: number;
  evidence_a?: { content?: string; source_id?: string; provenance?: Record<string, unknown> };
  evidence_b?: { content?: string; source_id?: string; provenance?: Record<string, unknown> };
}

export interface AgentStep {
  node: string;
  label: string;
  detail?: string;
  duration_ms?: number;
}

export type SentenceVerdict = 'supported' | 'partial' | 'unsupported' | 'contradicted' | 'no_claim' | 'unchecked';

/** One sentence of the answer checked against the passages it cites. */
export interface SentenceCheck {
  id: string;
  text: string;
  start: number;
  end: number;
  citations: number[];
  verdict: SentenceVerdict;
  supported_by: number[];
  reason?: string;
  /** Set when the citation was wrong and has been corrected in the answer */
  corrected_to?: number[] | null;
}

export interface Verification {
  status: 'verified' | 'partial' | 'unverified';
  score: number | null;
  supported: number;
  unsupported: number;
  feedback?: string;
  partial?: number;
  corrected?: number;
  sentences?: SentenceCheck[];
}

export interface GraphNode {
  id: string;
  name: string;
  category: string;
  description: string;
  doc_id?: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  source_name?: string;
  target_name?: string;
  relation: string;
  description?: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  documents?: Array<{ id: string; title: string }>;
}

/** Model calls made for one answer (the execution budget's count). */
export interface Usage {
  calls?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  models?: Record<string, number>;
  elapsed_s?: number;
}

export interface AnswerPayload {
  answer: string;
  sources: Source[];
  math_results: MathResult[];
  table_results?: TableResult[];
  visual_artifacts: ChartArtifact[];
  conflicts: ConflictItem[];
  graph: GraphData;
  steps: AgentStep[];
  verification: Verification;
  model?: string;
  elapsed_ms?: number;
  document_ids?: string[];
  usage?: Usage;
}

export interface QueryResponse extends AnswerPayload {
  status: string;
  message_id: number;
}

/** Message metadata is stored as returned by the server; older rows use legacy keys. */
export type ChatMetadata = Partial<AnswerPayload> & Record<string, unknown>;

export interface ChatMessage {
  id?: number;
  chat_id?: string;
  role: 'user' | 'assistant';
  content: string;
  metadata?: ChatMetadata | null;
  timestamp?: string;
  /** Client-only: set while the answer is streaming or after a failure. */
  pending?: boolean;
  error?: string;
}

export interface DocumentItem {
  id: string;
  filename: string;
  upload_date: string;
  size_bytes: number;
  file_type: string;
  chunk_count?: number | null;
  /** Background work after upload: the summary, then knowledge-graph extraction (null once the server restarts). */
  graph_status?: {
    status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled';
    stage?: 'summary' | 'extract' | 'graph';
    processed: number;
    total: number;
    entities?: number;
  } | null;
  pages?: number | null;
  /** Pages read with OCR (scans and images) */
  ocr_pages?: number;
  ocr_languages?: string[];
  table_count?: number;
  has_summary?: boolean;
  /** How the viewer shows the document: page images (PDFs, images) or text */
  viewer?: 'pages' | 'text';
  /** Detected at upload: invoice, contract, resume, research_paper, ... */
  doc_type?: string | null;
  doc_type_label?: string | null;
  /** Fields extracted for the type, and failed consistency checks */
  record?: { found: number; total: number; failed_checks: number; template?: string } | null;
}

export interface ValidationCheck {
  rule: string;
  status: 'ok' | 'fail' | 'skip';
  message: string;
  fields: string[];
}

export interface DocumentRecord {
  doc_type: string;
  label: string;
  confidence?: number | null;
  pending: boolean;
  record: {
    template: string;
    fields: ExtractFieldResult[];
    sources: Source[];
    validation: ValidationCheck[];
    extracted_at: number;
  } | null;
}

export interface SensitiveFinding {
  type: string;
  label: string;
  masked: string;
  page: number;
  rects: Array<[number, number, number, number]>;
  context: string;
  chunk_id?: string | null;
}

export interface CompareSide {
  text: string;
  page: number;
  chunk_id: string;
}

export interface CompareChange {
  id: string;
  kind: 'modified' | 'added' | 'removed';
  a: CompareSide | null;
  b: CompareSide | null;
  similarity?: number;
  /** Word-level diff: "=" same, "-" only in A, "+" only in B */
  diff?: Array<['=' | '-' | '+', string]>;
  figures?: Array<{ from: number; to: number }>;
}

export interface CompareResult {
  a: { id: string; title: string };
  b: { id: string; title: string };
  changes: CompareChange[];
  stats: { unchanged: number; modified: number; added: number; removed: number; figures: number; similarity: number };
  summary?: string;
  summary_error?: string;
}

export interface WebPage {
  url: string;
  final_url: string;
  title: string;
  site: string;
  published?: string;
  paragraphs: string[];
  highlight: { paragraph: number | null; quote: string };
}

export interface ProviderStatus {
  name: string;
  label: string;
  configured: boolean;
  model: string;
  fast_model: string;
  key_env: string;
  cooling_down_s: number;
  free_note: string;
  sign_up: string;
}

export interface ProvidersInfo {
  llm: ProviderStatus[];
  search: Array<{ name: string; label: string; configured: boolean; key_env: string }>;
  embedding_model: string | null;
  ollama: boolean;
  current_model: string;
}

export interface UploadResult {
  doc_id: string;
  filename: string;
  chunk_count: number;
  duplicate?: boolean;
  ocr_pages?: number;
  table_count?: number;
  warning?: string;
}

export interface DocumentInfo {
  id: string;
  filename: string;
  file_type: string;
  size_bytes?: number;
  viewer: 'pages' | 'text';
  pages: Array<{ w: number; h: number; ocr: boolean; lang?: string | null }>;
  ocr_pages: number[];
  ocr_languages: string[];
  tables: Array<{ table: string; title: string; page?: number | null; n_rows: number; columns: string[] }>;
  has_summary: boolean;
  /** Recordings: transcript segments and where each passage starts (seconds) */
  media?: {
    kind: 'audio' | 'video';
    language?: string | null;
    duration?: number | null;
    engine?: string;
    segments: Array<{ start: number; end: number; text: string }>;
    chunk_starts?: Record<string, number | null>;
  } | null;
  attachments?: string[];
}

/** Where a citation sits: rectangles as fractions of the page, or the passage to mark in text. */
export interface LocateResult {
  page: number | null;
  rects: Array<[number, number, number, number]>;
  quote: string;
  method: 'sentence' | 'passage' | 'table' | 'page' | 'text';
  chunk_id?: string;
}

export interface DocumentText {
  doc_id: string;
  title: string;
  chunks: Array<{ chunk_id: string; page: number; section?: string; text: string }>;
}

export interface TableData {
  table: string;
  title: string;
  page?: number | null;
  n_rows: number;
  columns: string[];
  rows: Array<Array<string | number | null>>;
  truncated: boolean;
}

export interface DocumentSummary {
  doc_id: string;
  title: string;
  summary: string;
  key_points: Array<{ text: string; sections: number[] }>;
  topics: string[];
  sections: Array<{ i: number; title: string; pages: [number, number]; chunk_ids: string[]; summary: string }>;
}

export type FieldType = 'text' | 'number' | 'date' | 'list' | 'boolean';

export interface ExtractField {
  name: string;
  label: string;
  description: string;
  type: FieldType;
}

export interface ExtractPreset {
  key: string;
  label: string;
  description: string;
  fields: ExtractField[];
}

export interface ExtractFieldResult extends ExtractField {
  value: string | number | boolean | string[] | null;
  quote: string | null;
  /** The [n] of the passage the value was found in */
  source: number | null;
  /** found: the quote is in the passage and contains the value; check: one of those failed */
  status: 'found' | 'check' | 'missing';
  page: number | null;
  chunk_id: string | null;
  note: string;
}

export interface ExtractResult {
  doc_id: string;
  title: string;
  fields: ExtractFieldResult[];
  sources: Source[];
  elapsed_ms: number;
}

export interface ExtractHandlers {
  onDocStart?: (d: { doc_id: string; title: string; index: number; total: number }) => void;
  onProgress?: (p: { doc_id: string; done: number; total: number }) => void;
  onResult?: (r: ExtractResult) => void;
  onDocError?: (e: { doc_id: string; title: string; message: string }) => void;
  signal?: AbortSignal;
}

export interface ModelInfo {
  name: string;
  label?: string;
  provider?: string;
  provider_label?: string;
  hosted?: boolean;
  tier?: 'smart' | 'fast';
  size_gb?: number | null;
  parameter_size?: string | null;
}

export type WebMode = 'auto' | 'on' | 'off';

/** A passage found by the library search (no model call). */
export interface SearchHit {
  doc_id: string;
  title: string;
  chunk_id: string;
  page: number | null;
  section?: string | null;
  score: number;
  text: string;
}

export interface LibraryTable {
  doc_id: string;
  document: string;
  table: string;
  table_id: string;
  title: string;
  page: number | null;
  n_rows: number;
  columns: string[];
}

export interface LibraryRecord {
  doc_id: string;
  document: string;
  doc_type: string;
  label: string;
  fields: Array<{ name: string; label: string; type?: string; value: unknown; status: string; page?: number | null; chunk_id?: string | null; quote?: string | null }>;
  /** Consistency checks of the record ("Subtotal + tax = total"): pass, fail, or skip when fields are missing. */
  checks: Array<{ rule: string; status: 'pass' | 'fail' | 'skip' | string; message?: string; fields?: string[] }>;
  extracted: boolean;
}

export interface TimelineEvent {
  date: string;
  written: string;
  text: string;
  chunk_id: string;
  doc_id: string;
  document: string;
  page: number | null;
}

export interface AdminOverview {
  health: {
    status: string; version: string; model: string; ollama: boolean; providers: string[];
    stores: Record<string, string>; memory_mb: number; memory_limit_mb: number | null;
  };
  stats: {
    accounts: number; guests: number; documents: number; chats: number; questions_today: number; questions_7d: number;
    questions_30d: number; uploads_30d: number; active_30d: number; by_day: Array<{ day: string; questions: number; uploads: number }>;
  };
  admins: Array<{ id: string; name: string; email: string | null }>;
  admin_emails: string[];
  settings: { accounts: boolean; demo: boolean; trial_answers: number; default_model: string; version: string };
}
/** How much evidence an answer reads: fewer passages and sooner, or more passages and later. */
export type Effort = 'quick' | 'balanced' | 'thorough';

export interface StreamHandlers {
  onStep?: (step: AgentStep) => void;
  /** The numbered sources, sent before the answer is written */
  onSources?: (sources: Source[]) => void;
  /** A piece of the answer as it is written */
  onDelta?: (text: string) => void;
  /** The draft so far is replaced (a revision, or another model took over) */
  onReset?: (sources: Source[]) => void;
  signal?: AbortSignal;
}

export interface Health {
  status: string;
  version: string;
  model: string;
  ollama: boolean;
  stores: Record<string, string>;
}

const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';
const TOKEN_KEY = 'omnidoc_token';
/** The user's own model keys, kept only in this browser and sent with each request (never stored by the server). */
const OWN_KEYS = 'omnidoc_own_keys';

function readOwnKeys(): Record<string, string> {
  try {
    const parsed = JSON.parse(localStorage.getItem(OWN_KEYS) || '{}');
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function encodeKeys(keys: Record<string, string>): string {
  const bytes = new TextEncoder().encode(JSON.stringify(keys));
  let bin = '';
  bytes.forEach((b) => (bin += String.fromCharCode(b)));
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/** Reads a Server-Sent Events body, calling onEvent for each complete event. */
async function readEvents(res: Response, onEvent: (event: string, data: unknown) => void): Promise<void> {
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const handle = (raw: string) => {
    let event = 'message';
    const dataLines: string[] = [];
    for (const line of raw.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
    }
    if (dataLines.length) onEvent(event, JSON.parse(dataLines.join('\n')));
  };
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
    let sep: number;
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const chunk = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      if (chunk.trim()) handle(chunk);
    }
  }
  if (buffer.trim()) handle(buffer);
}

async function readError(res: Response, fallback: string): Promise<ApiError> {
  let message = fallback;
  try {
    const body = await res.json();
    if (typeof body?.detail === 'string') message = body.detail;
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(message, res.status);
}

class OmniDocApiClient {
  private token: string | null = null;

  constructor() {
    try {
      this.token = localStorage.getItem(TOKEN_KEY);
    } catch {
      this.token = null;
    }
  }

  setToken(token: string | null) {
    this.token = token;
    try {
      if (token) localStorage.setItem(TOKEN_KEY, token);
      else localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* storage unavailable */
    }
  }

  private headers(json = true): HeadersInit {
    const h: Record<string, string> = {};
    if (json) h['Content-Type'] = 'application/json';
    // Not Authorization: a deployment's password gate (HTTP basic auth) uses that header.
    if (this.token) h['X-OmniDoc-Token'] = this.token;
    const keys = readOwnKeys();
    if (Object.keys(keys).length) h['X-OmniDoc-Keys'] = encodeKeys(keys);
    return h;
  }

  /** The error for a failed response; a 401 ends the session, a 402 asks for the user's own key. */
  private async failed(res: Response, fallback: string): Promise<ApiError> {
    if (res.status === 401 && this.token && this.onUnauthorized) {
      this.setToken(null);
      this.onUnauthorized();
    }
    const err = await readError(res, fallback);
    if (res.status === 402) this.onKeyRequired?.(err.message);
    return err;
  }

  private async request<T>(path: string, init: RequestInit = {}, fallback = 'Request failed'): Promise<T> {
    let res: Response;
    try {
      res = await fetch(`${API_BASE}${path}`, {
        ...init,
        headers: { ...this.headers(!(init.body instanceof FormData)), ...(init.headers || {}) },
      });
    } catch {
      throw new ApiError('Cannot reach the OmniDoc server. Is it running on port 8000?', 0);
    }
    if (!res.ok) throw await this.failed(res, fallback);
    return res.json() as Promise<T>;
  }

  // ---- Accounts (hosted servers) --------------------------------------------
  /** Called when the server answers 401 (the session ended): the app shows the sign-in page. */
  onUnauthorized: (() => void) | null = null;
  /** Called when the server answers 402: the free answers are used up and the user's own key is needed. */
  onKeyRequired: ((message: string) => void) | null = null;

  async authMethods(): Promise<AuthMethods> {
    try {
      return await this.request<AuthMethods>('/api/auth/methods');
    } catch {
      return { accounts: false, email: false, google: false, github: false };
    }
  }

  async requestCode(email: string): Promise<void> {
    await this.request('/api/auth/code/request', { method: 'POST', body: JSON.stringify({ email }) }, 'Could not send the code');
  }

  async verifyCode(email: string, code: string, name?: string): Promise<SignInResult> {
    const data = await this.request<{ user?: User; token?: string; mfa?: string }>(
      '/api/auth/code/verify',
      { method: 'POST', body: JSON.stringify({ email, code, name }) },
      'Could not verify the code',
    );
    return this.finish(data);
  }

  private finish(data: { user?: User; token?: string; mfa?: string; recovery_codes?: string[] }): SignInResult {
    if (data.mfa) return { mfa: data.mfa };
    this.setToken(data.token ?? null);
    return { user: data.user as User, recoveryCodes: data.recovery_codes };
  }

  /** Solves the server's proof-of-work check (sign-up, the demo, recovery codes). */
  private async proof() {
    const challenge = await this.request<PowChallenge>('/api/auth/challenge', {}, 'Could not start the browser check');
    return solvePow(challenge);
  }

  /** Creates an account with a passkey (no e-mail); returns the user and their recovery codes. */
  async signUpWithPasskey(name: string): Promise<SignInResult> {
    const pow = await this.proof();
    const start = await this.request<{ challenge_id: string; options: Record<string, unknown> }>(
      '/api/auth/passkey/signup/options', { method: 'POST', body: JSON.stringify({ name, pow }) }, 'Could not start sign-up');
    const credential = await createPasskey(start.options);
    const data = await this.request<{ user: User; token: string; recovery_codes: string[] }>(
      '/api/auth/passkey/signup/verify',
      { method: 'POST', body: JSON.stringify({ challenge_id: start.challenge_id, credential }) },
      'Could not create the account',
    );
    return this.finish(data);
  }

  async signInWithPasskey(): Promise<SignInResult> {
    const start = await this.request<{ challenge_id: string; options: Record<string, unknown> }>(
      '/api/auth/passkey/signin/options', { method: 'POST' }, 'Could not start sign-in');
    const credential = await signWithPasskey(start.options);
    const data = await this.request<{ user: User; token: string }>(
      '/api/auth/passkey/signin/verify',
      { method: 'POST', body: JSON.stringify({ challenge_id: start.challenge_id, credential }) },
      'Could not sign in',
    );
    return this.finish(data);
  }

  async signInWithRecoveryCode(code: string): Promise<SignInResult> {
    const pow = await this.proof();
    const data = await this.request<{ user: User; token: string }>(
      '/api/auth/recovery', { method: 'POST', body: JSON.stringify({ code, pow }) }, 'Could not sign in');
    return this.finish(data);
  }

  /** The second step: a code from the authenticator app, or a recovery code. */
  async finishTwoStep(ticket: string, code: string): Promise<SignInResult> {
    const data = await this.request<{ user: User; token: string }>(
      '/api/auth/mfa', { method: 'POST', body: JSON.stringify({ ticket, code }) }, 'Could not verify the code');
    return this.finish(data);
  }

  async startGuest(): Promise<SignInResult> {
    const pow = await this.proof();
    const data = await this.request<{ user: User; token: string }>(
      '/api/auth/guest', { method: 'POST', body: JSON.stringify({ pow }) }, 'Could not open the demo');
    return this.finish(data);
  }

  /** Google and GitHub sign-in leave the app and come back with the session in the address fragment. */
  oauthUrl(provider: 'google' | 'github'): string {
    return `${API_BASE}/api/auth/oauth/${provider}/start`;
  }

  /**
   * Takes what Google or GitHub sign-in handed back in the address (a session, a two-step ticket,
   * a linked account or an error) and clears it from the address bar.
   */
  takeRedirect(): { error?: string; mfa?: string; linked?: string } {
    const hash = window.location.hash;
    const match = /^#(auth|auth_error|mfa|linked)=(.*)$/.exec(hash);
    if (!match) return {};
    const value = decodeURIComponent(match[2]);
    window.history.replaceState(null, '', window.location.pathname + window.location.search);
    if (match[1] === 'auth') {
      this.setToken(value);
      return {};
    }
    if (match[1] === 'mfa') return { mfa: value };
    if (match[1] === 'linked') return { linked: value };
    return { error: value };
  }

  getAccount(): Promise<AccountInfo> {
    return this.request<AccountInfo>('/api/account');
  }

  // ---- Account security -----------------------------------------------------
  async listPasskeys(): Promise<Passkey[]> {
    return (await this.request<{ passkeys: Passkey[] }>('/api/account/passkeys')).passkeys;
  }

  /** Adds a passkey on this device; returns the list and, if the account had none left, new recovery codes. */
  async addPasskey(): Promise<{ passkeys: Passkey[]; recovery_codes: string[] | null }> {
    const start = await this.request<{ challenge_id: string; options: Record<string, unknown> }>(
      '/api/account/passkeys/options', { method: 'POST' }, 'Could not start adding a passkey');
    const credential = await createPasskey(start.options);
    return this.request('/api/account/passkeys/verify',
      { method: 'POST', body: JSON.stringify({ challenge_id: start.challenge_id, credential }) }, 'Could not add the passkey');
  }

  async removePasskey(id: string): Promise<Passkey[]> {
    const data = await this.request<{ passkeys: Passkey[] }>(
      `/api/account/passkeys/${encodeURIComponent(id)}`, { method: 'DELETE' }, 'Could not remove the passkey');
    return data.passkeys;
  }

  totpSetup(): Promise<TotpSetup> {
    return this.request<TotpSetup>('/api/account/totp/setup', { method: 'POST' }, 'Could not start the setup');
  }

  totpEnable(challengeId: string, code: string): Promise<{ recovery_codes: string[] | null }> {
    return this.request('/api/account/totp/enable',
      { method: 'POST', body: JSON.stringify({ challenge_id: challengeId, code }) }, 'Could not turn on two-step sign-in');
  }

  async totpDisable(code: string): Promise<void> {
    await this.request('/api/account/totp/disable', { method: 'POST', body: JSON.stringify({ code }) }, 'Could not turn it off');
  }

  async newRecoveryCodes(): Promise<string[]> {
    return (await this.request<{ recovery_codes: string[] }>('/api/account/recovery-codes', { method: 'POST' },
      'Could not make new codes')).recovery_codes;
  }

  async listSessions(): Promise<DeviceSession[]> {
    return (await this.request<{ sessions: DeviceSession[] }>('/api/account/sessions')).sessions;
  }

  async endSession(id: string): Promise<void> {
    await this.request(`/api/account/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }, 'Could not sign that device out');
  }

  async endOtherSessions(): Promise<number> {
    return (await this.request<{ signed_out: number }>('/api/account/sessions/sign-out-others', { method: 'POST' },
      'Could not sign the other devices out')).signed_out;
  }

  /** The consent page that adds GitHub or Google as another way into this account. */
  async linkUrl(provider: 'google' | 'github'): Promise<string> {
    return (await this.request<{ url: string }>(`/api/account/link/${provider}`, { method: 'POST' }, 'Could not start linking')).url;
  }

  /** Downloads everything the account holds as a zip. */
  async exportAccount(): Promise<void> {
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/api/account/export`, { headers: this.headers(false) });
    } catch {
      throw new ApiError('Cannot reach the OmniDoc server.', 0);
    }
    if (!res.ok) throw await this.failed(res, 'Could not export your data');
    const blob = await res.blob();
    const name = /filename="([^"]+)"/.exec(res.headers.get('content-disposition') || '')?.[1] || 'omnidoc-export.zip';
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
  }

  // ---- Bring your own key ----------------------------------------------------
  async keyProviders(): Promise<{ providers: KeyProvider[]; trial_answers: number }> {
    return this.request('/api/keys/providers', {}, 'Could not load the providers');
  }

  /** Tries a key with one tiny request to its provider; nothing is stored. */
  checkKey(provider: string, key: string): Promise<{ ok: boolean; reason: string }> {
    return this.request('/api/keys/check', { method: 'POST', body: JSON.stringify({ provider, key }) }, 'Could not check the key');
  }

  /** Keys kept in this browser only: provider to last four characters. */
  deviceKeys(): Record<string, string> {
    return Object.fromEntries(Object.entries(readOwnKeys()).map(([p, k]) => [p, k.slice(-4)]));
  }

  setDeviceKey(provider: string, key: string | null): void {
    const keys = readOwnKeys();
    if (key) keys[provider] = key;
    else delete keys[provider];
    try {
      if (Object.keys(keys).length) localStorage.setItem(OWN_KEYS, JSON.stringify(keys));
      else localStorage.removeItem(OWN_KEYS);
    } catch {
      throw new ApiError('This browser does not allow saving the key. Keep it on the server instead.', 0);
    }
  }

  async serverKeys(): Promise<ServerKey[]> {
    return (await this.request<{ keys: ServerKey[] }>('/api/account/keys')).keys;
  }

  async saveServerKey(provider: string, key: string): Promise<ServerKey[]> {
    return (await this.request<{ keys: ServerKey[] }>(`/api/account/keys/${encodeURIComponent(provider)}`,
      { method: 'PUT', body: JSON.stringify({ key }) }, 'Could not save the key')).keys;
  }

  async deleteServerKey(provider: string): Promise<ServerKey[]> {
    return (await this.request<{ keys: ServerKey[] }>(`/api/account/keys/${encodeURIComponent(provider)}`,
      { method: 'DELETE' }, 'Could not remove the key')).keys;
  }

  // ---- Notices (security events, What's new) --------------------------------
  listNotices(): Promise<{ notices: Notice[]; unread: number }> {
    return this.request('/api/notices');
  }

  async readNotices(ids?: number[]): Promise<void> {
    await this.request('/api/notices/read', { method: 'POST', body: JSON.stringify({ ids: ids ?? null }) });
  }

  async deleteAccount(): Promise<void> {
    await this.request('/api/account', { method: 'DELETE' }, 'Could not delete the account');
    this.setToken(null);
  }

  // ---- Profile -------------------------------------------------------------
  async login(name: string, email: string): Promise<User> {
    const data = await this.request<{ user: User; token: string }>(
      '/api/auth/login',
      { method: 'POST', body: JSON.stringify({ provider: 'local', name, email }) },
      'Could not sign in',
    );
    this.setToken(data.token);
    return data.user;
  }

  async getMe(): Promise<User | null> {
    if (!this.token) return null;
    try {
      const data = await this.request<{ user: User }>('/api/auth/me');
      return data.user;
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) this.setToken(null);
      return null;
    }
  }

  async logout(): Promise<void> {
    try {
      await this.request('/api/auth/logout', { method: 'POST' });
    } finally {
      this.setToken(null);
    }
  }

  // ---- System --------------------------------------------------------------
  health(): Promise<Health> {
    return this.request<Health>('/api/health');
  }

  async getModels(): Promise<{ models: ModelInfo[]; current: string; can_set_default?: boolean }> {
    return this.request('/api/models');
  }

  async setModel(model: string): Promise<{ current: string }> {
    return this.request('/api/models/current', { method: 'PUT', body: JSON.stringify({ model }) }, 'Could not switch model');
  }

  // ---- Chats ---------------------------------------------------------------
  async getChats(): Promise<ChatSession[]> {
    const data = await this.request<{ chats: ChatSession[] }>('/api/chats', {}, 'Could not load conversations');
    return data.chats;
  }

  async createChat(title?: string): Promise<ChatSession> {
    const data = await this.request<{ chat: ChatSession }>(
      '/api/chats',
      { method: 'POST', body: JSON.stringify({ title }) },
      'Could not start a conversation',
    );
    return data.chat;
  }

  getChat(chatId: string): Promise<{ chat: ChatSession; messages: ChatMessage[] }> {
    return this.request(`/api/chats/${encodeURIComponent(chatId)}`, {}, 'Could not load the conversation');
  }

  async renameChat(chatId: string, title: string): Promise<void> {
    await this.request(`/api/chats/${encodeURIComponent(chatId)}`, { method: 'PATCH', body: JSON.stringify({ title }) });
  }

  async deleteChat(chatId: string): Promise<void> {
    await this.request(`/api/chats/${encodeURIComponent(chatId)}`, { method: 'DELETE' });
  }

  /**
   * Runs the agent pipeline and streams progress. `onStep` fires once per finished
   * pipeline stage; the promise resolves with the final answer.
   */
  async streamQuery(
    chatId: string,
    body: { query: string; document_ids?: string[]; language?: string; web?: WebMode; effort?: Effort; model?: string },
    handlers: StreamHandlers = {},
  ): Promise<QueryResponse> {
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/api/chats/${encodeURIComponent(chatId)}/query/stream`, {
        method: 'POST',
        headers: { ...this.headers(), Accept: 'text/event-stream' },
        body: JSON.stringify(body),
        signal: handlers.signal,
      });
    } catch (err) {
      if ((err as Error).name === 'AbortError') throw err;
      throw new ApiError('Cannot reach the OmniDoc server. Is it running on port 8000?', 0);
    }
    if (!res.ok || !res.body) throw await this.failed(res, 'The query failed');

    let result: QueryResponse | null = null;
    await readEvents(res, (event, data) => {
      if (event === 'step') handlers.onStep?.(data as AgentStep);
      else if (event === 'sources') handlers.onSources?.(data as Source[]);
      else if (event === 'delta') handlers.onDelta?.((data as { text: string }).text);
      else if (event === 'reset') handlers.onReset?.(data as Source[]);
      else if (event === 'result') result = data as QueryResponse;
      else if (event === 'error') throw new ApiError((data as { message?: string })?.message || 'The query failed', 500);
    });
    if (!result) throw new ApiError('The server closed the stream before answering', 500);
    return result;
  }

  // ---- Documents -----------------------------------------------------------
  async getDocuments(): Promise<DocumentItem[]> {
    const data = await this.request<{ documents: DocumentItem[] }>('/api/documents', {}, 'Could not load the library');
    return data.documents;
  }

  importUrl(url: string): Promise<UploadResult & { url?: string }> {
    return this.request('/api/documents/import-url', { method: 'POST', body: JSON.stringify({ url }) }, 'Import failed');
  }

  uploadDocument(file: File): Promise<UploadResult> {
    const form = new FormData();
    form.append('file', file);
    return this.request<UploadResult>('/api/documents/upload', { method: 'POST', body: form }, 'Upload failed');
  }

  async deleteDocument(docId: string): Promise<void> {
    await this.request(`/api/documents/${encodeURIComponent(docId)}`, { method: 'DELETE' }, 'Could not delete the document');
  }

  /** Queues background summaries for documents (all by default) that have none. Returns the ids queued. */
  async summarizeMissing(docIds?: string[]): Promise<string[]> {
    const data = await this.request<{ queued: string[] }>(
      '/api/documents/summaries',
      { method: 'POST', body: JSON.stringify({ document_ids: docIds ?? null }) },
      'Could not start the summaries',
    );
    return data.queued;
  }

  // ---- Document viewer -----------------------------------------------------
  getDocumentInfo(docId: string): Promise<DocumentInfo> {
    return this.request(`/api/documents/${encodeURIComponent(docId)}/info`, {}, 'Could not open the document');
  }

  /** The original file (PDFs open at a page in the browser's viewer). */
  documentFileUrl(docId: string, page?: number | null): string {
    return `${API_BASE}/api/documents/${encodeURIComponent(docId)}/file${page ? `#page=${page}` : ''}`;
  }

  pageImageUrl(docId: string, page: number, width: number): string {
    return `${API_BASE}/api/documents/${encodeURIComponent(docId)}/pages/${page}?width=${width}`;
  }

  locate(
    docId: string,
    body: { page?: number | null; chunk_id?: string; claim?: string; passage?: string; table?: string; exact?: boolean },
    signal?: AbortSignal,
  ): Promise<LocateResult> {
    return this.request(
      `/api/documents/${encodeURIComponent(docId)}/locate`,
      { method: 'POST', body: JSON.stringify(body), signal },
      'Could not find the passage in the document',
    );
  }

  getDocumentText(docId: string): Promise<DocumentText> {
    return this.request(`/api/documents/${encodeURIComponent(docId)}/text`, {}, 'Could not load the document text');
  }

  getDocumentTable(docId: string, table: string, limit?: number): Promise<TableData> {
    const q = limit ? `?limit=${limit}` : '';
    return this.request(`/api/documents/${encodeURIComponent(docId)}/tables/${encodeURIComponent(table)}${q}`, {}, 'Could not load the table');
  }

  /** Passages that match, found by meaning and by exact words, with no model call. */
  search(query: string, documentIds?: string[], topK = 20): Promise<{ candidates: number; results: SearchHit[] }> {
    return this.request('/api/search', { method: 'POST', body: JSON.stringify({ query, document_ids: documentIds?.length ? documentIds : null, top_k: topK }) }, 'Search failed');
  }

  libraryTables(): Promise<{ tables: LibraryTable[] }> {
    return this.request('/api/tables', {}, 'Could not list the tables');
  }

  libraryRecords(): Promise<{ records: LibraryRecord[] }> {
    return this.request('/api/records', {}, 'Could not list the records');
  }

  timeline(documentIds?: string[]): Promise<{ events: TimelineEvent[]; total: number }> {
    const q = documentIds?.length ? `?doc_ids=${encodeURIComponent(documentIds.join(','))}` : '';
    return this.request(`/api/timeline${q}`, {}, 'Could not build the timeline');
  }

  createToken(name: string): Promise<{ token: string; name: string; expires_in_days: number }> {
    return this.request('/api/account/tokens', { method: 'POST', body: JSON.stringify({ name }) }, 'Could not create the token');
  }

  adminOverview(): Promise<AdminOverview> {
    return this.request('/api/admin/overview', {}, 'Could not load the server overview');
  }

  claimAdmin(code: string): Promise<{ admin: boolean }> {
    return this.request('/api/admin/claim', { method: 'POST', body: JSON.stringify({ code }) }, 'Could not claim the role');
  }

  announce(title: string, body: string, url?: string): Promise<{ id: number }> {
    return this.request('/api/admin/announce', { method: 'POST', body: JSON.stringify({ title, body, url: url || null }) }, 'Could not post the announcement');
  }

  getDocumentSummary(docId: string): Promise<{ status: 'ready' | 'pending' | 'missing'; summary: DocumentSummary | null; progress?: { processed: number; total: number } | null }> {
    return this.request(`/api/documents/${encodeURIComponent(docId)}/summary`, {}, 'Could not load the summary');
  }

  getRecord(docId: string): Promise<DocumentRecord> {
    return this.request(`/api/documents/${encodeURIComponent(docId)}/record`, {}, 'Could not load the extracted fields');
  }

  extractRecord(docId: string, docType?: string): Promise<DocumentRecord> {
    return this.request(
      `/api/documents/${encodeURIComponent(docId)}/record`,
      { method: 'POST', body: JSON.stringify({ doc_type: docType ?? null }) },
      'Extraction failed',
    );
  }

  webPage(url: string, passage = '', claim = '', signal?: AbortSignal): Promise<WebPage> {
    const q = new URLSearchParams({ url, passage: passage.slice(0, 1500), claim: claim.slice(0, 600) });
    return this.request(`/api/web/page?${q}`, { signal }, 'Could not open that page');
  }

  getSensitive(docId: string): Promise<{ findings: SensitiveFinding[]; counts: Record<string, number> }> {
    return this.request(`/api/documents/${encodeURIComponent(docId)}/sensitive`, {}, 'Could not scan the document');
  }

  async redact(docId: string, types?: string[]): Promise<{ blob: Blob; filename: string }> {
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/api/documents/${encodeURIComponent(docId)}/redact`, {
        method: 'POST',
        headers: this.headers(),
        body: JSON.stringify({ types: types ?? null }),
      });
    } catch {
      throw new ApiError('Cannot reach the OmniDoc server.', 0);
    }
    if (!res.ok) throw await this.failed(res, 'Could not create the redacted copy');
    const disposition = res.headers.get('content-disposition') || '';
    const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
    const plain = /filename="([^"]+)"/i.exec(disposition);
    const filename = star ? decodeURIComponent(star[1]) : plain ? plain[1] : 'redacted';
    return { blob: await res.blob(), filename };
  }

  compare(a: string, b: string, summarize = false): Promise<CompareResult> {
    return this.request('/api/compare', { method: 'POST', body: JSON.stringify({ a, b, summarize }) }, 'Comparison failed');
  }

  getProviders(): Promise<ProvidersInfo> {
    return this.request('/api/providers', {}, 'Could not load the model providers');
  }

  // ---- Extraction ----------------------------------------------------------
  getExtractPresets(): Promise<{ presets: ExtractPreset[]; types: FieldType[] }> {
    return this.request('/api/extract/presets', {}, 'Could not load the templates');
  }

  /** Fills the fields from each document, reporting progress; resolves with CSV rows of all results. */
  async streamExtract(body: { document_ids: string[]; fields: ExtractField[] }, handlers: ExtractHandlers = {}): Promise<string[][]> {
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/api/extract/stream`, {
        method: 'POST',
        headers: { ...this.headers(), Accept: 'text/event-stream' },
        body: JSON.stringify(body),
        signal: handlers.signal,
      });
    } catch (err) {
      if ((err as Error).name === 'AbortError') throw err;
      throw new ApiError('Cannot reach the OmniDoc server. Is it running on port 8000?', 0);
    }
    if (!res.ok || !res.body) throw await this.failed(res, 'Extraction failed');
    let csv: string[][] | null = null;
    await readEvents(res, (event, data) => {
      if (event === 'doc_start') handlers.onDocStart?.(data as never);
      else if (event === 'progress') handlers.onProgress?.(data as never);
      else if (event === 'doc_result') handlers.onResult?.(data as ExtractResult);
      else if (event === 'doc_error') handlers.onDocError?.(data as never);
      else if (event === 'done') csv = (data as { csv_rows?: string[][] }).csv_rows ?? [];
    });
    if (!csv) throw new ApiError('The server closed the stream before finishing', 500);
    return csv;
  }

  // ---- Knowledge graph -----------------------------------------------------
  getGraph(limit = 2000): Promise<GraphData> {
    return this.request<GraphData>(`/api/graph?limit=${limit}`, {}, 'Could not load the knowledge graph');
  }

  // ---- Export --------------------------------------------------------------
  async exportChat(chatId: string, format: 'pdf' | 'docx'): Promise<Blob> {
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/api/export/${format}`, {
        method: 'POST',
        headers: this.headers(),
        body: JSON.stringify({ chat_id: chatId }),
      });
    } catch {
      throw new ApiError('Cannot reach the OmniDoc server.', 0);
    }
    if (!res.ok) throw await this.failed(res, `Could not export ${format.toUpperCase()}`);
    return res.blob();
  }
}

export const api = new OmniDocApiClient();
