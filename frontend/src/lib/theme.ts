import { useSyncExternalStore } from 'react';

export type ThemePreference = 'system' | 'light' | 'dark';
export type ResolvedTheme = 'light' | 'dark';

const STORAGE_KEY = 'omnidoc_theme';
const media = typeof window !== 'undefined' ? window.matchMedia('(prefers-color-scheme: dark)') : null;
const listeners = new Set<() => void>();

function readPreference(): ThemePreference {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === 'light' || v === 'dark' || v === 'system') return v;
  } catch {
    /* storage unavailable */
  }
  return 'system';
}

let preference: ThemePreference = readPreference();

function resolve(pref: ThemePreference): ResolvedTheme {
  if (pref === 'system') return media?.matches ? 'dark' : 'light';
  return pref;
}

let snapshot = { preference, resolved: resolve(preference) };

function apply() {
  snapshot = { preference, resolved: resolve(preference) };
  document.documentElement.dataset.theme = snapshot.resolved;
  listeners.forEach((l) => l());
}

media?.addEventListener('change', () => {
  if (preference === 'system') apply();
});

export function setThemePreference(next: ThemePreference) {
  preference = next;
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    /* storage unavailable */
  }
  apply();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Current theme preference and the resolved light/dark value. */
export function useTheme() {
  const state = useSyncExternalStore(subscribe, () => snapshot);
  return { ...state, setPreference: setThemePreference };
}

/** Reads a CSS custom property from :root (used by canvas/WebGL code). */
export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
