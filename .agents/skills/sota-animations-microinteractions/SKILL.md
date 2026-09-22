---
name: sota-animations-microinteractions
description: >-
  Functional micro-interactions, state transitions, and accessible motion engineering.
  Ensures motion communicates state, hierarchy, feedback, and spatial continuity with full prefers-reduced-motion
  and keyboard focus parity. Activate when implementing hover/focus states, view transitions, loading feedback,
  gestures, or layout animations.
---

# Functional Animations & Micro-Interactions

## When to Use
Activate this skill whenever:
- Implementing interactive state transitions (hover, active, focus, disabled).
- Creating page, modal, or layout transitions.
- Adding loading indicators, progress bars, or skeleton pulse animations.
- Designing gestures, dragging interactions, or physics-based spring movements.
- Auditing existing animations for performance bottlenecks, accessibility compliance, and reduced-motion support.

---

## 1. Functional Purpose of Motion
Motion in user interfaces must serve a clear function. Never add decorative animation that delays user action or increases cognitive load.

Every animation must fulfill at least one of these roles:
1. **Communicating State**: Confirming that a toggle switched, a form submitted, or a record saved.
2. **Clarifying Hierarchy**: Revealing child details emerging from their parent trigger.
3. **Preserving Spatial Continuity**: Helping users track where an item moved or expanded during layout changes.
4. **Providing Feedback**: Indicating system responsiveness and preventing repeat clicks during latency.

---

## 2. Compositing & Performance Reality
- **Prefer `transform` and `opacity` for frequent animations**: These properties avoid triggering browser layout and repaint passes when handled on the compositor thread.
- **No 60fps Guarantees**: `transform` and `opacity` do NOT automatically guarantee 60fps. Performance depends on layer memory, paint complexity, GPU bus limits, and main-thread JavaScript load.
- **Allowed Complex Properties**: Transitioning `background-color`, `border-color`, `clip-path`, or `filter` is permitted when design intent justifies it, provided it is profiled in DevTools to ensure frame budgets are respected.
- **NEVER use `transition: all`**: Always declare explicit properties with independent timings. `transition: all` triggers unintended transitions (e.g. padding, margins) and hurts performance.

---

## 3. Inclusive Motion & Accessibility

### A. Mandatory `prefers-reduced-motion` Support
Users with vestibular disorders or motion sensitivity must receive a reduced-motion experience. Provide immediate state changes or subtle opacity fades.

```css
/* Standard motion */
.btn-interactive {
  transition:
    transform 160ms cubic-bezier(0.16, 1, 0.3, 1),
    background-color 160ms ease,
    box-shadow 160ms ease;
}

.btn-interactive:hover {
  transform: translateY(-1px);
}

/* Reduced motion override */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }

  /* When motion is reduced, preserve subtle opacity or color transitions without movement */
  .btn-interactive:hover {
    transform: none;
  }
}
```

### B. Keyboard and Focus Parity
Interactive states shown on `:hover` must have an equivalent, clearly visible state on `:focus-visible`. A keyboard user must experience the same state clarity as a pointer user.

```css
.card-item {
  border: 1px solid var(--border-subtle);
  background-color: var(--bg-surface);
  transition:
    border-color 150ms ease,
    box-shadow 150ms ease,
    transform 150ms cubic-bezier(0.16, 1, 0.3, 1);
}

.card-item:hover {
  border-color: var(--border-strong);
  transform: translateY(-2px);
}

/* Keyboard parity with visible ring */
.card-item:focus-visible {
  outline: none;
  border-color: var(--color-accent);
  box-shadow: 0 0 0 2px var(--color-accent);
  transform: translateY(-2px);
}
```

---

## 4. Animation Stack Selection & Browser Support
Select animation tools based on project requirements and verified browser support:

| Tool / API | When to Choose | Browser Support & Verification |
|---|---|---|
| **CSS Transitions & Keyframes** | Micro-interactions, hover/focus, simple spinners | Universal browser support. Zero JS runtime overhead. |
| **CSS View Transitions API** | Page transitions and shared element continuity | Supported in modern Chromium/Safari. Always wrap in `if (document.startViewTransition)` feature detection. |
| **CSS Scroll-Driven Animations** | Scroll progress bars and subtle reveal-on-scroll | Supported in Chromium. Use feature queries `@supports (animation-timeline: scroll())` with static fallback. |
| **Motion (Framer Motion)** | Complex gesture drag, shared layout transitions, spring physics | Check bundle impact (~30kB+). Prefer pure CSS for basic interactions; reserve Motion for complex UI orchestration. |

---

## 5. Practical Implementation Recipes

### Explicit Focus & Hover Card Transition
```css
.interactive-panel {
  background-color: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  /* Enumerate every animated property explicitly */
  transition:
    transform 200ms cubic-bezier(0.16, 1, 0.3, 1),
    border-color 200ms ease,
    box-shadow 200ms ease;
}

.interactive-panel:hover {
  transform: translateY(-2px);
  border-color: var(--border-strong);
  box-shadow: 0 4px 12px oklch(0 0 0 / 0.08);
}

.interactive-panel:focus-visible {
  outline: none;
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px oklch(from var(--color-accent) l c h / 0.25);
  transform: translateY(-2px);
}
```

### Loading Skeleton Pulse
```css
.skeleton-loader {
  background-color: var(--bg-surface-raised);
  border-radius: 4px;
  animation: skeleton-fade 1.8s ease-in-out infinite;
}

@keyframes skeleton-fade {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.45; }
}

@media (prefers-reduced-motion: reduce) {
  .skeleton-loader {
    animation: none;
    opacity: 0.7;
  }
}
```

---

## 6. Performance Testing Workflow
1. **Open Chrome DevTools Performance Panel**: Record user interaction flows (clicking buttons, expanding menus, scrolling).
2. **Inspect Frame Rate & Long Animation Frames (LoAF)**: Ensure transitions do not exceed the 16.6ms frame budget or block the main thread.
3. **Check Paint Flashing & Layer Borders**: Enable "Rendering > Paint flashing" in DevTools to verify that animations avoid unnecessary full-page repaints.

---

## Anti-Patterns
- ❌ Never use `transition: all`. Explicitly name all transitioned properties.
- ❌ Never add decorative motion that does not communicate state, hierarchy, spatial continuity, or feedback.
- ❌ Never claim that `transform` and `opacity` guarantee 60fps without profiling against real-world hardware.
- ❌ Never omit `@media (prefers-reduced-motion: reduce)` fallbacks.
- ❌ Never provide hover animations without matching keyboard `:focus-visible` parity.
- ❌ Never use heavy JavaScript animation libraries for simple transitions that CSS handles natively.
