/** OmniDoc mark: a ring (the globe of linked knowledge) crossed by a highlighter stroke. */
export function BrandMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="4.5" y="12.4" width="15" height="4.2" rx="2.1" fill="var(--accent)" opacity="0.85" />
      <circle cx="12" cy="12" r="8.4" stroke="currentColor" strokeWidth="1.8" />
      <path d="M3.9 10.2c2.6 1.1 5.3 1.6 8.1 1.6s5.5-.5 8.1-1.6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" opacity="0.55" />
    </svg>
  );
}
