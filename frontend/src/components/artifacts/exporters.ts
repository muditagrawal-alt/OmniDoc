import { cssVar } from '../../lib/theme';
import type { TableModel } from './normalize';

export function slugify(title: string): string {
  const s = title
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[^\w\s-]/g, '')
    .trim()
    .replace(/[\s_-]+/g, '-')
    .slice(0, 60);
  return s || 'chart';
}

export function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function csvCell(v: string | number | null): string {
  if (v === null) return '';
  const s = String(v);
  // Neutralise spreadsheet formula injection from untrusted labels.
  const safe = typeof v === 'string' && /^[=+\-@\t\r]/.test(s) ? `'${s}` : s;
  return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

export function tableToCsv(table: TableModel): string {
  const lines = [table.columns.map(csvCell).join(',')];
  table.rows.forEach((row) => lines.push(row.map((c) => csvCell(c)).join(',')));
  return `﻿${lines.join('\r\n')}\r\n`;
}

/* ------------------------------------------------------------------- SVG */

const STYLE_PROPS = [
  'fill',
  'fill-opacity',
  'stroke',
  'stroke-width',
  'stroke-opacity',
  'stroke-linecap',
  'stroke-linejoin',
  'opacity',
  'font-family',
  'font-size',
  'font-weight',
  'letter-spacing',
  'text-anchor',
  'dominant-baseline',
  'font-variant-numeric',
] as const;

export interface SvgLegendItem {
  label: string;
  color: string;
  shape: 'rect' | 'line' | 'dot';
}

function resolveColor(value: string): string {
  const m = /^var\((--[\w-]+)\)$/.exec(value.trim());
  return m ? cssVar(m[1]) || value : value;
}

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c);
}

/**
 * Serialises a live chart SVG into a standalone file: computed styles are
 * inlined (CSS variables resolved for the current theme), interaction layers
 * are dropped, and the title + legend are drawn above the plot.
 */
export function chartSvgString(svg: SVGSVGElement, opts: { title: string; legend: SvgLegendItem[]; caption?: string }): string {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  const src = [svg, ...Array.from(svg.querySelectorAll('*'))];
  const dst = [clone, ...Array.from(clone.querySelectorAll('*'))];
  src.forEach((el, i) => {
    const target = dst[i];
    if (!target || !(el instanceof SVGElement)) return;
    const cs = getComputedStyle(el);
    const decl = STYLE_PROPS.map((p) => {
      const v = cs.getPropertyValue(p);
      return v ? `${p}:${v}` : '';
    })
      .filter(Boolean)
      .join(';');
    target.setAttribute('style', decl);
    target.removeAttribute('class');
  });
  clone.querySelectorAll('[data-export="skip"]').forEach((n) => n.remove());

  const width = svg.viewBox.baseVal?.width || svg.clientWidth;
  const height = svg.viewBox.baseVal?.height || svg.clientHeight;
  const ui = cssVar('--font-ui') || 'sans-serif';
  const text = cssVar('--text') || '#1c1b19';
  const text2 = cssVar('--text-2') || '#57544d';
  const surface = cssVar('--surface') || '#ffffff';
  const pad = 16;

  let legendSvg = '';
  let lx = pad;
  const ly = pad + 34;
  const ctx = document.createElement('canvas').getContext('2d');
  if (ctx) ctx.font = `400 12px ${ui}`;
  opts.legend.forEach((item) => {
    const color = resolveColor(item.color);
    const swatch =
      item.shape === 'line'
        ? `<line x1="${lx}" y1="${ly}" x2="${lx + 14}" y2="${ly}" stroke="${color}" stroke-width="2" stroke-linecap="round"/>`
        : item.shape === 'dot'
          ? `<circle cx="${lx + 5}" cy="${ly}" r="4" fill="${color}"/>`
          : `<rect x="${lx}" y="${ly - 5}" width="10" height="10" rx="2" fill="${color}"/>`;
    const sw = item.shape === 'line' ? 14 : 10;
    legendSvg += `${swatch}<text x="${lx + sw + 6}" y="${ly}" dominant-baseline="central" font-family="${esc(ui)}" font-size="12" fill="${text2}">${esc(item.label)}</text>`;
    lx += sw + 6 + (ctx ? ctx.measureText(item.label).width : item.label.length * 7) + 18;
  });

  const headH = opts.legend.length ? 62 : 44;
  const capH = opts.caption ? 34 : 0;
  const totalW = width + pad * 2;
  const totalH = height + headH + capH + pad;
  const inner = new XMLSerializer().serializeToString(clone).replace(/^<svg[^>]*>/, '').replace(/<\/svg>$/, '');

  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    `<svg xmlns="http://www.w3.org/2000/svg" width="${totalW}" height="${totalH}" viewBox="0 0 ${totalW} ${totalH}">`,
    `<rect width="100%" height="100%" fill="${surface}"/>`,
    `<text x="${pad}" y="${pad + 12}" font-family="${esc(ui)}" font-size="15" font-weight="600" fill="${text}">${esc(opts.title)}</text>`,
    legendSvg,
    `<g transform="translate(${pad} ${headH})">${inner}</g>`,
    opts.caption
      ? `<text x="${pad}" y="${headH + height + 22}" font-family="${esc(ui)}" font-size="12" fill="${text2}">${esc(opts.caption)}</text>`
      : '',
    '</svg>',
  ].join('');
}
