/**
 * OmniDoc Frontend API Client & Type Definitions
 */

export interface User {
  id: string;
  email: string;
  name: string;
  provider: 'google' | 'apple' | 'email';
  avatar_url: string;
}

export interface ChatSession {
  id: string;
  title: string;
  document_id?: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
  last_message?: string;
}

export interface MathResult {
  expression: string;
  result: number | string;
  unit?: string;
  verified: boolean;
  steps?: string[];
  computation_trace?: string;
}

export interface EvidenceSource {
  chunk_id: string;
  doc_id: string;
  snippet: string;
  score: number;
  source_type: string;
}

export interface ConflictItem {
  entity: string;
  claim_a: string;
  claim_b: string;
  source_a: string;
  source_b: string;
  resolution: string;
  confidence?: number;
}

export interface GraphNode {
  id: string;
  name: string;
  category: string;
  description: string;
  x?: number;
  y?: number;
}

export interface GraphEdge {
  source: string;
  source_name: string;
  target: string;
  target_name: string;
  relation: string;
  description: string;
}

export interface GeoLocationItem {
  id: string;
  name: string;
  region: string;
  country: string;
  lat: number;
  lon: number;
  description: string;
  radius_meters?: number;
  highlight_color?: string;
  entities?: string[];
  metrics?: Record<string, string>;
}

export interface ChatMetadata {
  math_results?: MathResult[];
  visual_artifacts?: any[];
  geo_locations?: GeoLocationItem[];
  sources?: EvidenceSource[];
  conflicts?: ConflictItem[];
  graph_entities?: GraphNode[];
  thought_process?: string[];
  groundedness_score?: number;
  document_ids?: string[];
}

export interface ChatMessage {
  id?: number;
  chat_id?: string;
  role: 'user' | 'assistant';
  content: string;
  metadata?: ChatMetadata;
  timestamp?: string;
}

export interface DocumentItem {
  id: string;
  filename: string;
  upload_date: string;
  size_bytes: number;
  file_type: string;
}

const API_BASE = 'http://localhost:8000';

class OmniDocApiClient {
  private token: string | null = null;

  constructor() {
    this.token = localStorage.getItem('omnidoc_token');
  }

  setToken(token: string | null) {
    this.token = token;
    if (token) {
      localStorage.setItem('omnidoc_token', token);
    } else {
      localStorage.removeItem('omnidoc_token');
    }
  }

  getToken(): string | null {
    return this.token;
  }

