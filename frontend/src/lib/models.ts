import { useEffect, useSyncExternalStore } from 'react';
import { api } from '../api';
import type { ModelInfo } from '../api';
import { getSettings, setSetting } from './settings';

/* The answer models the server offers and the one in use, shared by the model picker and Settings. */

interface ModelsState {
  models: ModelInfo[] | null;
  /** The server's default answer model. */
  current: string;
  /** Whether this user may change the default for everyone (an administrator, or a local install). */
  canSetDefault: boolean;
  error: string | null;
  loading: boolean;
}

let state: ModelsState = { models: null, current: '', canSetDefault: false, error: null, loading: false };
const listeners = new Set<() => void>();

function emit(next: Partial<ModelsState>) {
  state = { ...state, ...next };
  listeners.forEach((l) => l());
}

export function loadModels() {
  if (state.loading) return;
  emit({ loading: true });
  api
    .getModels()
    .then((r) => {
      // A model chosen earlier that this server no longer offers falls back to the default.
      const mine = getSettings().model;
      if (mine && !r.models.some((m) => m.name === mine)) setSetting('model', '');
      emit({ models: r.models, current: r.current, canSetDefault: !!r.can_set_default, error: null, loading: false });
    })
    .catch((e: Error) => emit({ error: e.message, loading: false }));
}

/** The model this user's questions use: their own choice, or the server's default. */
export function chooseModel(name: string) {
  setSetting('model', name === state.current ? '' : name);
}

/** Changes the default answer model for everyone (administrators). */
export async function setDefaultModel(name: string): Promise<string> {
  const r = await api.setModel(name);
  emit({ current: r.current });
  return r.current;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useModels(): ModelsState {
  const s = useSyncExternalStore(subscribe, () => state);
  useEffect(() => {
    if (!state.models && !state.loading && !state.error) loadModels();
  }, []);
  return s;
}

/** A short name for a model: its label, or the last part of its id. */
export function modelName(name: string, models: ModelInfo[] | null): string {
  const m = models?.find((x) => x.name === name);
  if (m?.label) return m.label;
  return name.split(':').slice(-1)[0].split('/').slice(-1)[0] || 'Model';
}
