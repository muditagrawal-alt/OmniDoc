import { useEffect, useSyncExternalStore } from 'react';
import { api } from '../api';
import type { ModelInfo } from '../api';

/* The answer models the server offers and the one in use, shared by the model picker and Settings. */

interface ModelsState {
  models: ModelInfo[] | null;
  current: string;
  error: string | null;
  loading: boolean;
}

let state: ModelsState = { models: null, current: '', error: null, loading: false };
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
    .then((r) => emit({ models: r.models, current: r.current, error: null, loading: false }))
    .catch((e: Error) => emit({ error: e.message, loading: false }));
}

/** Switches the answer model; resolves to the model now in use. */
export async function chooseModel(name: string): Promise<string> {
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