  private headers(isJson = true): HeadersInit {
    const headers: Record<string, string> = {};
    if (isJson) {
      headers['Content-Type'] = 'application/json';
    }
    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }
    return headers;
  }

  async login(provider: 'google' | 'apple' | 'email', email?: string, name?: string): Promise<{ user: User; token: string }> {
    const res = await fetch(`${API_BASE}/api/auth/login`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify({ provider, email, name }),
    });
    if (!res.ok) throw new Error('Authentication failed');
    const data = await res.json();
    this.setToken(data.token);
    return data;
  }

  async getMe(): Promise<User | null> {
    if (!this.token) return null;
    try {
      const res = await fetch(`${API_BASE}/api/auth/me`, {
        headers: this.headers(),
      });
      if (!res.ok) {
        this.setToken(null);
        return null;
      }
      const data = await res.json();
      return data.user;
    } catch {
      return null;
    }
  }

  async logout(): Promise<void> {
    this.setToken(null);
  }

  async getChats(): Promise<ChatSession[]> {
    const res = await fetch(`${API_BASE}/api/chats`, {
      headers: this.headers(),
    });
    if (!res.ok) throw new Error('Failed to fetch chats');
    const data = await res.json();
    return data.chats;
  }

  async createChat(title?: string, documentId?: string): Promise<ChatSession> {
    const res = await fetch(`${API_BASE}/api/chats`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify({ title, document_id: documentId }),
    });
    if (!res.ok) throw new Error('Failed to create chat');
    const data = await res.json();
    return data.chat;
  }

  async getChat(chatId: string): Promise<{ chat: ChatSession; messages: ChatMessage[] }> {
    const res = await fetch(`${API_BASE}/api/chats/${chatId}`, {
      headers: this.headers(),
    });
    if (!res.ok) throw new Error('Failed to fetch chat details');
    return res.json();
  }

  async renameChat(chatId: string, title: string): Promise<void> {
    const res = await fetch(`${API_BASE}/api/chats/${chatId}`, {
      method: 'PATCH',
      headers: this.headers(),
      body: JSON.stringify({ title }),
    });
    if (!res.ok) throw new Error('Failed to rename chat');
  }

  async deleteChat(chatId: string): Promise<void> {
    const res = await fetch(`${API_BASE}/api/chats/${chatId}`, {
      method: 'DELETE',
      headers: this.headers(),
    });
    if (!res.ok) throw new Error('Failed to delete chat');
  }

  async queryChat(
    chatId: string,
    query: string,
    documentIds?: string[],
    language: string = 'en'
  ): Promise<{
    answer: string;
    math_results: MathResult[];
    visual_artifacts: any[];
    geo_locations?: GeoLocationItem[];
    sources: EvidenceSource[];
    conflicts: ConflictItem[];
    graph_entities: GraphNode[];
    thought_process: string[];
    groundedness_score: number;
  }> {
    const res = await fetch(`${API_BASE}/api/chats/${chatId}/query`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify({ query, document_ids: documentIds, language }),
    });
    if (!res.ok) {
      const err = await res.text();
      throw new Error(err || 'Query failed');
    }
    return res.json();
  }

  async getGraph(limit: number = 150): Promise<{ nodes: GraphNode[]; edges: GraphEdge[] }> {
    const res = await fetch(`${API_BASE}/api/graph?limit=${limit}`, {
      headers: this.headers(),
    });
    if (!res.ok) throw new Error('Failed to fetch knowledge graph');
    return res.json();
  }

  async getNodeDetails(nodeId: string): Promise<{ node: GraphNode; connected_edges: GraphEdge[]; stats: any }> {
    const res = await fetch(`${API_BASE}/api/graph/node/${encodeURIComponent(nodeId)}`, {
      headers: this.headers(),
    });
    if (!res.ok) throw new Error('Failed to fetch node details');
    return res.json();
  }

  async getDocuments(): Promise<DocumentItem[]> {
    const res = await fetch(`${API_BASE}/api/documents`, {
      headers: this.headers(),
    });
    if (!res.ok) throw new Error('Failed to fetch documents');
    const data = await res.json();
    return data.documents;
  }

  async uploadDocument(file: File): Promise<{ doc_id: string; filename: string; chunk_count: number }> {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${API_BASE}/api/documents/upload`, {
      method: 'POST',
      headers: this.headers(false),
      body: formData,
    });
    if (!res.ok) throw new Error('Document upload failed');
    return res.json();
  }

  async deleteDocument(docId: string): Promise<void> {
    const res = await fetch(`${API_BASE}/api/documents/${encodeURIComponent(docId)}`, {
      method: 'DELETE',
      headers: this.headers(),
    });
    if (!res.ok) throw new Error('Failed to delete document');
  }

  async exportPdf(chatId?: string, messages?: any[], title?: string): Promise<Blob> {
    const res = await fetch(`${API_BASE}/api/export/pdf`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify({ chat_id: chatId, messages, title }),
    });
    if (!res.ok) throw new Error('Failed to export PDF');
    return res.blob();
  }

  async exportDocx(chatId?: string, messages?: any[], title?: string): Promise<Blob> {
    const res = await fetch(`${API_BASE}/api/export/docx`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify({ chat_id: chatId, messages, title }),
    });
    if (!res.ok) throw new Error('Failed to export DOCX');
    return res.blob();
  }
}

export const api = new OmniDocApiClient();
