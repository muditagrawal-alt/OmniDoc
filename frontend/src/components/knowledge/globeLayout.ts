/**
 * Deterministic layout of a knowledge graph on the unit sphere.
 *
 * Pipeline (all pure, no DOM, no three.js):
 *   1. degree + CSR adjacency
 *   2. communities by seeded asynchronous label propagation
 *   3. community centroids on a Fibonacci lattice (farthest-point order, so the
 *      largest communities are spread apart), then relaxed so each community's
 *      spherical cap (area proportional to its size) does not overlap another,
 *      while communities that share edges drift towards each other
 *   4. members spread around their centroid on a sunflower spiral, hubs at the
 *      centre
 *   5. a few iterations of constrained force relaxation on the sphere: springs
 *      along edges, short-range repulsion through a spatial grid, renormalised
 *      to the sphere after every step
 *   6. the whole layout is rotated so the largest community faces `front`
 *
 * Every random choice comes from a seeded PRNG, so the same input always
 * produces the same layout.
 */

/** Flat list of undirected edges: [a0, b0, a1, b1, ...] (node indices). */
export type EdgeList = ArrayLike<number>;

export type Vec3 = readonly [number, number, number];

export interface Adjacency {
  /** offsets[i]..offsets[i + 1] indexes into `neighbors` for node i. */
  offsets: Int32Array;
  neighbors: Int32Array;
}

export interface GlobeLayoutOptions {
  /** PRNG seed. Same seed + same graph = same layout. */
  seed?: number;
  /** Force relaxation iterations. Defaults scale with graph size. */
  iterations?: number;
  /** Unit vector the largest community should face (the default camera direction). */
  front?: Vec3;
}

export interface GlobeLayout {
  /** xyz per node, unit length. */
  positions: Float32Array;
  degree: Int32Array;
  /** Community id per node; 0 is the largest community. */
  community: Int32Array;
  communityCount: number;
  /** Typical angular distance (radians) between neighbouring nodes. */
  spacing: number;
}

export const DEFAULT_FRONT: Vec3 = normalize3(0, 0.34, 1);

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
/** Largest angular spacing between neighbours (radians), so tiny graphs cluster. */
const MAX_SPACING = 0.42;

function normalize3(x: number, y: number, z: number): Vec3 {
  const l = Math.hypot(x, y, z) || 1;
  return [x / l, y / l, z / l];
}

function clamp(v: number, lo: number, hi: number): number {
  return v < lo ? lo : v > hi ? hi : v;
}

/** mulberry32: small, fast, good-enough seeded PRNG returning [0, 1). */
export function createRng(seed: number): () => number {
  let a = seed >>> 0 || 0x9e3779b9;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** FNV-1a hash, handy for deriving a seed from node ids. */
export function hashString(s: string, h = 0x811c9dc5): number {
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/** Compressed adjacency. Self-loops and out-of-range indices are ignored. */
export function buildAdjacency(n: number, edges: EdgeList): Adjacency {
  const deg = new Int32Array(n);
  const m = edges.length >> 1;
  for (let e = 0; e < m; e++) {
    const a = edges[2 * e];
    const b = edges[2 * e + 1];
    if (a === b || a < 0 || b < 0 || a >= n || b >= n) continue;
    deg[a]++;
    deg[b]++;
  }
  const offsets = new Int32Array(n + 1);
  for (let i = 0; i < n; i++) offsets[i + 1] = offsets[i] + deg[i];
  const neighbors = new Int32Array(offsets[n]);
  const cursor = offsets.slice(0, n);
  for (let e = 0; e < m; e++) {
    const a = edges[2 * e];
    const b = edges[2 * e + 1];
    if (a === b || a < 0 || b < 0 || a >= n || b >= n) continue;
    neighbors[cursor[a]++] = b;
    neighbors[cursor[b]++] = a;
  }
  return { offsets, neighbors };
}

export function computeDegree(n: number, edges: EdgeList): Int32Array {
  return degreeOf(buildAdjacency(n, edges));
}

function degreeOf(adj: Adjacency): Int32Array {
  const n = adj.offsets.length - 1;
  const degree = new Int32Array(Math.max(0, n));
  for (let i = 0; i < n; i++) degree[i] = adj.offsets[i + 1] - adj.offsets[i];
  return degree;
}

function shuffleInPlace(arr: Int32Array, rng: () => number) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    const t = arr[i];
    arr[i] = arr[j];
    arr[j] = t;
  }
}

