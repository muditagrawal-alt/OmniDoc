import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

// Fonts are bundled locally: OmniDoc makes no third-party requests.
import '@fontsource-variable/instrument-sans';
import '@fontsource-variable/source-serif-4/opsz.css';
import '@fontsource-variable/source-serif-4/opsz-italic.css';
import '@fontsource/ibm-plex-mono/400.css';
import '@fontsource/ibm-plex-mono/500.css';
import 'katex/dist/katex.min.css';

import './styles/tokens.css';
import './styles/base.css';
import './styles/primitives.css';
import App from './App';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
