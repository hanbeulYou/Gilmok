import { academyV0 } from '../scoring/presets';
import type { ComparisonCandidate } from './store';

/** The saved input contract version is unrelated to the version of these scores. */
export function savableModelVersion(rows: readonly ComparisonCandidate[]): string | null {
  return rows.length > 0 && rows.every(row =>
    ['scored', 'scored_provisional'].includes(row.stage) && !row.refreshing && !row.error &&
    row.result?.preset.version === academyV0.version) ? academyV0.version : null;
}

export function modelVersionNotice(saved: string | null | undefined, rows: readonly ComparisonCandidate[], snapshotReadOnly: boolean) {
  if (saved === undefined || saved === academyV0.version) return null;
  const prefix = saved === null ? '저장 당시 모델 미기록' : `저장 모델 v${saved}`;
  const target = `현재 v${academyV0.version}`;
  if (snapshotReadOnly || rows.some(row => row.stage === 'error'))
    return { phase: 'failed', message: `${prefix} · ${target} 재계산 실패. 다시 시도해 주세요.` } as const;
  if (savableModelVersion(rows) === null)
    return { phase: 'calculating', message: `${prefix} · ${target}로 다시 계산 중입니다.` } as const;
  return { phase: 'complete', message: `${prefix} · ${target}로 다시 계산했습니다. 저장하면 모델 버전도 갱신됩니다.` } as const;
}