/**
 * Asynchronous label propagation with a seeded visiting order. Ties keep the
 * current label, otherwise the smallest label wins, so results are stable.
 * Returns compact community ids ordered by size (0 = largest); isolated nodes
 * are singleton communities.
 */
export function detectCommunities(n: number, adj: Adjacency, seed = 1, maxIterations = 30): Int32Array {
  const labels = new Int32Array(n);
  for (let i = 0; i < n; i++) labels[i] = i;
  if (n === 0) return labels;

  const order = new Int32Array(n);
  for (let i = 0; i < n; i++) order[i] = i;
  const rng = createRng(seed ^ 0x51ed27);
  const weight = new Float64Array(n);
  const touched: number[] = [];
  const { offsets, neighbors } = adj;

  for (let it = 0; it < maxIterations; it++) {
    shuffleInPlace(order, rng);
    let changed = 0;
    for (let k = 0; k < n; k++) {
      const v = order[k];
      const s = offsets[v];
      const e = offsets[v + 1];
      if (s === e) continue;
      for (let q = s; q < e; q++) {
        const l = labels[neighbors[q]];
        if (weight[l] === 0) touched.push(l);
        weight[l] += 1;
      }
      let maxW = 0;
      for (const l of touched) if (weight[l] > maxW) maxW = weight[l];
      const current = labels[v];
      let next = current;
      if (weight[current] !== maxW) {
        next = Number.MAX_SAFE_INTEGER;
        for (const l of touched) if (weight[l] === maxW && l < next) next = l;
      }
      for (const l of touched) weight[l] = 0;
      touched.length = 0;
      if (next !== current) {
        labels[v] = next;
        changed++;
      }
    }
    if (changed === 0) break;
  }

  return relabelBySize(labels);
}

/** Maps arbitrary labels to 0..k-1 ordered by size desc (ties: first occurrence). */
function relabelBySize(labels: Int32Array): Int32Array {
  const size = new Map<number, number>();
  const first = new Map<number, number>();
  for (let i = 0; i < labels.length; i++) {
    const l = labels[i];
    size.set(l, (size.get(l) ?? 0) + 1);
    if (!first.has(l)) first.set(l, i);
  }
  const keys = [...size.keys()].sort((a, b) => size.get(b)! - size.get(a)! || first.get(a)! - first.get(b)!);
  const remap = new Map<number, number>();
  keys.forEach((k, i) => remap.set(k, i));
  const out = new Int32Array(labels.length);
  for (let i = 0; i < labels.length; i++) out[i] = remap.get(labels[i])!;
  return out;
}

/**
 * Label propagation fragments sparse graphs into many tiny communities. Folds
 * every community smaller than `minSize` into the neighbouring community it
 * shares the most edges with (ties: the larger one), smallest first.
 * Returns compact ids ordered by size.
 */
export function mergeSmallCommunities(labels: Int32Array, adj: Adjacency, minSize: number): Int32Array {
  const n = labels.length;
  const k = n === 0 ? 0 : Math.max(...labels) + 1;
  const parent = new Int32Array(k);
  const size = new Int32Array(k);
  for (let c = 0; c < k; c++) parent[c] = c;
  for (let i = 0; i < n; i++) size[labels[i]]++;
  const find = (c: number) => {
    while (parent[c] !== c) {
      parent[c] = parent[parent[c]];
      c = parent[c];
    }
    return c;
  };
  const membersOf: number[][] = Array.from({ length: k }, () => []);
  for (let i = 0; i < n; i++) membersOf[labels[i]].push(i);
  const order = [...Array(k).keys()].sort((a, b) => size[a] - size[b] || a - b);
  const counts = new Map<number, number>();
  for (const c0 of order) {
    const c = find(c0);
    if (size[c] >= minSize) continue;
    counts.clear();
    for (const i of membersOf[c0]) {
      for (let q = adj.offsets[i]; q < adj.offsets[i + 1]; q++) {
        const o = find(labels[adj.neighbors[q]]);
        if (o !== c) counts.set(o, (counts.get(o) ?? 0) + 1);
      }
    }
    let best = -1;
    let bestW = 0;
    for (const [o, w] of counts) {
      if (w > bestW || (w === bestW && (size[o] > size[best] || (size[o] === size[best] && o < best)))) {
        best = o;
        bestW = w;
      }
    }
    if (best < 0) continue;
    parent[c] = best;
    size[best] += size[c];
    membersOf[best].push(...membersOf[c0]);
  }
  const out = new Int32Array(n);
  for (let i = 0; i < n; i++) out[i] = find(labels[i]);
  return relabelBySize(out);
}

