/**
 * Indexes raw GraphData for the knowledge view: resolves edges to node
 * indices (by id, falling back to name), drops self-loops and exact
 * duplicates, and precomputes degree, connections and family per entity.
 */
import type { GraphData } from '../../api';
import { ALL_FAMILIES, familyOf, type CategoryFamily } from '../../lib/categories';

export interface Entity {
  index: number;
  id: string;
  name: string;
  category: string;
  description: string;
  docId: string | null;
  family: CategoryFamily;
  /** Number of distinct neighbours. */
  degree: number;
}

export interface Relation {
  source: number;
  target: number;
  relation: string;
  description: string;
}

export interface Connection {
  relation: number;
  neighbor: number;
  /** true when this entity is the relation's source. */
  outgoing: boolean;
}

export interface FamilyCount {
  family: CategoryFamily;
  count: number;
}

export interface GraphModel {
  entities: Entity[];
  relations: Relation[];
  connections: Connection[][];
  /** Unique undirected neighbour pairs, flat [a0, b0, a1, b1, ...]. */
  pairs: Int32Array;
  documents: Array<{ id: string; title: string }>;
  docTitle: Map<string, string>;
  /** Entity indices sorted by degree desc, then name. */
  byDegree: number[];
}

export const EMPTY_MODEL: GraphModel = {
  entities: [],
  relations: [],
  connections: [],
  pairs: new Int32Array(0),
  documents: [],
  docTitle: new Map(),
  byDegree: [],
};

export function buildGraphModel(data: GraphData | null | undefined): GraphModel {
  if (!data || !Array.isArray(data.nodes) || data.nodes.length === 0) {
    return { ...EMPTY_MODEL, documents: data?.documents ?? [], docTitle: docTitles(data) };
  }

  const entities: Entity[] = [];
  const byId = new Map<string, number>();
  const byName = new Map<string, number>();
  for (const node of data.nodes) {
    const id = String(node.id ?? '');
    if (!id || byId.has(id)) continue;
    const name = (node.name || '').trim() || id;
    const index = entities.length;
    entities.push({
      index,
      id,
      name,
      category: (node.category || '').trim() || 'Entity',
      description: (node.description || '').trim(),
      docId: node.doc_id || null,
      family: familyOf(node.category),
      degree: 0,
    });
    byId.set(id, index);
    const key = name.toLowerCase();
    if (!byName.has(key)) byName.set(key, index);
  }

  const resolve = (id: string | undefined, name: string | undefined): number => {
    if (id !== undefined && byId.has(id)) return byId.get(id)!;
    if (name) {
      const hit = byName.get(name.trim().toLowerCase());
      if (hit !== undefined) return hit;
    }
    if (id) {
      const hit = byName.get(id.trim().toLowerCase());
      if (hit !== undefined) return hit;
    }
    return -1;
  };

  const relations: Relation[] = [];
  const connections: Connection[][] = entities.map(() => []);
  const seenRelation = new Set<string>();
  const pairSet = new Set<number>();
  const pairs: number[] = [];
  const n = entities.length;

  for (const edge of data.edges ?? []) {
    const s = resolve(edge.source, edge.source_name);
    const t = resolve(edge.target, edge.target_name);
    if (s < 0 || t < 0 || s === t) continue;
    const relation = (edge.relation || '').trim() || 'RELATED_TO';
    const rKey = `${s}\u0000${t}\u0000${relation.toLowerCase()}`;
    if (seenRelation.has(rKey)) continue;
    seenRelation.add(rKey);
    const ri = relations.length;
    relations.push({ source: s, target: t, relation, description: (edge.description || '').trim() });
    connections[s].push({ relation: ri, neighbor: t, outgoing: true });
    connections[t].push({ relation: ri, neighbor: s, outgoing: false });
    const a = Math.min(s, t);
    const b = Math.max(s, t);
    const pKey = a * n + b;
    if (!pairSet.has(pKey)) {
      pairSet.add(pKey);
      pairs.push(a, b);
      entities[a].degree++;
      entities[b].degree++;
    }
  }

  // strongest neighbours first in every connection list
  for (const list of connections) {
    list.sort(
      (x, y) =>
        entities[y.neighbor].degree - entities[x.neighbor].degree ||
        entities[x.neighbor].name.localeCompare(entities[y.neighbor].name),
    );
  }

  const byDegree = entities
    .map((e) => e.index)
    .sort((a, b) => entities[b].degree - entities[a].degree || entities[a].name.localeCompare(entities[b].name));

  const documents = data.documents?.length ? data.documents : inferDocuments(entities);

  return {
    entities,
    relations,
    connections,
    pairs: Int32Array.from(pairs),
    documents,
    docTitle: docTitles({ ...data, documents }),
    byDegree,
  };
}

function docTitles(data: Pick<GraphData, 'documents'> | null | undefined): Map<string, string> {
  const map = new Map<string, string>();
  for (const d of data?.documents ?? []) if (d?.id) map.set(d.id, d.title || d.id);
  return map;
}

function inferDocuments(entities: Entity[]): Array<{ id: string; title: string }> {
  const ids = new Set<string>();
  for (const e of entities) if (e.docId) ids.add(e.docId);
  return [...ids].map((id) => ({ id, title: id }));
}

/** Families that occur in `indices` (or all entities), in canonical order, with counts. */
export function familyCounts(model: GraphModel, include?: (e: Entity) => boolean): FamilyCount[] {
  const counts = new Map<string, number>();
  for (const e of model.entities) {
    if (include && !include(e)) continue;
    counts.set(e.family.key, (counts.get(e.family.key) ?? 0) + 1);
  }
  return ALL_FAMILIES.filter((f) => counts.has(f.key)).map((family) => ({ family, count: counts.get(family.key)! }));
}

/** Case-insensitive exact name lookup; preserves the order of `names`. */
export function findEntitiesByName(model: GraphModel, names: readonly string[]): number[] {
  const wanted = names.map((s) => s.trim().toLowerCase()).filter(Boolean);
  if (!wanted.length) return [];
  const index = new Map<string, number>();
  for (const e of model.entities) {
    const key = e.name.toLowerCase();
    if (!index.has(key)) index.set(key, e.index);
  }
  const out: number[] = [];
  for (const w of wanted) {
    const hit = index.get(w);
    if (hit !== undefined && !out.includes(hit)) out.push(hit);
  }
  return out;
}

/**
 * Entities whose name (or category) contains `query`, best first: exact name,
 * name prefix, word prefix, substring, category match; ties by degree.
 */
export function searchEntities(model: GraphModel, query: string, visible?: Uint8Array): number[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const scored: Array<[number, number]> = [];
  for (const e of model.entities) {
    if (visible && !visible[e.index]) continue;
    const name = e.name.toLowerCase();
    let score = -1;
    if (name === q) score = 5;
    else if (name.startsWith(q)) score = 4;
    else if (name.includes(` ${q}`) || name.includes(`-${q}`)) score = 3;
    else if (name.includes(q)) score = 2;
    else if (e.category.toLowerCase().includes(q)) score = 1;
    if (score >= 0) scored.push([e.index, score]);
  }
  scored.sort((a, b) => b[1] - a[1] || model.entities[b[0]].degree - model.entities[a[0]].degree);
  return scored.map((s) => s[0]);
}

export function plural(n: number, one: string, many: string): string {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`;
}
