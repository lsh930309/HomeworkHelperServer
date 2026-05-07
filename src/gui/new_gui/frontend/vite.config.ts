import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: '/',
  build: {
    outDir: '../../../../build/main-gui-static',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: 'main-gui.js',
        chunkFileNames: 'main-gui-[name].js',
        assetFileNames: (assetInfo) => assetInfo.name?.endsWith('.css') ? 'main-gui.css' : 'main-gui-[name][extname]',
      },
    },
  },
});