/** `count` evenly spread points on the unit sphere (xyz triples). */
export function fibonacciSphere(count: number): Float32Array {
  const out = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    const y = 1 - (2 * i + 1) / count;
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const th = GOLDEN_ANGLE * i;
    out[3 * i] = Math.cos(th) * r;
    out[3 * i + 1] = y;
    out[3 * i + 2] = Math.sin(th) * r;
  }
  return out;
}

/** Orders lattice points so each next point is as far as possible from all previous ones. */
function farthestPointOrder(points: Float32Array, count: number): Int32Array {
  const order = new Int32Array(count);
  if (count === 0) return order;
  const best = new Float64Array(count).fill(Infinity); // min chord^2 to chosen set
  const used = new Uint8Array(count);
  let current = 0;
  for (let k = 0; k < count; k++) {
    order[k] = current;
    used[current] = 1;
    const cx = points[3 * current];
    const cy = points[3 * current + 1];
    const cz = points[3 * current + 2];
    let next = -1;
    let nextD = -1;
    for (let i = 0; i < count; i++) {
      if (used[i]) continue;
      const dx = points[3 * i] - cx;
      const dy = points[3 * i + 1] - cy;
      const dz = points[3 * i + 2] - cz;
      const d = dx * dx + dy * dy + dz * dz;
      if (d < best[i]) best[i] = d;
      if (best[i] > nextD) {
        nextD = best[i];
        next = i;
      }
    }
    if (next < 0) break;
    current = next;
  }
  return order;
}

/** Orthonormal tangent basis (u, v) at unit vector c. */
function tangentBasis(cx: number, cy: number, cz: number): [number, number, number, number, number, number] {
  // pick the world axis least aligned with c
  let ax = 0;
  let ay = 1;
  let az = 0;
  if (Math.abs(cy) > 0.9) {
    ax = 1;
    ay = 0;
  }
  // u = normalize(a x c)
  let ux = ay * cz - az * cy;
  let uy = az * cx - ax * cz;
  let uz = ax * cy - ay * cx;
  const ul = Math.hypot(ux, uy, uz) || 1;
  ux /= ul;
  uy /= ul;
  uz /= ul;
  // v = c x u
  const vx = cy * uz - cz * uy;
  const vy = cz * ux - cx * uz;
  const vz = cx * uy - cy * ux;
  return [ux, uy, uz, vx, vy, vz];
}

/** Rotates every xyz triple in `pos` so that unit vector `from` maps onto unit vector `to`. */
export function rotateToFace(pos: Float32Array, from: Vec3, to: Vec3): void {
  const [fx, fy, fz] = from;
  const [tx, ty, tz] = to;
  const cos = clamp(fx * tx + fy * ty + fz * tz, -1, 1);
  let kx = fy * tz - fz * ty;
  let ky = fz * tx - fx * tz;
  let kz = fx * ty - fy * tx;
  let sin = Math.hypot(kx, ky, kz);
  if (sin < 1e-9) {
    if (cos > 0) return; // already aligned
    // opposite: rotate pi around any axis perpendicular to `from`
    const [ux, uy, uz] = tangentBasis(fx, fy, fz);
    kx = ux;
    ky = uy;
    kz = uz;
    sin = 0;
  } else {
    kx /= sin;
    ky /= sin;
    kz /= sin;
  }
  const c = cos;
  const s = sin;
  const t = 1 - c;
  // Rodrigues rotation matrix
  const m00 = c + kx * kx * t;
  const m01 = kx * ky * t - kz * s;
  const m02 = kx * kz * t + ky * s;
  const m10 = ky * kx * t + kz * s;
  const m11 = c + ky * ky * t;
  const m12 = ky * kz * t - kx * s;
  const m20 = kz * kx * t - ky * s;
  const m21 = kz * ky * t + kx * s;
  const m22 = c + kz * kz * t;
  for (let i = 0; i < pos.length; i += 3) {
    const x = pos[i];
    const y = pos[i + 1];
    const z = pos[i + 2];
    pos[i] = m00 * x + m01 * y + m02 * z;
    pos[i + 1] = m10 * x + m11 * y + m12 * z;
    pos[i + 2] = m20 * x + m21 * y + m22 * z;
  }
}

