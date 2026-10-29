/** OmniDoc mark: a page with a folded corner and one highlighted line, the evidence an answer cites. */
export function BrandMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M6 2.75h8.2l4.55 4.55V20.1a1.15 1.15 0 0 1-1.15 1.15H6.4A1.15 1.15 0 0 1 5.25 20.1V3.9" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
      <path d="M5.25 3.9c0-.64.51-1.15 1.15-1.15M14 2.9v3.6c0 .55.45 1 1 1h3.6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      <rect x="8" y="11.4" width="8.6" height="2.9" rx="0.7" fill="var(--accent)" />
      <rect x="8" y="16.2" width="5.6" height="1.6" rx="0.8" fill="currentColor" opacity="0.45" />
    </svg>
  );
}
