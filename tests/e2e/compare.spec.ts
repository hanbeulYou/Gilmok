import { expect, test } from '@playwright/test';
import { createClient } from '@supabase/supabase-js';
import { execFileSync } from 'node:child_process';
import fixtures from './fixtures/addresses.json';

test('a~e 등록 → v0.4.0 근거 → 슬라이더 → 익명 저장 → 같은 uid 재열기', async ({ page }, info) => {
  const users: string[] = [], rpc: { name:string; status:number }[] = [];
  const errors: string[] = [];
  const percentileResponses: unknown[] = [];
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
    const before = rpc.length;
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
    expect(performance.p95).toBeLessThanOrEqual(100);
    expect(rpc.length).toBe(before);
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
    expect(errors).toEqual([]);
    const evidence = { environment:'local real Auth/RPC/Worker + fixed public provider responses',
      userAgent:await page.evaluate(() => navigator.userAgent), totals:expected, confidence,
      slider:performance, rpc, checks:{ same_uid:true, saved_reopened:true, manual_order_restored:true, named_preset_raw_weights:true,
        model_version:'0.4.0', five_candidates:true, mobile_totals:true, floor_elevator_evidence:true, attention_evidence:true } };
    await info.attach('comparison-proof', { body:JSON.stringify(evidence,null,2), contentType:'application/json' });
    console.log(JSON.stringify(evidence));
  } finally {
    // Delete only this test's new local Auth users; no service key reaches the browser.
    const local = JSON.parse(execFileSync('supabase',['status','-o','json'],{ encoding:'utf8', stdio:['ignore','pipe','ignore'] }));
    const admin = createClient(local.API_URL,local.SERVICE_ROLE_KEY,{ auth:{ persistSession:false,autoRefreshToken:false } });
    for (const uid of users) await admin.auth.admin.deleteUser(uid);
  }
});
