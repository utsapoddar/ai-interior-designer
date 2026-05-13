import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  base: './',
  plugins: [react()],
  server: {
    proxy: {
      '/health': 'http://localhost:8000',
      '/catalog': 'http://localhost:8000',
      '/scans': 'http://localhost:8000',
      '/plans': 'http://localhost:8000',
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (/node_modules\/(three|@react-three)/.test(id)) {
            return 'three';
          }
        },
      },
    },
  },
});
