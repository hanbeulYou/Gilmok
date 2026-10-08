import process from 'node:process';
import console from 'node:console';
import { execFileSync } from 'node:child_process';
import { appendFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

// Unknown/empty diffs run E2E. Only documentation-only PRs may skip it.
export function requiresE2E(paths, eventName) {
  return eventName !== 'pull_request' || paths.length === 0
    || paths.some(path => !path.startsWith('docs/') && !/\.mdx?$/i.test(path));
}

export function changedPaths(base, cwd = process.cwd()) {
  if (!/^[0-9a-f]{40}$/.test(base ?? '')) throw new Error('Missing PR base SHA');
  // Include both sides of renames: code renamed to *.md must still run E2E.
  return execFileSync('git', ['diff', '--name-only', '--no-renames', '-z', base, 'HEAD'],
    { cwd, encoding: 'utf8' }).split('\0').filter(Boolean);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  let paths = [];
  try {
    if (process.env.GITHUB_EVENT_NAME === 'pull_request') paths = changedPaths(process.env.PR_BASE_SHA);
  } catch {
    console.warn('Changed paths unavailable; run E2E conservatively.');
  }
  const run = requiresE2E(paths, process.env.GITHUB_EVENT_NAME);
  console.log(`E2E scope: ${run ? 'run' : 'skip (documentation-only PR)'}; changed paths=${paths.length}`);
  appendFileSync(process.env.GITHUB_OUTPUT, `run_e2e=${run}\n`);
}
