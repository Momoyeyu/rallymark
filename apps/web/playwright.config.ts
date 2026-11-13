import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  retries: 0,
  use: { baseURL: 'http://127.0.0.1:4187', viewport: { width: 390, height: 844 } },
  webServer: [
    {
      command: 'pnpm dev --port 4187 --strictPort',
      url: 'http://127.0.0.1:4187',
      reuseExistingServer: false,
    },
    {
      command: 'pnpm exec vite --config vite.preview.config.ts --port 4188 --strictPort',
      url: 'http://127.0.0.1:4188',
      reuseExistingServer: false,
    },
  ],
});
