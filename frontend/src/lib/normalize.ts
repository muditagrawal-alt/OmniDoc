import type {
  AgentStep,
  AnswerPayload,
  ChartArtifact,
  ChatMetadata,
  ConflictItem,
  GraphData,
  GraphEdge,
  GraphNode,
  MathResult,
  Source,
  TableResult,
  Usage,
  Verification,
} from '../api';

/**
 * Message metadata comes from two generations of the backend. Current rows carry
 * the AnswerPayload fields; older rows used thought_process / graph_entities and
 * stored placeholder scores (0.95 per source, 0.98 groundedness) that were never
 * measured. Those placeholders are dropped rather than shown as real numbers.
 * Older rows also mixed hardcoded demo charts and map pins into every answer;
 * they cannot be told apart from real ones, so charts from those rows are not shown.
 */
export interface NormalizedAnswer {
  sources: Source[];
  steps: AgentStep[];
  verification: Verification | null;
  math: MathResult[];
  tables: TableResult[];
  charts: ChartArtifact[];
  conflicts: ConflictItem[];
  graph: GraphData;
  model?: string;
  elapsedMs?: number;
  usage?: Usage;
}

const asArray = <T,>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);

function normalizeSources(raw: unknown): Source[] {
  return asArray<Record<string, unknown>>(raw).map((s, i) => {
    const legacy = typeof s.n !== 'number';
    const score = typeof s.score === 'number' ? s.score : null;
    return {
      n: legacy ? i + 1 : (s.n as number),
      kind: String(s.kind ?? s.source_type ?? 'chunk'),
      doc_id: String(s.doc_id ?? ''),
      doc_title: s.doc_title ? String(s.doc_title) : undefined,
      chunk_id: s.chunk_id ? String(s.chunk_id) : undefined,
      page: typeof s.page === 'number' ? s.page : null,
      section: s.section ? String(s.section) : undefined,
      title: s.title ? String(s.title) : undefined,
      snippet: String(s.snippet ?? ''),
      // Legacy rows stored a constant 0.95 for every source.
      score: legacy && score === 0.95 ? null : score,
      url: typeof s.url === 'string' ? s.url : undefined,
      site: typeof s.site === 'string' ? s.site : undefined,
      published: typeof s.published === 'string' ? s.published : undefined,
      table: typeof s.table === 'string' ? s.table : undefined,
    };
  });
}

function normalizeSteps(meta: ChatMetadata): AgentStep[] {
  if (Array.isArray(meta.steps)) return meta.steps as AgentStep[];
  return asArray<unknown>(meta.thought_process)
    .filter((t): t is string => typeof t === 'string' && t.trim().length > 0)
    .map((label, i) => ({ node: `legacy_${i}`, label }));
}

function normalizeGraph(meta: ChatMetadata): GraphData {
  const g = meta.graph as GraphData | undefined;
  if (g && Array.isArray(g.nodes)) return { nodes: g.nodes, edges: asArray<GraphEdge>(g.edges) };
  const nodes = new Map<string, GraphNode>();
  const edges: GraphEdge[] = [];
  for (const sub of asArray<Record<string, unknown>>(meta.graph_entities)) {
    for (const n of asArray<Record<string, unknown>>(sub.nodes)) {
      const id = String(n.id ?? '');
      if (id) nodes.set(id, { id, name: String(n.name ?? id), category: String(n.category ?? 'Entity'), description: String(n.description ?? '') });
    }
    for (const e of asArray<Record<string, unknown>>(sub.edges)) {
      const source = String(e.source_id ?? e.source ?? '');
      const target = String(e.target_id ?? e.target ?? '');
      if (source && target) {
        edges.push({
          source,
          target,
          source_name: String(e.source_name ?? ''),
          target_name: String(e.target_name ?? ''),
          relation: String(e.relation ?? 'RELATED_TO'),
          description: String(e.description ?? ''),
        });
      }
    }
  }
  return { nodes: [...nodes.values()], edges };
}

export function normalizeAnswer(meta?: ChatMetadata | null): NormalizedAnswer {
  const m: ChatMetadata = meta ?? {};
  const verification = (m.verification as Verification | undefined) ?? null;
  // Rows written by the current backend always carry a verification block.
  const current = m.verification != null;
  return {
    sources: normalizeSources(m.sources),
    steps: normalizeSteps(m),
    verification,
    math: asArray<MathResult>(m.math_results),
    tables: asArray<TableResult>(m.table_results).filter((t) => t && typeof t.sql === 'string' && Array.isArray(t.rows)),
    charts: current ? asArray<ChartArtifact>(m.visual_artifacts) : [],
    conflicts: asArray<ConflictItem>(m.conflicts),
    graph: normalizeGraph(m),
    model: typeof m.model === 'string' ? m.model : undefined,
    elapsedMs: typeof m.elapsed_ms === 'number' ? m.elapsed_ms : undefined,
    usage: m.usage && typeof m.usage === 'object' ? (m.usage as Usage) : undefined,
  };
}

export function payloadToMetadata(p: AnswerPayload): ChatMetadata {
  const { answer: _answer, ...rest } = p;
  void _answer;
  return rest as ChatMetadata;
}
