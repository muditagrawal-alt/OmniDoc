---
name: sota-design-system
description: >-
  Systematic design token architecture, typography, density, surfaces, and theme engineering.
  Derives visual direction from product requirements, brand identity, content structure, and existing systems
  rather than default templates. Activate when defining tokens, theme architectures (OKLCH/HSL), component
  libraries, or systematic UI foundations.
---

# Systematic Design System Architecture

## When to Use
Activate this skill whenever:
- Establishing a project's visual direction, design tokens, or theme architecture.
- Creating or auditing a reusable component library.
- Implementing accessible light and dark themes using semantic tokens.
- Defining typography hierarchies, spacing grids, and surface elevations tailored to the product domain.
- Auditing existing projects to ensure design-system reuse rather than introducing redundant styles.

---

## 1. Process for Deriving Visual Direction
Never start by copy-pasting a generic dark-blue SaaS dashboard or predetermined color palette. Design choices must be derived methodically:

1. **Analyze Product Purpose & Domain**:
   - Financial, medical, and developer tools prioritize high information density, low eye fatigue, and unambiguous status indicators.
   - Editorial, consumer, and creative products prioritize narrative flow, expressive typography, and atmospheric pacing.
2. **Understand the Target Audience**:
   - Assess lighting environments (e.g. bright office vs. dark trading room), accessibility requirements (WCAG AAA vs. AA), and user technical familiarity.
3. **Audit and Reuse Existing Systems First**:
   - Before introducing new primitives, inspect the existing codebase for established CSS variables, Tailwind configurations, or component libraries.
   - Extend existing conventions rather than imposing a disjointed visual layer.
4. **Forbid Generic SaaS Tropes**:
   - Do not default to electric blue accents, dark-purple backgrounds, and frosted glass cards unless the product brief specifically demands that exact aesthetic.

---

## 2. Semantic Token Architecture
Separate primitive values from semantic intent. Primitives hold raw color spaces; semantic tokens express roles that adapt across light and dark modes.

### Color Spaces (OKLCH & HSL)
- **OKLCH** is preferred for modern CSS because it delivers perceptually uniform lightness and chroma across hues, avoiding muddy transitions and inconsistent contrast.
- **HSL** remains supported for legacy browser environments.

```css
/* tokens.css - Semantic Token Structure */
:root {
  /* Primitive Scale (OKLCH) */
  --color-neutral-50: oklch(0.98 0.005 250);
  --color-neutral-100: oklch(0.95 0.008 250);
  --color-neutral-200: oklch(0.90 0.010 250);
  --color-neutral-800: oklch(0.25 0.015 250);
  --color-neutral-900: oklch(0.18 0.018 250);
  --color-neutral-950: oklch(0.12 0.020 250);

  --color-brand-light: oklch(0.55 0.20 240);
  --color-brand-dark: oklch(0.68 0.18 240);

  /* Light Theme Semantic Mapping (Default) */
  --bg-canvas: var(--color-neutral-50);
  --bg-surface: oklch(1 0 0);
  --bg-surface-raised: var(--color-neutral-100);
  --border-subtle: var(--color-neutral-200);
  --border-strong: var(--color-neutral-800);

  --text-primary: var(--color-neutral-950);
  --text-secondary: var(--color-neutral-800);
  --text-muted: oklch(0.50 0.015 250);

  --color-accent: var(--color-brand-light);
  --color-accent-contrast: oklch(0.99 0 0);

  --color-status-success: oklch(0.62 0.17 145);
  --color-status-warning: oklch(0.75 0.16 75);
  --color-status-error: oklch(0.58 0.22 25);
}

/* Dark Theme Overrides */
[data-theme="dark"],
.dark {
  --bg-canvas: var(--color-neutral-950);
  --bg-surface: var(--color-neutral-900);
  --bg-surface-raised: var(--color-neutral-800);
  --border-subtle: oklch(0.28 0.015 250);
  --border-strong: oklch(0.45 0.015 250);

  --text-primary: oklch(0.96 0.005 250);
  --text-secondary: oklch(0.78 0.010 250);
  --text-muted: oklch(0.55 0.012 250);

  --color-accent: var(--color-brand-dark);
  --color-accent-contrast: oklch(0.12 0.020 250);
}
```