/** Fraction of the sphere's area the layout occupies; small graphs stay compact. */
export function fillFraction(n: number): number {
  return clamp(0.3 + 0.15 * Math.log10(Math.max(n, 1)), 0.34, 0.8);
}

/**
 * Lays out `nodeCount` nodes on the unit sphere. `edges` is a flat pair list of
 * node indices; duplicates add weight, self-loops are ignored.
 */
export function computeGlobeLayout(nodeCount: number, edges: EdgeList, options: GlobeLayoutOptions = {}): GlobeLayout {
  const n = Math.max(0, Math.floor(nodeCount));
  const seed = options.seed ?? 1;
  const front = options.front ?? DEFAULT_FRONT;
  const adj = buildAdjacency(n, edges);
  const degree = degreeOf(adj);
  const positions = new Float32Array(n * 3);

  if (n === 0) {
    return { positions, degree, community: new Int32Array(0), communityCount: 0, spacing: 0 };
  }
  if (n === 1) {
    positions.set(front);
    return { positions, degree, community: new Int32Array(1), communityCount: 1, spacing: Math.PI / 2 };
  }

  const rng = createRng(seed);

  // ---- 2. communities; all isolated nodes share one pseudo-community -------
  const lpa = mergeSmallCommunities(detectCommunities(n, adj, seed), adj, clamp(Math.round(n / 120), 3, 24));
  const ISOLATE = -1;
  const raw = new Int32Array(n);
  for (let i = 0; i < n; i++) raw[i] = degree[i] === 0 ? ISOLATE : lpa[i];
  // compact: connected communities by size desc, isolates last
  const sizeOf = new Map<number, number>();
  for (let i = 0; i < n; i++) sizeOf.set(raw[i], (sizeOf.get(raw[i]) ?? 0) + 1);
  const keys = [...sizeOf.keys()].sort((a, b) => {
    if (a === ISOLATE) return 1;
    if (b === ISOLATE) return -1;
    return sizeOf.get(b)! - sizeOf.get(a)! || a - b;
  });
  const remap = new Map<number, number>();
  keys.forEach((k, i) => remap.set(k, i));
  const community = new Int32Array(n);
  for (let i = 0; i < n; i++) community[i] = remap.get(raw[i])!;
  const K = keys.length;
  const sizes = keys.map((k) => sizeOf.get(k)!);

  // ---- 3. centroids and caps ------------------------------------------------
  // tiny graphs stay as a compact cluster instead of spreading over the globe
  const spacing = Math.min(MAX_SPACING, Math.sqrt((4 * Math.PI * fillFraction(n)) / n));
  const fill = (spacing * spacing * n) / (4 * Math.PI);
  const cap = new Float64Array(K);
  for (let c = 0; c < K; c++) {
    const f = Math.min(0.9, (fill * sizes[c]) / n);
    cap[c] = Math.max(Math.acos(1 - 2 * f), spacing * 0.5);
  }

  const lattice = fibonacciSphere(K);
  const order = farthestPointOrder(lattice, K);
  const cen = new Float64Array(K * 3);
  for (let c = 0; c < K; c++) {
    const p = order[c];
    cen[3 * c] = lattice[3 * p];
    cen[3 * c + 1] = lattice[3 * p + 1];
    cen[3 * c + 2] = lattice[3 * p + 2];
  }

  if (K > 1) {
    // inter-community edge weights
    const link = new Map<number, number>();
    const m = edges.length >> 1;
    for (let e = 0; e < m; e++) {
      const a = edges[2 * e];
      const b = edges[2 * e + 1];
      if (a === b || a < 0 || b < 0 || a >= n || b >= n) continue;
      const ca = community[a];
      const cb = community[b];
      if (ca === cb) continue;
      const key = ca < cb ? ca * K + cb : cb * K + ca;
      link.set(key, (link.get(key) ?? 0) + 1);
    }
    const links = [...link.entries()].map(([key, w]) => [Math.floor(key / K), key % K, w] as const);

    const gap = spacing * 0.6;
    let maxCap = 0;
    for (let c = 0; c < K; c++) maxCap = Math.max(maxCap, cap[c]);
    const cosSkip = Math.cos(Math.min(Math.PI, 2 * maxCap + gap));
    const area = new Float64Array(K);
    for (let c = 0; c < K; c++) area[c] = 1 - Math.cos(cap[c]);
    const disp = new Float64Array(K * 3);
    const iters = K > 400 ? 24 : K > 120 ? 48 : 90;

    for (let it = 0; it < iters; it++) {
      disp.fill(0);
      const temp = 1 - it / iters;
      // separation: caps must not overlap
      for (let i = 0; i < K; i++) {
        const ix = cen[3 * i];
        const iy = cen[3 * i + 1];
        const iz = cen[3 * i + 2];
        for (let j = i + 1; j < K; j++) {
          const jx = cen[3 * j];
          const jy = cen[3 * j + 1];
          const jz = cen[3 * j + 2];
          const dot = ix * jx + iy * jy + iz * jz;
          if (dot < cosSkip) continue;
          const delta = Math.acos(clamp(dot, -1, 1));
          const need = cap[i] + cap[j] + gap;
          if (delta >= need) continue;
          const overlap = need - delta;
          const wi = area[j] / (area[i] + area[j]);
          const wj = 1 - wi;
          // tangent at i pointing away from j: i*(i.j) - j
          let tx = ix * dot - jx;
          let ty = iy * dot - jy;
          let tz = iz * dot - jz;
          let tl = Math.hypot(tx, ty, tz);
          if (tl < 1e-9) {
            tx = rng() - 0.5;
            ty = rng() - 0.5;
            tz = rng() - 0.5;
            tl = Math.hypot(tx, ty, tz) || 1;
          }
          const si = (overlap * wi * 0.5) / tl;
          disp[3 * i] += tx * si;
          disp[3 * i + 1] += ty * si;
          disp[3 * i + 2] += tz * si;
          // tangent at j pointing away from i: j*(i.j) - i
          let ux = jx * dot - ix;
          let uy = jy * dot - iy;
          let uz = jz * dot - iz;
          const ul = Math.hypot(ux, uy, uz) || 1;
          ux /= ul;
          uy /= ul;
          uz /= ul;
          const sj = overlap * wj * 0.5;
          disp[3 * j] += ux * sj;
          disp[3 * j + 1] += uy * sj;
          disp[3 * j + 2] += uz * sj;
        }
      }
      // attraction: linked communities drift together (gently, cooling)
      for (const [a, b, w] of links) {
        const ax = cen[3 * a];
        const ay = cen[3 * a + 1];
        const az = cen[3 * a + 2];
        const bx = cen[3 * b];
        const by = cen[3 * b + 1];
        const bz = cen[3 * b + 2];
        const dot = ax * bx + ay * by + az * bz;
        const delta = Math.acos(clamp(dot, -1, 1));
        const need = cap[a] + cap[b] + gap;
        if (delta <= need) continue;
        const pull = Math.min(delta - need, 0.4) * 0.25 * Math.min(1, Math.sqrt(w) / 2) * temp;
        // towards b at a: b - a*(a.b)
        let tx = bx - ax * dot;
        let ty = by - ay * dot;
        let tz = bz - az * dot;
        let tl = Math.hypot(tx, ty, tz) || 1;
        const wa = area[b] / (area[a] + area[b]);
        disp[3 * a] += (tx / tl) * pull * wa;
        disp[3 * a + 1] += (ty / tl) * pull * wa;
        disp[3 * a + 2] += (tz / tl) * pull * wa;
        tx = ax - bx * dot;
        ty = ay - by * dot;
        tz = az - bz * dot;
        tl = Math.hypot(tx, ty, tz) || 1;
        disp[3 * b] += (tx / tl) * pull * (1 - wa);
        disp[3 * b + 1] += (ty / tl) * pull * (1 - wa);
        disp[3 * b + 2] += (tz / tl) * pull * (1 - wa);
      }
      for (let c = 0; c < K; c++) {
        let x = cen[3 * c] + disp[3 * c];
        let y = cen[3 * c + 1] + disp[3 * c + 1];
        let z = cen[3 * c + 2] + disp[3 * c + 2];
        const l = Math.hypot(x, y, z) || 1;
        x /= l;
        y /= l;
        z /= l;
        cen[3 * c] = x;
        cen[3 * c + 1] = y;
        cen[3 * c + 2] = z;
      }
    }
  }

  // ---- 4. members on a sunflower spiral around their centroid ---------------
  const members: number[][] = Array.from({ length: K }, () => []);
  for (let i = 0; i < n; i++) members[community[i]].push(i);
  for (let c = 0; c < K; c++) {
    const list = members[c];
    list.sort((a, b) => degree[b] - degree[a] || a - b);
    const cx = cen[3 * c];
    const cy = cen[3 * c + 1];
    const cz = cen[3 * c + 2];
    const [ux, uy, uz, vx, vy, vz] = tangentBasis(cx, cy, cz);
    const spin = rng() * Math.PI * 2;
    const m = list.length;
    for (let j = 0; j < m; j++) {
      const r = m === 1 ? 0 : cap[c] * Math.sqrt((j + 0.5) / m);
      const phi = spin + j * GOLDEN_ANGLE;
      const tx = Math.cos(phi) * ux + Math.sin(phi) * vx;
      const ty = Math.cos(phi) * uy + Math.sin(phi) * vy;
      const tz = Math.cos(phi) * uz + Math.sin(phi) * vz;
      const cr = Math.cos(r);
      const sr = Math.sin(r);
      const i = list[j];
      positions[3 * i] = cx * cr + tx * sr;
      positions[3 * i + 1] = cy * cr + ty * sr;
      positions[3 * i + 2] = cz * cr + tz * sr;
    }
  }

  // ---- 5. constrained force relaxation on the sphere ------------------------
  relaxOnSphere(positions, adj, degree, spacing, options.iterations ?? (n > 1200 ? 36 : n > 300 ? 56 : 80), rng);

  // ---- 6. largest community faces the camera --------------------------------
  let sx = 0;
  let sy = 0;
  let sz = 0;
  for (const i of members[0]) {
    sx += positions[3 * i];
    sy += positions[3 * i + 1];
    sz += positions[3 * i + 2];
  }
  const sl = Math.hypot(sx, sy, sz);
  if (sl > 1e-6) rotateToFace(positions, [sx / sl, sy / sl, sz / sl], front);

  return { positions, degree, community, communityCount: K, spacing };
}

