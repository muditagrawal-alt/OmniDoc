---
name: sota-tailwind-v4
description: >-
  Tailwind CSS v4 patterns, CSS-first @theme configuration, container queries, and styling best practices.
  Respects existing project styling systems and provides accurate dark mode and utility syntax.
  Activate when configuring or styling components with Tailwind v4 in repositories that use Tailwind.
---

# Tailwind CSS v4 Engineering Patterns

## When to Use
Activate this skill whenever:
- Configuring or styling UI components with Tailwind CSS v4 in repositories that already use or specifically request Tailwind.
- Setting up `@theme` design tokens in CSS files.
- Implementing container queries (`@container`), custom variants, or modern CSS features via Tailwind.
- Managing dark mode transitions via `@custom-variant`.
- Migrating existing Tailwind v3 codebases to Tailwind v4.

---

## 1. Respect Existing Styling Systems
**Never force Tailwind CSS on a repository that uses another styling system.**
- If a project uses CSS Modules, Vanilla CSS, Sass, Styled-Components, or Emotion, adhere strictly to that repository's established architecture.
- Only introduce or configure Tailwind if the repository already includes Tailwind in `package.json` or the user explicitly asks to adopt it.

---

## 2. Configuration in Tailwind v4

### CSS-First `@theme` (Preferred for New Work)
Tailwind v4 replaces `tailwind.config.js` with direct CSS configuration using `@import "tailwindcss";` and `@theme`:

```css
/* app/globals.css */
@import "tailwindcss";

@theme {
  --color-primary: oklch(0.55 0.20 240);
  --color-surface: oklch(0.98 0.005 250);
  --color-surface-raised: oklch(1 0 0);
  --color-border-subtle: oklch(0.90 0.010 250);

  --font-sans: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, "Cascadia Code", monospace;

  --breakpoint-xs: 24rem;
  --breakpoint-sm: 40rem;
  --breakpoint-md: 48rem;
  --breakpoint-lg: 64rem;
  --breakpoint-xl: 80rem;
}
```

### Legacy `@config` Directive (Supported for Migrations)
For existing projects migrating from v3, Tailwind v4 continues to support legacy JavaScript config files via the `@config` directive:

```css
@import "tailwindcss";
@config "../../tailwind.config.js";
```
Do not force disruptive refactors to `@theme` if a team or legacy project relies on existing plugins or dynamic JS configuration in `tailwind.config.js`.

---

## 3. Dark Mode Architecture in v4

### Default Media Query Mode
By default, Tailwind v4 links `dark:` utilities directly to the operating system's preference:
`@media (prefers-color-scheme: dark)`.

### Class or Data-Attribute Switching
When manual theme toggling via class (`.dark`) or attribute (`data-theme="dark"`, e.g. with `next-themes`) is required, you must define a `@custom-variant` in your CSS:

```css
/* Enable class-based switching: <html class="dark"> */
@custom-variant dark (&:where(.dark, .dark *));

/* OR enable data-attribute switching: <html data-theme="dark"> */
@custom-variant dark (&:where([data-theme="dark"], [data-theme="dark"] *));
```

```html
<!-- Components then switch reliably across themes -->
<div class="bg-surface text-neutral-900 dark:bg-surface-dark dark:text-neutral-100">
  Content responds to theme selector
</div>
```

---

## 4. Syntax Corrections: No `hover:(...)` Shorthand
Tailwind CSS does not support arbitrary parentheses grouping like `hover:(...)` or `focus:(...)` in official releases. Always write standard, explicit variant prefixes:

```html
<!-- ❌ INCORRECT (Unsupported shorthand syntax) -->
<button class="hover:(bg-primary text-white scale-105 shadow-md)">
  Submit
</button>

<!-- ✅ CORRECT (Valid Tailwind v4 utility syntax) -->
<button class="transition-transform duration-150 hover:bg-primary hover:text-white hover:scale-[1.02] hover:shadow-md">
  Submit
</button>
```

---

## 5. Technical Precision with Units (Allowing `px`)
Do not enforce a dogmatic ban on pixel units (`px`). Use the appropriate unit for the technical requirement:
- **Use `px` where technically appropriate**:
  - 1px borders and hairline dividers (`border-b`, `border-t`, `h-[1px]`).
  - Crisp raster image alignment and fine shadow offsets.
  - Concrete design token definitions (e.g. `--border-width: 1px`).
- **Use `rem` / Tailwind spacing tokens** for layouts, grid tracks, container paddings, margins, and fluid typography.

```html
<!-- Hairline divider with 1px border is technically correct -->
<div class="border-b border-border-subtle p-4">
  <h2 class="text-base font-medium">Section Header</h2>
</div>
```

---

## 6. Modern v4 Features

### Built-in Container Queries
```html
<div class="@container">
  <div class="grid grid-cols-1 @sm:grid-cols-2 @lg:grid-cols-4 gap-4">
    <!-- Adapts based on parent container width, not viewport -->
  </div>
</div>
```

### Custom Utilities with `@utility`
```css
@utility content-auto {
  content-visibility: auto;
}
```

---

## Anti-Patterns
- ❌ Never use unsupported variant-group syntax like `hover:(...)` or `focus:(...)`.
- ❌ Never assume Tailwind v4 toggles dark mode via `.dark` class without configuring `@custom-variant`.
- ❌ Never dogmatically ban `px` units when 1px borders, dividers, or raster alignments require them.
- ❌ Never force Tailwind CSS into repositories that use CSS Modules, Vanilla CSS, or other styling systems.
- ❌ Never delete or break `@config` in projects migrating from v3 before verifying plugin compatibility.
