import { execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { expect, it } from 'vitest';
import { changedPaths, requiresE2E } from '../../.github/scripts/e2e-scope.mjs';

it('skips only docs-only PRs; code/config/mixed/unknown/main still run', () => {
  expect(requiresE2E(['docs/validation/result.json', 'README.md', 'nested/guide.mdx'], 'pull_request')).toBe(false);
  for (const path of ['app/page.tsx', 'package.json', 'pnpm-lock.yaml', '.github/workflows/ci.yml', 'supabase/migrations/new.sql']) {
    expect(requiresE2E(['docs/plan.md', path], 'pull_request')).toBe(true);
  }
  expect(requiresE2E([], 'pull_request')).toBe(true);
  expect(requiresE2E(['README.md'], 'push')).toBe(true);
  expect(() => changedPaths('')).toThrow();
});

it('reads the full Git diff, including code renamed to documentation', () => {
  const cwd = mkdtempSync(join(tmpdir(), 'gilmok-scope-'));
  const git = (...args: string[]) => execFileSync('git', args, { cwd, encoding:'utf8' }).trim();
  try {
    git('init', '-q');
    git('config', 'user.name', 'Scope test');
    git('config', 'user.email', 'scope@example.invalid');
    writeFileSync(join(cwd, 'code.ts'), 'export const value = 1;\n');
    git('add', '.'); git('-c', 'commit.gpgsign=false', 'commit', '-qm', 'base');
    const base = git('rev-parse', 'HEAD');
    mkdirSync(join(cwd, 'docs'));
    renameSync(join(cwd, 'code.ts'), join(cwd, 'docs', 'renamed.md'));
    for (let i = 0; i < 301; i++) writeFileSync(join(cwd, 'docs', `${i}.md`), 'docs\n');
    git('add', '.'); git('-c', 'commit.gpgsign=false', 'commit', '-qm', 'rename and docs');
    const paths = changedPaths(base, cwd);
    expect(paths).toHaveLength(303);
    expect(paths).toContain('code.ts');
    expect(requiresE2E(paths, 'pull_request')).toBe(true);
  } finally {
    rmSync(cwd, { recursive:true, force:true });
  }
});