/**
 * Springs along edges + short-range repulsion, both tangential in effect
 * because every step is renormalised onto the sphere. Uses a uniform 3D grid
 * (counting sort) for neighbour queries, so each iteration is ~O(n + m).
 */
function relaxOnSphere(
  pos: Float32Array,
  adj: Adjacency,
  degree: Int32Array,
  spacing: number,
  iterations: number,
  rng: () => number,
) {
  const n = degree.length;
  const ideal = spacing * 0.85;
  const repel = spacing * 1.1;
  const repel2 = repel * repel;
  const cell = repel;
  const G = clamp(Math.ceil(2.0001 / cell), 1, 64);
  const cellSize = 2.0001 / G;
  const cells = G * G * G;
  const cellStart = new Int32Array(cells + 1);
  const cellOf = new Int32Array(n);
  const sorted = new Int32Array(n);
  const disp = new Float32Array(n * 3);
  const invSqrtDeg = new Float32Array(n);
  for (let i = 0; i < n; i++) invSqrtDeg[i] = 1 / Math.sqrt(Math.max(1, degree[i]));
  const { offsets, neighbors } = adj;

  const cellCoord = (v: number) => clamp(Math.floor((v + 1.00005) / cellSize), 0, G - 1);

  for (let it = 0; it < iterations; it++) {
    const temp = 1 - it / iterations;
    disp.fill(0);

    // springs (each undirected edge appears twice in CSR; handle when i < j)
    for (let i = 0; i < n; i++) {
      const ix = pos[3 * i];
      const iy = pos[3 * i + 1];
      const iz = pos[3 * i + 2];
      for (let q = offsets[i]; q < offsets[i + 1]; q++) {
        const j = neighbors[q];
        if (j < i) continue;
        const dx = pos[3 * j] - ix;
        const dy = pos[3 * j + 1] - iy;
        const dz = pos[3 * j + 2] - iz;
        const d = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (d <= ideal || d < 1e-9) continue;
        const f = (0.32 * (d - ideal)) / d;
        const fi = f * invSqrtDeg[i];
        const fj = f * invSqrtDeg[j];
        disp[3 * i] += dx * fi;
        disp[3 * i + 1] += dy * fi;
        disp[3 * i + 2] += dz * fi;
        disp[3 * j] -= dx * fj;
        disp[3 * j + 1] -= dy * fj;
        disp[3 * j + 2] -= dz * fj;
      }
    }

    // spatial grid (counting sort by cell)
    cellStart.fill(0);
    for (let i = 0; i < n; i++) {
      const c =
        cellCoord(pos[3 * i]) + G * (cellCoord(pos[3 * i + 1]) + G * cellCoord(pos[3 * i + 2]));
      cellOf[i] = c;
      cellStart[c + 1]++;
    }
    for (let c = 0; c < cells; c++) cellStart[c + 1] += cellStart[c];
    {
      const fillPtr = cellStart.slice(0, cells);
      for (let i = 0; i < n; i++) sorted[fillPtr[cellOf[i]]++] = i;
    }

    // repulsion between nearby nodes
    for (let i = 0; i < n; i++) {
      const ix = pos[3 * i];
      const iy = pos[3 * i + 1];
      const iz = pos[3 * i + 2];
      const cx = cellCoord(ix);
      const cy = cellCoord(iy);
      const cz = cellCoord(iz);
      for (let oz = -1; oz <= 1; oz++) {
        const zz = cz + oz;
        if (zz < 0 || zz >= G) continue;
        for (let oy = -1; oy <= 1; oy++) {
          const yy = cy + oy;
          if (yy < 0 || yy >= G) continue;
          for (let ox = -1; ox <= 1; ox++) {
            const xx = cx + ox;
            if (xx < 0 || xx >= G) continue;
            const c = xx + G * (yy + G * zz);
            for (let k = cellStart[c]; k < cellStart[c + 1]; k++) {
              const j = sorted[k];
              if (j <= i) continue;
              let dx = ix - pos[3 * j];
              let dy = iy - pos[3 * j + 1];
              let dz = iz - pos[3 * j + 2];
              let d2 = dx * dx + dy * dy + dz * dz;
              if (d2 >= repel2) continue;
              if (d2 < 1e-12) {
                dx = (rng() - 0.5) * 1e-3;
                dy = (rng() - 0.5) * 1e-3;
                dz = (rng() - 0.5) * 1e-3;
                d2 = dx * dx + dy * dy + dz * dz;
              }
              const d = Math.sqrt(d2);
              const f = (0.7 * (repel - d)) / d;
              disp[3 * i] += dx * f;
              disp[3 * i + 1] += dy * f;
              disp[3 * i + 2] += dz * f;
              disp[3 * j] -= dx * f;
              disp[3 * j + 1] -= dy * f;
              disp[3 * j + 2] -= dz * f;
            }
          }
        }
      }
    }

    // apply with a cooling step cap, then back onto the sphere
    const maxStep = spacing * (0.06 + 0.5 * temp);
    for (let i = 0; i < n; i++) {
      let dx = disp[3 * i];
      let dy = disp[3 * i + 1];
      let dz = disp[3 * i + 2];
      const l = Math.sqrt(dx * dx + dy * dy + dz * dz);
      if (l > maxStep) {
        const s = maxStep / l;
        dx *= s;
        dy *= s;
        dz *= s;
      }
      const x = pos[3 * i] + dx;
      const y = pos[3 * i + 1] + dy;
      const z = pos[3 * i + 2] + dz;
      const pl = Math.sqrt(x * x + y * y + z * z) || 1;
      pos[3 * i] = x / pl;
      pos[3 * i + 1] = y / pl;
      pos[3 * i + 2] = z / pl;
    }
  }
}
