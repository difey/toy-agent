import { resolve } from 'node:path';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  base: '/static/dist/',
  build: {
    outDir: '../src/nano_claude/interfaces/web/static/dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        index: resolve(__dirname, 'index.html'),
        'plan-view': resolve(__dirname, 'plan-view.html'),
      },
    },
  },
});
