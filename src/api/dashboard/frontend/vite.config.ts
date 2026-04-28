import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  base: '/static/dashboard/',
  plugins: [react()],
  build: {
    outDir: '../static',
    emptyOutDir: false,
    rollupOptions: {
      output: {
        entryFileNames: 'dashboard.js',
        chunkFileNames: 'dashboard-[name].js',
        assetFileNames: (assetInfo) => assetInfo.name?.endsWith('.css') ? 'dashboard.css' : 'dashboard-[name][extname]',
      },
    },
  },
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
});
