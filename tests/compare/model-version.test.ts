import { describe, expect, it } from 'vitest';
import { academyV0 } from '../../lib/scoring/presets';
import { modelVersionNotice, savableModelVersion } from '../../lib/compare/model-version';
import { useComparisonStore, type ComparisonCandidate } from '../../lib/compare/store';

const row = (patch: Partial<ComparisonCandidate> = {}): ComparisonCandidate => ({
  id:'candidate', stage:'scored', result:{ preset:{ id:'academy_v0', version:'0.4.0' } }, ...patch,
} as ComparisonCandidate);

describe('saved scoring model notices', () => {
  it('never compares the legacy 0.3 input-contract field', () => {
    expect(modelVersionNotice(undefined, [row()], false)).toBeNull();
    expect(modelVersionNotice('0.4.0', [row()], false)).toBeNull();
    expect(modelVersionNotice(null, [row()], false)?.message).toContain('저장 당시 모델 미기록');
  });
  it.each([null, '0.3'])('keeps %s visible through calculation, failure and retry until explicit save', saved => {
    expect(modelVersionNotice(saved, [row({ stage:'fetching', result:undefined })], false)?.phase).toBe('calculating');
    expect(modelVersionNotice(saved, [row(), row({ stage:'error' })], false)?.phase).toBe('failed');
    expect(modelVersionNotice(saved, [row({ stage:'scoring' })], false)?.phase).toBe('calculating');
    const done = modelVersionNotice(saved, [row()], false);
    expect(done?.phase).toBe('complete');
    expect(done?.message).toContain(saved === null ? '모델 미기록' : '저장 모델 v0.3');
    expect(done?.message).toContain('저장하면 모델 버전도 갱신');
    expect(modelVersionNotice(saved, [row()], true)?.phase).toBe('failed');
  });
  it('tags only complete current results, including a pending register scored by that model', () => {
    expect(savableModelVersion([row(), row({ stage:'scored_provisional' })])).toBe(academyV0.version);
    for (const patch of [{ stage:'error' }, { stage:'fetching' }, { refreshing:true }, { error:'failed' }, { result:undefined }] as Partial<ComparisonCandidate>[])
      expect(savableModelVersion([row(), row(patch)])).toBeNull();
    expect(savableModelVersion([])).toBeNull();
    expect(savableModelVersion([row({ result:{ preset:{ id:'academy_v0', version:'0.3' } } as ComparisonCandidate['result'] })])).toBeNull();
  });
  it('clears previous owner metadata on clear/uid replacement', () => {
    useComparisonStore.setState({ savedModelVersion:'0.3' });
    useComparisonStore.getState().clear();
    expect(useComparisonStore.getState().savedModelVersion).toBeUndefined();
  });
});
