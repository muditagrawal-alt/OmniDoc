import { useId } from 'react';

/*
 * The OmniDoc mark: a circle (the answer) overlapping a page (the document). Where they overlap,
 * in the accent colour, is the evidence an answer stands on. Built from two primitives on a
 * 24-unit grid so it holds at 16 px, and it works in one colour (the overlap knocked out).
 * Inside a button or link, the circle slides a little further onto the page on hover.
 */
export function BrandMark({ size = 22, mono = false }: { size?: number; mono?: boolean }) {
  const clip = `omnidoc-page-${useId().replace(/:/g, '')}`;
  return (
    <svg className="brand-mark" width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <defs>
        <clipPath id={clip}>
          <rect x="10" y="3" width="11" height="15" rx="2.6" />
        </clipPath>
      </defs>
      <rect className="brand-mark-page" x="10" y="3" width="11" height="15" rx="2.6" fill="currentColor" />
      <g className="brand-mark-orb">
        <circle cx="9" cy="14" r="7" fill="currentColor" />
        <circle cx="9" cy="14" r="7" fill={mono ? 'var(--bg)' : 'var(--accent)'} clipPath={`url(#${clip})`} />
      </g>
    </svg>
  );
}
