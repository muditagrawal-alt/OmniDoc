import { useState } from 'react';
import type { Ref } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import styles from './PasswordInput.module.css';

interface PasswordInputProps {
  id: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete: 'current-password' | 'new-password';
  inputRef?: Ref<HTMLInputElement>;
}

/** A password field with a show/hide button, so a new password can be checked without typing it twice. */
export function PasswordInput({ id, value, onChange, autoComplete, inputRef }: PasswordInputProps) {
  const [shown, setShown] = useState(false);
  return (
    <div className={styles.secret}>
      <input id={id} ref={inputRef} className="field" type={shown ? 'text' : 'password'} autoComplete={autoComplete}
        autoCapitalize="none" spellCheck={false} maxLength={200} value={value} onChange={(e) => onChange(e.target.value)} />
      <button type="button" className={styles.reveal} onClick={() => setShown((v) => !v)}
        aria-label={shown ? 'Hide password' : 'Show password'} aria-pressed={shown}>
        {shown ? <EyeOff size={16} strokeWidth={1.75} /> : <Eye size={16} strokeWidth={1.75} />}
      </button>
    </div>
  );
}
