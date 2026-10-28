import { defineConfig } from '@playwright/test';
import { execFileSync } from 'node:child_process';
if (process.env.ACADEMY_FPS === '1') {
  if (process.env.ACADEMY_REAL_GPU !== '1') throw new Error('FPS must use real GPU');
  execFileSync(process.execPath, ['tests/e2e/academy-hardware.mjs'], { stdio: 'inherit' });
}
export default defineConfig({
  testDir: 'tests/e2e', testMatch: process.env.ACADEMY_REAL_DATA === '1' ? 'academy-real.spec.ts' : 'academy-layer.spec.ts', workers: 1, retries: 0,
  timeout: 600_000, expect: { timeout: 30_000 }, outputDir: '.local/academy-b/results',
  reporter: [['list'], ['json', { outputFile: '.local/academy-b/report.json' }]],
  use: { baseURL: process.env.ACADEMY_PREVIEW_URL || 'http://127.0.0.1:3106', viewport: { width: 1440, height: 1000 },
    screenshot: 'only-on-failure',
    ...(process.env.ACADEMY_REAL_GPU === '1' ? { headless: false, channel: 'chrome', deviceScaleFactor: 2, launchOptions: { args: ['--window-position=0,0'] } }
      : { launchOptions: { args: ['--use-angle=swiftshader','--enable-unsafe-swiftshader'] } }) },
  webServer: process.env.ACADEMY_PREVIEW_URL ? undefined : { command: 'pnpm build && pnpm start --hostname 127.0.0.1 --port 3106',
    url: 'http://127.0.0.1:3106', timeout: 120_000, reuseExistingServer: false,
    env: { NEXT_PUBLIC_SUPABASE_URL: 'http://127.0.0.1:56999', NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: 'synthetic-key',
      NEXT_PUBLIC_MAP_STYLE_URL: process.env.ACADEMY_REAL_DATA === '1' ? 'https://tiles.openfreemap.org/styles/liberty' : 'https://map.gilmok.test/style.json', NEXT_TELEMETRY_DISABLED: '1' } },
});
