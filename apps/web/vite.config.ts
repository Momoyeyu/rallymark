import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { previewData } from './dev/preview';
export default defineConfig({
  plugins: [react(), previewData()],
  server: { host: '0.0.0.0', proxy: { '/api': 'http://localhost:8000' } },
});
