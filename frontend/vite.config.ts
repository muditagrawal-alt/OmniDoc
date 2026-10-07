import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// The FastAPI backend (server.py) listens on :8000. Proxying /api keeps the
// browser same-origin in development and preview, so no CORS is involved.
const api = { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } };

export default defineConfig({
  plugins: [react()],
  server: { proxy: api },
  preview: { proxy: api },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/three')) return 'three';
          if (id.includes('node_modules/katex')) return 'katex';
        },
      },
    },
  },
});