---

## 3. Typography: Contextual Selection & Fluid Scales
Typography must be chosen to match content hierarchy, not forced to a single font family or fixed ratio.

1. **Font Family Selection**:
   - Data-heavy dashboards: High legibility grotesques or system fonts with tabular figures (`font-variant-numeric: tabular-nums`).
   - Technical / Code: Readable monospaced fonts with distinct glyphs (`0`, `O`, `l`, `1`).
   - Editorial / Content: Thoughtful serif or expressive sans pairings that match editorial tone.
2. **Modular Ratio Derived from Context**:
   - Dense analytical interfaces: Minor Second (`1.067`) or Major Second (`1.125`) to conserve vertical space.
   - Balanced general applications: Minor Third (`1.200`) or Major Third (`1.250`).
   - Expressive / Marketing sites: Perfect Fourth (`1.333`) or Golden Ratio (`1.618`).

```css
:root {
  /* Fluid typographic scale adapting between mobile and desktop viewports */
  --font-text: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, "Cascadia Code", monospace;

  --text-xs: clamp(0.75rem, 0.70rem + 0.2vw, 0.8125rem);
  --text-sm: clamp(0.875rem, 0.82rem + 0.25vw, 0.9375rem);
  --text-base: clamp(1rem, 0.95rem + 0.3vw, 1.0625rem);
  --text-lg: clamp(1.125rem, 1.05rem + 0.4vw, 1.25rem);
  --text-xl: clamp(1.25rem, 1.15rem + 0.6vw, 1.5rem);
  --text-2xl: clamp(1.5rem, 1.35rem + 0.9vw, 1.875rem);
  --text-3xl: clamp(1.875rem, 1.65rem + 1.3vw, 2.375rem);
}
```

---

## 4. Surfaces, Elevation & Deliberate Styling
Solid surfaces and clean border contrast are the standard foundation.

- **Solid Surfaces First**: Rely on clean background values (`--bg-surface`, `--bg-surface-raised`) and subtle borders (`--border-subtle`) for visual structure.
- **Glassmorphism as an Exception**: Use backdrop blur and translucent surfaces ONLY when preserving background spatial continuity (e.g. fixed sticky headers, floating command palettes, or contextual overlays). Never make all cards glassmorphic by default.
- **Gradients as Deliberate Accents**: Use gradients selectively for primary calls-to-action or hero focal points. Never use gradient backgrounds across standard operational panels.

```css
/* Standard Surface (Default) */
.surface-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  box-shadow: 0 1px 3px oklch(0 0 0 / 0.06);
}

/* Deliberate Floating Overlay (Optional, contextual) */
.surface-overlay {
  background: oklch(from var(--bg-surface) l c h / 0.85);
  backdrop-filter: blur(12px);
  border: 1px solid var(--border-subtle);
  box-shadow: 0 12px 32px oklch(0 0 0 / 0.15);
}
```

---

## 5. Component Library Architecture & Reuse
1. **Audit First**: Check if `@radix-ui`, `shadcn/ui`, or existing custom primitives are already implemented.
2. **Encapsulate Behavior, Expose Tokens**: Primitives should consume semantic tokens so themes apply automatically without ad-hoc utility overriding.
3. **Accessibility Baseline**:
   - Visible `:focus-visible` styles with sufficient contrast (`ring-2 ring-offset-2`).
   - Screen-reader text (`sr-only`) on icon-only interactive controls.
   - ARIA roles and keyboard management for modals, dropdowns, and comboboxes.

---

## Anti-Patterns
- ❌ Never apply a generic dark-blue SaaS dashboard template unless specifically requested by the product brief.
- ❌ Never treat glassmorphism, blur effects, or heavy gradients as default card styling.
- ❌ Never hardcode static hex/rgb color values in components; always consume semantic tokens.
- ❌ Never default blindly to Inter and a 1.250 scale without evaluating content density.
- ❌ Never reinvent existing component primitives when the repository already has an established design system.
