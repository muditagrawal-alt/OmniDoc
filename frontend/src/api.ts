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
  kind: 'chunk' | 'graph' | 'math' | 'visual' | 'web' | 'conflict' | string;
  doc_id: string;
  doc_title?: string;
  chunk_id?: string;
  page?: number | null;
  section?: string;
  title?: string;
  snippet: string;
  score?: number | null;
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

export interface Verification {
  status: 'verified' | 'partial' | 'unverified';
  score: number | null;
  supported: number;
  unsupported: number;
  feedback?: string;
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

export interface AnswerPayload {
  answer: string;
  sources: Source[];
  math_results: MathResult[];
  visual_artifacts: ChartArtifact[];
  conflicts: ConflictItem[];
  graph: GraphData;
  steps: AgentStep[];
  verification: Verification;
  model?: string;
  elapsed_ms?: number;
  document_ids?: string[];
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
  /** Background knowledge-graph extraction progress (null once the server restarts). */
  graph_status?: { status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled'; processed: number; total: number; entities?: number } | null;
}

export interface UploadResult {
  doc_id: string;
  filename: string;
  chunk_count: number;
  duplicate?: boolean;
}

export interface ModelInfo {
  name: string;
  size_gb?: number | null;
  parameter_size?: string | null;
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
    if (this.token) h.Authorization = `Bearer ${this.token}`;
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
    body: { query: string; document_ids?: string[]; language?: string },
    handlers: { onStep?: (step: AgentStep) => void; signal?: AbortSignal } = {},
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

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let result: QueryResponse | null = null;

    const handleEvent = (raw: string) => {
      let event = 'message';
      const dataLines: string[] = [];
      for (const line of raw.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
      }
      if (!dataLines.length) return;
      const data = JSON.parse(dataLines.join('\n'));
      if (event === 'step') handlers.onStep?.(data as AgentStep);
      else if (event === 'result') result = data as QueryResponse;
      else if (event === 'error') throw new ApiError(data?.message || 'The query failed', 500);
    };

    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
      let sep: number;
      while ((sep = buffer.indexOf('\n\n')) !== -1) {
        const chunk = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        if (chunk.trim()) handleEvent(chunk);
      }
    }
    if (buffer.trim()) handleEvent(buffer);
    if (!result) throw new ApiError('The server closed the stream before answering', 500);
    return result;
  }

  // ---- Documents -----------------------------------------------------------
  async getDocuments(): Promise<DocumentItem[]> {
    const data = await this.request<{ documents: DocumentItem[] }>('/api/documents', {}, 'Could not load the library');
    return data.documents;
  }

  uploadDocument(file: File): Promise<UploadResult> {
    const form = new FormData();
    form.append('file', file);
    return this.request<UploadResult>('/api/documents/upload', { method: 'POST', body: form }, 'Upload failed');
  }

  async deleteDocument(docId: string): Promise<void> {
    await this.request(`/api/documents/${encodeURIComponent(docId)}`, { method: 'DELETE' }, 'Could not delete the document');
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
