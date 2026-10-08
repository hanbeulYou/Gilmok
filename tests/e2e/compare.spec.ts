import { expect, test } from '@playwright/test';
import { createClient } from '@supabase/supabase-js';
import { execFileSync } from 'node:child_process';
import fixtures from './fixtures/addresses.json';
import { mapFixture, checkMap, checkMobileTabs } from './map-network';

test('a~e 등록 → v0.4.0 근거 → 슬라이더 → 익명 저장 → 같은 uid 재열기', async ({ page, browser }, info) => {
  await page.addInitScript(() => {
    const send = Worker.prototype.postMessage;
    Worker.prototype.postMessage = function(message: unknown, transfer?: Transferable[] | StructuredSerializeOptions) {
      if (message && typeof message === 'object' && 'scene' in message && document.documentElement)
        document.documentElement.dataset.exposureRuns = String(Number(document.documentElement.dataset.exposureRuns ?? '0') + 1);
      return Reflect.apply(send, this, transfer === undefined ? [message] : [message, transfer]);
    };
  });
  await mapFixture(page);
  const scoringCoordinates: number[][] = [];
  page.on('request', request => { if (request.url().endsWith('/rpc/score_inputs')) { const body = request.postDataJSON(); scoringCoordinates.push([body.lng, body.lat]); } });
  const users: string[] = [], rpc: { name:string; status:number }[] = [];
  const errors: string[] = [];
  const percentileResponses: unknown[] = [];
  const local = JSON.parse(execFileSync('supabase',['status','-o','json'],{ encoding:'utf8',stdio:['ignore','pipe','ignore'] }));
  if (!['localhost','127.0.0.1'].includes(new URL(local.API_URL).hostname)) throw new Error('Model fixture requires local Supabase');
  const admin = createClient(local.API_URL,local.SERVICE_ROLE_KEY,{ auth:{ persistSession:false } });

  page.on('pageerror', e => errors.push(e.message));
  page.on('response', async response => {
    if (response.url().includes('/auth/v1/signup') && response.status() === 200) users.push((await response.json()).user.id);
    if (response.url().includes('/rpc/')) rpc.push({ name:response.url().split('/').at(-1)!, status:response.status() });
    if (response.url().endsWith('/rpc/score_reference_percentiles') && response.status() === 200)
      percentileResponses.push(await response.json());
  });
  try {
    const expected = [83.10201719669011,92.60289331263688,82.67204741731668,81.84736541572254,85.08500496915157];
    const candidates = [...fixtures, { ...fixtures[0], floor:4 }, { ...fixtures[0], floor:1 }];
    for (let i=0; i<candidates.length; i++) {
      if (!i) await page.goto('/new'); else await page.getByRole('link',{ name:'후보 추가', exact:true }).first().click();
      await expect(page.getByLabel('주소 *',{ exact:true })).toBeEnabled();
      await page.getByLabel('주소 *',{ exact:true }).fill(candidates[i].address);
      await page.locator('.address-options button').filter({ has:page.locator('strong',{ hasText:candidates[i].address }) }).first().click();
      await page.getByLabel('층 *',{ exact:true }).fill(String(candidates[i].floor));
      await page.locator('#alias').fill(['a','b','c','d','e'][i]);
      await page.getByRole('button',{ name:'후보 추가하고 채점', exact:true }).click();
      await expect(page).toHaveURL(/\/compare/);
      await expect(page.locator('.desktop-matrix [data-total]')).toHaveCount(i+1);
    }
    const totals = () => page.locator('.desktop-matrix [data-total]').evaluateAll(nodes => nodes.map(n => Number((n as HTMLElement).dataset.total)));
    const axes = await page.locator('.desktop-matrix').evaluate(matrix => {
      const names = Object.fromEntries([...matrix.querySelectorAll<HTMLElement>('th[data-candidate-id]')]
        .map(n => [n.dataset.candidateId,n.querySelector('.candidate-name')?.textContent]));
      return [...matrix.querySelectorAll<HTMLElement>('td[data-axis]')].map(n => ({
        candidate:names[n.dataset.candidateId!],axis:n.dataset.axis,
        score:n.querySelector<HTMLElement>('[data-score]')?.dataset.score,
      }));
    });
    console.log('public-score-diagnostic',JSON.stringify({ totals:await totals(),axes,percentileResponses }));
    expect((await totals()).sort((a,b)=>a-b)).toEqual([...expected].sort((a,b)=>a-b));
    const confidence = await page.locator('.desktop-matrix .confidence').evaluateAll(nodes =>
      nodes.map(n => Number(n.querySelector('text')?.textContent)).sort((a,b)=>a-b));
    expect(confidence).toEqual([85,90,90,90,90]);
    await page.locator('.desktop-matrix').getByRole('button',{ name:'a 건물 적합성 근거', exact:true }).click();
    await expect(page.getByTestId('floor-elevator-rule')).toHaveText('적용 행: 3층 · 승용승강기 없음 · 보정 -5점');
    await page.getByRole('button',{ name:'근거 닫기', exact:true }).click();
    await page.locator('.desktop-matrix').getByRole('button',{ name:'a 건물 앞 도로·맞은편에서의 간판 노출 근거', exact:true }).click();
    await expect(page.getByTestId('floor-attention-rule')).toContainText('3층 · 주목도 Y 계수 0.8 (모델 가정)');
    const attentionText = await page.getByTestId('floor-attention-rule').innerText();
    await page.getByRole('button',{ name:'근거 닫기', exact:true }).click();
    await page.setViewportSize({ width:390,height:844 });
    const mobileTotals = await page.locator('.mobile-cards [data-total]').evaluateAll(nodes => nodes.map(n => Number((n as HTMLElement).dataset.total)));
    expect(mobileTotals).toEqual(await totals());
    await page.locator('.mobile-cards').getByRole('button',{ name:'a 건물 앞 도로·맞은편에서의 간판 노출 근거', exact:true }).click();
    await expect(page.getByTestId('floor-attention-rule')).toHaveText(attentionText);
    await page.getByRole('button',{ name:'근거 닫기', exact:true }).click();
    await page.setViewportSize({ width:1440,height:1000 });
    expect(users).toHaveLength(1);
    const scoringCalls = () => rpc.filter(call => ['score_inputs', 'exposure_inputs_v022', 'score_reference_percentiles'].includes(call.name)).length;
    const selectionScoringBefore = scoringCalls(), selectionWorkerBefore = await page.locator('html').getAttribute('data-exposure-runs');
    const mapProof = await checkMap(page, scoringCoordinates);
    expect(scoringCalls()).toBe(selectionScoringBefore);
    expect(await page.locator('html').getAttribute('data-exposure-runs')).toBe(selectionWorkerBefore);
    const before = rpc.length;
    const exposureBefore = Number(await page.locator('html').getAttribute('data-exposure-runs') ?? '0');
    const performance = await page.evaluate(async () => {
      const input = document.querySelector<HTMLInputElement>('#desktop-demand')!;
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!;
      const times: number[] = [];
      input.dispatchEvent(new PointerEvent('pointerdown',{ bubbles:true }));
      for (let i=0; i<100; i++) {
        const start = window.performance.now(); setter.call(input,String(i%41));
        input.dispatchEvent(new Event('input',{ bubbles:true }));
        await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
        times.push(window.performance.now()-start);
      }
      input.dispatchEvent(new PointerEvent('pointerup',{ bubbles:true })); times.sort((a,b)=>a-b);
      return { samples:times.length, p95:times[94], max:times[99] };
    });
    console.log('slider-performance', JSON.stringify(performance));
    expect(performance.p95).toBeLessThanOrEqual(100);
    expect(rpc.length).toBe(before);
    expect(exposureBefore).toBeGreaterThan(0);
    expect(Number(await page.locator('html').getAttribute('data-exposure-runs') ?? '0')).toBe(exposureBefore);
    await expect(page.locator('#desktop-demand')).toHaveValue('17');
    await page.getByRole('button',{ name:'프리셋으로 저장', exact:true }).click();
    await page.getByLabel('프리셋 이름',{ exact:true }).fill('수요 17');
    await page.getByRole('button',{ name:'가중치 이름 저장', exact:true }).click();
    await expect(page.getByText('가중치 프리셋을 저장했습니다.',{ exact:true })).toBeVisible();
    const menu = page.locator('.desktop-matrix details').last();
    await menu.locator('summary').click();
    await menu.getByRole('button',{ name:'앞으로 이동',exact:true }).click();
    const changed = await totals();
    await page.getByRole('button',{ name:'비교 저장', exact:true }).click();
    await page.getByRole('button',{ name:'안내 확인하고 저장', exact:true }).click();
    await expect(page.getByText('비교를 저장했습니다. 같은 브라우저에서 다시 열 수 있습니다.',{ exact:true })).toBeVisible();
    const savedUrl = page.url();
    await page.reload();
    await expect(page.locator('.desktop-matrix [data-total]')).toHaveCount(5);
    await expect(page.locator('#desktop-demand')).toHaveValue('17');
    expect(await totals()).toEqual(changed); expect(users).toHaveLength(1); expect(page.url()).toBe(savedUrl);
    await page.getByLabel('가중치 프리셋',{ exact:true }).selectOption({ label:'학원 v0.4.0(기본)' });
    expect((await totals()).sort((a,b)=>a-b)).toEqual([...expected].sort((a,b)=>a-b));
    await page.getByLabel('가중치 프리셋',{ exact:true }).selectOption({ label:'수요 17' });
    await expect(page.locator('#desktop-demand')).toHaveValue('17');
    const comparisonId = new URL(savedUrl).searchParams.get('comparison')!;
    const persistedModel = async () => {
      const { data, error } = await admin.from('comparisons').select('scoring_model_version').eq('id',comparisonId).single();
      expect(error).toBeNull(); return data!.scoring_model_version;
    };
    expect(await persistedModel()).toBe('0.4.0');
    await expect(page.getByTestId('model-version-notice')).toHaveCount(0);
    for (const version of ['0.3', null]) {
      const { error } = await admin.from('comparisons').update({ scoring_model_version:version }).eq('id',comparisonId).eq('user_id',users[0]);
      expect(error).toBeNull();
      if (version === '0.3') await page.route('**/rest/v1/rpc/score_inputs', route => route.fulfill({
        status:503, contentType:'application/json', body:JSON.stringify({ message:'local test: scoring temporarily unavailable' }),
      }));
      await page.reload();
      const notice = page.getByTestId('model-version-notice');
      if (version === '0.3') {
        await expect(notice).toHaveAttribute('data-phase','failed');
        await page.unroute('**/rest/v1/rpc/score_inputs');
        await page.getByRole('button',{ name:'모델 재계산 다시 시도', exact:true }).click();
      }
      await expect(notice).toHaveAttribute('data-phase','complete');
      await expect(notice).toContainText(version === null ? '저장 당시 모델 미기록' : '저장 모델 v0.3');
      expect(await totals()).toEqual(changed);
      expect(await persistedModel()).toBe(version); // Calculation never silently saves the model tag.
      await page.getByRole('button',{ name:'비교 저장', exact:true }).click();
      await expect(notice).toHaveCount(0);
      expect(await persistedModel()).toBe('0.4.0');
    }
    await page.reload();
    await expect(page.locator('.desktop-matrix [data-total]')).toHaveCount(5);
    await expect(page.getByTestId('model-version-notice')).toHaveCount(0);
    expect(await totals()).toEqual(changed); expect(users).toHaveLength(1);
    expect(errors).toEqual([]);
    const evidence = { environment:'local real Auth/RPC/Worker/WebGL + fixed public provider and basemap responses', map:mapProof, coldMobileMapDeferred:true, sliderExposureRequests:0,
      userAgent:await page.evaluate(() => navigator.userAgent), totals:expected, confidence,
      slider:performance, rpc, checks:{ same_uid:true, saved_reopened:true, manual_order_restored:true, named_preset_raw_weights:true,
        model_version:'0.4.0', model_notice_legacy_unknown_same:true, model_failure_retry:true, model_tag_requires_save:true, five_candidates:true, mobile_totals:true, floor_elevator_evidence:true, attention_evidence:true } };
    await info.attach('comparison-proof', { body:JSON.stringify(evidence,null,2), contentType:'application/json' });
    const coldMobile = await browser.newContext({ viewport:{width:390,height:844}, storageState:await page.context().storageState() });
    const mobile = await coldMobile.newPage(); await mapFixture(mobile);
    const mobileRequests: string[] = []; mobile.on('request', request => mobileRequests.push(request.url()));
    await mobile.goto(savedUrl);
    await expect(mobile.locator('.mobile-cards [data-total]')).toHaveCount(5);
    await expect(mobile.getByTestId('compare-map')).toHaveCount(0);
    expect(mobileRequests.filter(url => url.includes('map.gilmok.test') || url.endsWith('/compare_map_context'))).toEqual([]);
    const mobileProof = await checkMobileTabs(mobile);
    console.log('mobile-navigation', JSON.stringify(mobileProof));
    await mobile.getByRole('tab',{name:'지도',exact:true}).click();
    await expect(mobile.getByTestId('compare-map')).toHaveAttribute('data-map-idle','true');
    await expect(mobile.locator('.map-context-status')).toContainText(/학교 \d+곳/);
    await coldMobile.close();
    console.log(JSON.stringify(evidence));
  } finally {
    // Delete only this test's new local Auth users; no service key reaches the browser.
    for (const uid of users) await admin.auth.admin.deleteUser(uid);
  }
});
