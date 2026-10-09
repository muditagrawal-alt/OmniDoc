/**
 * OmniDoc API client and shared response types.
 *
 * In development Vite proxies /api to the FastAPI server (see vite.config.ts),
 * so the default base is same-origin. Set VITE_API_BASE to point elsewhere.
 */

export interface User {
  id: string;
  email: string;
  name: string;
  provider: string;
  avatar_url?: string;
}

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
    return h;
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
    if (!res.ok) throw await readError(res, fallback);
    return res.json() as Promise<T>;
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

  async getModels(): Promise<{ models: ModelInfo[]; current: string }> {
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
    body: { query: string; document_ids?: string[]; language?: string; web?: WebMode },
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
    if (!res.ok || !res.body) throw await readError(res, 'The query failed');

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

  getDocumentTable(docId: string, table: string): Promise<TableData> {
    return this.request(`/api/documents/${encodeURIComponent(docId)}/tables/${encodeURIComponent(table)}`, {}, 'Could not load the table');
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
    if (!res.ok) throw await readError(res, 'Could not create the redacted copy');
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
    if (!res.ok || !res.body) throw await readError(res, 'Extraction failed');
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
    if (!res.ok) throw await readError(res, `Could not export ${format.toUpperCase()}`);
    return res.blob();
  }
}

export const api = new OmniDocApiClient();
