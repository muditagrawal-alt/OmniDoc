import React from 'react';
import { Globe } from 'lucide-react';
import { SUPPORTED_LANGUAGES } from '../utils/voice';

interface LanguageSelectorProps {
  currentLanguage: string;
  onChangeLanguage: (code: string) => void;
}

export const LanguageSelector: React.FC<LanguageSelectorProps> = ({
  currentLanguage,
  onChangeLanguage,
}) => {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: '0.4rem',
      backgroundColor: 'var(--bg-surface)',
      border: '1px solid var(--border-subtle)',
      borderRadius: 'var(--radius-md)',
      padding: '0.2rem 0.5rem',
      fontSize: '0.78rem',
      color: 'var(--text-secondary)',
    }}>
      <Globe size={13} style={{ color: 'var(--accent-primary)', flexShrink: 0 }} />
      <select
        value={currentLanguage}
        onChange={(e) => onChangeLanguage(e.target.value)}
        style={{
          background: 'transparent',
          border: 'none',
          color: 'var(--text-primary)',
          fontSize: '0.78rem',
          outline: 'none',
          cursor: 'pointer',
          padding: '0.1rem 0.2rem',
        }}
      >
        {SUPPORTED_LANGUAGES.map((lang) => (
          <option
            key={lang.code}
            value={lang.code}
            style={{ backgroundColor: '#151922', color: '#f8fafc' }}
          >
            {lang.nativeName} ({lang.name})
          </option>
        ))}
      </select>
    </div>
  );
};
