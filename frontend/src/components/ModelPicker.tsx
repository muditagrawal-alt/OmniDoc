import { Check, ChevronDown, Cpu, Gauge, KeyRound } from 'lucide-react';
import type { Effort } from '../api';
import { chooseModel, modelName, useModels } from '../lib/models';
import { setSetting, useSettings } from '../lib/settings';
import { Popover, Segmented } from './ui/Controls';
import type { SegmentedOption } from './ui/Controls';
import { useToast } from './ui/Toast';
import styles from './ModelPicker.module.css';

const EFFORTS: ReadonlyArray<SegmentedOption<Effort>> = [
  { value: 'quick', label: 'Quick' },
  { value: 'balanced', label: 'Balanced' },
  { value: 'thorough', label: 'Thorough' },
];

/* Passage counts mirror core/effort.py on the server. */
const EFFORT_NOTE: Record<Effort, { reads: string; when: string; tokens: string }> = {
  quick: { reads: 'Reads about 6 passages', when: 'Fastest. Good for a single fact or figure.', tokens: 'About 60% of the evidence tokens' },
  balanced: { reads: 'Reads about 10 passages', when: 'The setting the published benchmarks use.', tokens: 'The usual amount of evidence' },
  thorough: { reads: 'Reads up to 16 passages', when: 'Slower. For answers spread over many pages.', tokens: 'About 160% of the evidence tokens' },
};

export interface CostContext {
  /** A hosted server with accounts (the trial and own keys apply). */
  accountsMode: boolean;
  /** Free answers left on the server's keys; null when they do not apply. */
  freeAnswers?: { left: number; limit: number } | null;
  onAddKey?: () => void;
}

/** What an answer costs here: always nothing, but on whose free tier, and with which limit. */
function CostNote({ accountsMode, freeAnswers, onAddKey }: CostContext) {
  if (accountsMode && freeAnswers) {
    return (
      <p className={styles.cost}>
        <strong>Free.</strong> Answers on OmniDoc’s keys use your free answers: {freeAnswers.left} of {freeAnswers.limit} left.
        {onAddKey && (
          <button type="button" className={styles.costLink} onClick={onAddKey}>
            <KeyRound size={13} strokeWidth={1.75} /> Use your own free key
          </button>
        )}
      </p>
    );
  }
  return (
    <p className={styles.cost}>
      <strong>Free.</strong>{' '}
      {accountsMode
        ? 'Answers use your own key, or the free tiers this server is set up with.'
        : 'Every model here runs on a free hosted tier or on this computer.'}
    </p>
  );
}

/** The models the server offers, grouped by provider, as a single-choice list. */
export function ModelChoices({ onChosen }: { onChosen?: () => void }) {
  const { models, current, error, loading } = useModels();
  const toast = useToast();
  const choose = async (name: string) => {
    try {
      const now = await chooseModel(name);
      toast(`Answers now use ${modelName(now, models)}`, 'good');
      onChosen?.();
    } catch (e) {
      toast((e as Error).message, 'bad');
    }
  };
  if (error) return <p className={styles.note}>{error}</p>;
  if (!models) return <p className={styles.note}>{loading ? 'Loading models…' : 'No models listed.'}</p>;
  return (
    <div role="radiogroup" aria-label="Answer model" className={styles.models}>
      {models.map((m, i) => (
        <div key={m.name}>
          {(i === 0 || models[i - 1].provider_label !== m.provider_label) && m.provider_label && (
            <p className={styles.provider}>{m.provider_label}</p>
          )}
          <button type="button" role="radio" aria-checked={current === m.name} className={styles.model} onClick={() => choose(m.name)}>
            <span className={styles.modelName}>{m.label || modelName(m.name, models)}</span>
            <span className={styles.modelMeta}>
              {m.tier && <span className={styles.tag}>{m.tier === 'fast' ? 'Fast' : 'Smart'}</span>}
              {m.parameter_size && <span className={styles.tag}>{m.parameter_size}</span>}
              <span className={styles.price}>{m.hosted === false ? 'This computer' : 'Free'}</span>
            </span>
            <span className={styles.check}>{current === m.name && <Check size={15} strokeWidth={2} />}</span>
          </button>
        </div>
      ))}
    </div>
  );
}

/** Quick, Balanced or Thorough, with what each one reads. */
export function EffortChoice() {
  const { effort } = useSettings();
  const note = EFFORT_NOTE[effort];
  return (
    <div className={styles.effort}>
      <Segmented options={EFFORTS} value={effort} onChange={(v) => setSetting('effort', v)} label="Effort" stretch />
      <p className={styles.effortNote}>
        <span>{note.reads}. {note.when}</span>
        <span className={styles.tokens}>{note.tokens}</span>
      </p>
    </div>
  );
}

/** The model and effort for the next answers, from the chat's navigation bar. */
export function ModelPicker(cost: CostContext) {
  const { models, current } = useModels();
  const { effort } = useSettings();
  return (
    <Popover
      label="Model and effort"
      width={360}
      trigger={(p) => (
        <button type="button" className={styles.trigger} {...p}>
          <Cpu size={15} strokeWidth={1.75} />
          <span className={styles.triggerName}>{current ? modelName(current, models) : 'Model'}</span>
          <span className={styles.triggerEffort}>{EFFORTS.find((e) => e.value === effort)?.label}</span>
          <ChevronDown size={14} strokeWidth={1.75} />
        </button>
      )}
    >
      {(close) => (
        <div className={styles.panel}>
          <p className={styles.heading}><Gauge size={14} strokeWidth={1.75} /> Effort</p>
          <EffortChoice />
          <p className={styles.heading}><Cpu size={14} strokeWidth={1.75} /> Model</p>
          <CostNote {...cost} onAddKey={cost.onAddKey ? () => { close(); cost.onAddKey?.(); } : undefined} />
          <ModelChoices onChosen={close} />
        </div>
      )}
    </Popover>
  );
}
