/** Small SVG geometry helpers shared by the chart plots. */

export type Tip = 'top' | 'bottom' | 'left' | 'right';

const r2 = (n: number) => Math.round(n * 100) / 100;

/**
 * A bar with a 4px rounded data-end (`tip`) and square corners at the baseline.
 * (l, t) is the top-left corner; w/h are positive.
 */
export function barPath(l: number, t: number, w: number, h: number, tip: Tip, radius = 4): string {
  if (w <= 0 || h <= 0) return '';
  const along = tip === 'top' || tip === 'bottom' ? h : w;
  const across = tip === 'top' || tip === 'bottom' ? w : h;
  const r = Math.max(0, Math.min(radius, across / 2, along));
  const R = r2(r);
  const L = r2(l);
  const T = r2(t);
  const Rt = r2(l + w);
  const B = r2(t + h);
  switch (tip) {
    case 'top':
      return `M${L},${B}V${r2(t + r)}A${R},${R} 0 0 1 ${r2(l + r)},${T}H${r2(l + w - r)}A${R},${R} 0 0 1 ${Rt},${r2(t + r)}V${B}Z`;
    case 'bottom':
      return `M${L},${T}H${Rt}V${r2(t + h - r)}A${R},${R} 0 0 1 ${r2(l + w - r)},${B}H${r2(l + r)}A${R},${R} 0 0 1 ${L},${r2(t + h - r)}Z`;
    case 'right':
      return `M${L},${T}H${r2(l + w - r)}A${R},${R} 0 0 1 ${Rt},${r2(t + r)}V${r2(t + h - r)}A${R},${R} 0 0 1 ${r2(l + w - r)},${B}H${L}Z`;
    case 'left':
      return `M${Rt},${T}V${B}H${r2(l + r)}A${R},${R} 0 0 1 ${L},${r2(t + h - r)}V${r2(t + r)}A${R},${R} 0 0 1 ${r2(l + r)},${T}Z`;
  }
}

/** Donut segment between radii r0 < r1 from angle a0 to a1 (radians, 0 = 12 o'clock, clockwise). */
export function arcPath(cx: number, cy: number, r0: number, r1: number, a0: number, a1: number): string {
  const sweep = a1 - a0;
  if (sweep <= 0) return '';
  if (sweep >= Math.PI * 2 - 1e-6) {
    // Full ring: two half arcs per radius.
    return [
      `M${r2(cx)},${r2(cy - r1)}`,
      `A${r1},${r1} 0 1 1 ${r2(cx)},${r2(cy + r1)}`,
      `A${r1},${r1} 0 1 1 ${r2(cx)},${r2(cy - r1)}`,
      `M${r2(cx)},${r2(cy - r0)}`,
      `A${r0},${r0} 0 1 0 ${r2(cx)},${r2(cy + r0)}`,
      `A${r0},${r0} 0 1 0 ${r2(cx)},${r2(cy - r0)}Z`,
    ].join('');
  }
  const pt = (r: number, a: number) => `${r2(cx + r * Math.sin(a))},${r2(cy - r * Math.cos(a))}`;
  const large = sweep > Math.PI ? 1 : 0;
  return `M${pt(r1, a0)}A${r1},${r1} 0 ${large} 1 ${pt(r1, a1)}L${pt(r0, a1)}A${r0},${r0} 0 ${large} 0 ${pt(r0, a0)}Z`;
}

export type Scale = ((v: number) => number) & { domain: [number, number]; range: [number, number] };

export function linearScale(d0: number, d1: number, r0: number, r1: number): Scale {
  const span = d1 - d0 || 1;
  const fn = ((v: number) => r0 + ((v - d0) / span) * (r1 - r0)) as Scale;
  fn.domain = [d0, d1];
  fn.range = [r0, r1];
  return fn;
}

export function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

/** Path through points; `breakAt(prev, next)` splits the line (missing values). */
export function polyline(points: Array<{ x: number; y: number }>, breakAt?: (i: number) => boolean): string {
  let d = '';
  points.forEach((p, i) => {
    const cmd = i === 0 || breakAt?.(i) ? 'M' : 'L';
    d += `${cmd}${r2(p.x)},${r2(p.y)}`;
  });
  return d;
}

/**
 * Spreads label positions so neighbours sit at least `gap` apart inside
 * [lo, hi]. Returns the adjusted positions in the input order.
 */
export function spreadLabels(ys: number[], gap: number, lo: number, hi: number): number[] {
  const order = ys.map((y, i) => ({ y, i })).sort((a, b) => a.y - b.y);
  const out = order.map((o) => o.y);
  for (let pass = 0; pass < 4; pass++) {
    for (let k = 1; k < out.length; k++) if (out[k] - out[k - 1] < gap) out[k] = out[k - 1] + gap;
    if (out.length && out[out.length - 1] > hi) out[out.length - 1] = hi;
    for (let k = out.length - 2; k >= 0; k--) if (out[k + 1] - out[k] < gap) out[k] = out[k + 1] - gap;
    if (out.length && out[0] < lo) out[0] = lo;
  }
  const result = new Array<number>(ys.length);
  order.forEach((o, k) => {
    result[o.i] = out[k];
  });
  return result;
}
