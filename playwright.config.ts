import { defineConfig } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';

const local = JSON.parse(execFileSync('supabase', ['status', '-o', 'json'], { encoding:'utf8', stdio:['ignore','pipe','ignore'] }));
if (!['localhost','127.0.0.1'].includes(new URL(local.API_URL).hostname)) throw new Error('E2E requires local Supabase');
process.env.E2E_SUPABASE_URL = local.API_URL;
process.env.E2E_SUPABASE_KEY = local.ANON_KEY;
if (process.env.E2E_APP_MODE === 'production' && process.env.SLIDER_PERFORMANCE_POLICY === 'ci') {
  throw new Error('Production measurements require the per-set slider policy');
}
export default defineConfig({
  testDir:'tests/e2e', testMatch:'compare.spec.ts', fullyParallel:false, workers:1, retries:0,
  timeout:process.env.BUILDING_3D_FPS === '1' ? 600_000 : 180_000, expect:{ timeout:60_000 }, outputDir:'.local/playwright-results',
  reporter:[['list'], ['json', { outputFile:'.local/playwright-results/report.json' }]], use:{ baseURL:'http://127.0.0.1:3105', browserName:'chromium',
    viewport:{ width:1440, height:1000 }, trace:'off', screenshot:'only-on-failure', actionTimeout:30000,
    ...(process.env.E2E_REAL_GPU === '1' ? { headless:false, channel:'chrome', deviceScaleFactor:2, launchOptions:{args:[]} }
      : {launchOptions:{args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']}}) },
  webServer:{ command:process.env.E2E_APP_MODE === 'production'
    ? 'pnpm build && pnpm start --hostname 127.0.0.1 --port 3105'
    : 'pnpm exec next dev --hostname 127.0.0.1 --port 3105', url:'http://127.0.0.1:3105',
    reuseExistingServer:false, timeout:120_000, env:{
      NEXT_PUBLIC_SUPABASE_URL:local.API_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY:local.ANON_KEY,
      JUSO_API_KEY:'local-fixture', VWORLD_API_KEY:'local-fixture',
      NODE_OPTIONS:`--import=${resolve('tests/e2e/providers.mjs')}`, NEXT_TELEMETRY_DISABLED:'1',
      NEXT_PUBLIC_MAP_STYLE_URL:process.env.E2E_REAL_MAP_STYLE === '1'
        ? 'https://tiles.openfreemap.org/styles/liberty' : 'https://map.gilmok.test/style.json',
    } },
});
