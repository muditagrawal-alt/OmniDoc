import { Monitor, Moon, Sun } from 'lucide-react';
import { useTheme } from '../lib/theme';
import type { ThemePreference } from '../lib/theme';
import { Segmented } from './ui/Controls';
import type { SegmentedOption } from './ui/Controls';

const OPTIONS: ReadonlyArray<SegmentedOption<ThemePreference>> = [
  { value: 'system', label: 'System', icon: Monitor, hint: 'Follow this device’s light or dark setting' },
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
];

/** System, light or dark: icons only in navigation bars, labelled in settings. */
export function ThemeSwitch({ labelled = false, stretch = false }: { labelled?: boolean; stretch?: boolean }) {
  const { preference, setPreference } = useTheme();
  return (
    <Segmented options={OPTIONS} value={preference} onChange={setPreference} label="Theme"
      iconOnly={!labelled} size={labelled ? 'md' : 'sm'} stretch={stretch} />
  );
}
