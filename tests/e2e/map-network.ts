import { expect, type Page } from '@playwright/test';
// Real MapLibre/WebGL and RPC; only CI's external basemap is deterministic.
export async function mapFixture(page: Page) {
  await page.route('https://map.gilmok.test/**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({
    version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#edf2ef' } }],
  }) }));
}
export async function checkMap(page: Page, scoringCoordinates: number[][]) {
  await expect(page.getByTestId('compare-map')).toHaveAttribute('data-map-idle', 'true');
  await expect(page.locator('.map-context-status')).toContainText(/학교 \d+곳/);
  const markers = page.locator('.map-candidate');
  await expect(markers).toHaveCount(3);
  const groups = await markers.evaluateAll(elements => elements.map(element => ({
    coordinate: JSON.parse((element as HTMLElement).dataset.coordinate!), ids: JSON.parse((element as HTMLElement).dataset.candidateIds!),
  })));
  for (const group of groups) expect(scoringCoordinates).toContainEqual(group.coordinate);
  expect(groups.flatMap(group => group.ids).sort()).toEqual(await page.locator('.desktop-matrix th[data-candidate-id]').evaluateAll(elements => elements.map(e => (e as HTMLElement).dataset.candidateId!).sort()));
  const header = (alias: string) => page.locator('.desktop-matrix .candidate-name').filter({ hasText: new RegExp(`^${alias} ·`) });
  const grouped = page.getByRole('button', { name: '같은 좌표 후보 3곳', exact: true });
  await header('a').click();
  await expect(grouped).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('button', { name: '근거 닫기', exact: true })).toHaveCount(0);
  await header('a').press('Home');
  await expect(page.locator('.desktop-matrix .candidate-name').first()).toBeFocused();
  await header('a').click();
  await grouped.focus(); await grouped.press('Enter');
  const floors = page.getByRole('group', { name: '같은 좌표 후보 층 목록', exact: true });
  await expect(floors).toContainText('a · 3층'); await expect(floors).toContainText('d · 4층'); await expect(floors).toContainText('e · 1층');
  await expect(floors.getByRole('button', { name: /a · 3층/ })).toBeFocused();
  await floors.getByRole('button', { name: /a · 3층/ }).press('Escape');
  await expect(floors).toHaveCount(0); await expect(grouped).toBeFocused();
  await grouped.press('Enter'); await floors.getByRole('button', { name: /d · 4층/ }).click();
  await expect(grouped).toBeFocused(); await expect(header('d')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.desktop-matrix [data-selected=true]')).toHaveCount(10);
  await expect(page.locator('.map-candidate-list').getByRole('button', { name: /d · 4층/ })).toHaveAttribute('aria-pressed', 'true');
  const single = markers.filter({ hasText: /^1$/ });
  await single.click(); await expect(header('b')).toHaveAttribute('aria-pressed', 'true');
  await expect.poll(() => page.locator('.matrix-scroll').evaluate(scroll => {
    const selected = scroll.querySelector('th[data-selected=true] .candidate-name')!.getBoundingClientRect();
    const sticky = scroll.querySelector('th')!.getBoundingClientRect();
    return selected.left >= sticky.right && selected.right <= scroll.getBoundingClientRect().right;
  })).toBe(true);
  await page.getByRole('button', { name: 'a 총점으로 후보 선택', exact: true }).first().click();
  await expect(header('a')).toHaveAttribute('aria-pressed', 'true'); await expect(grouped).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.maplibregl-ctrl-attrib')).toContainText('OpenFreeMap');
  await expect(page.locator('.maplibregl-ctrl-attrib')).toContainText('OpenStreetMap');
  const totals = await page.locator('.desktop-matrix [data-total]').evaluateAll(elements => elements.map(e => (e as HTMLElement).dataset.total));
  // c has not been selected: exercise an uncached context failure without touching scoring.
  await page.route('**/rest/v1/rpc/compare_map_context', route => route.fulfill({ status: 503, contentType: 'application/json', body: '{}' }));
  await page.locator('.map-candidate-list').getByRole('button', { name: /c · 3층/ }).click();
  await expect(page.locator('.map-context-status')).toContainText('자료를');
  expect(await page.locator('.desktop-matrix [data-total]').evaluateAll(elements => elements.map(e => (e as HTMLElement).dataset.total))).toEqual(totals);
  await page.unroute('**/rest/v1/rpc/compare_map_context'); await page.getByRole('button', { name: '주변 자료 다시 시도', exact: true }).click();
  await expect(page.locator('.map-context-status')).toContainText(/학교 \d+곳/);
  await expect(page.getByTestId('compare-map')).toHaveAttribute('data-map-idle', 'true');
  return { markerGroups: groups.length, candidates: groups.flatMap(group => group.ids).length, groupedFloors: [1, 3, 4], coordinateMatch: true, selectionBothDirections: true, keyboardFocus: true, contextFailureIsolated: true };
}
export async function checkMobileTabs(page: Page) {
  const tab = (name: string) => page.getByRole('tab', { name, exact: true });
  await expect(tab('매트릭스')).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('#compare-panel-map')).toBeHidden();
  await tab('매트릭스').press('ArrowRight');
  await expect(tab('지도')).toBeFocused();
  await expect(page.getByTestId('compare-map')).toHaveAttribute('data-map-idle', 'true');
  await expect(page.locator('.map-context-status')).toContainText(/학교 \d+곳/);
  await page.locator('.maplibregl-canvas').evaluate(node => node.setAttribute('data-preserved', 'yes'));
  await page.locator('.map-candidate-list').getByRole('button', { name: /a · 3층/ }).click();
  await expect(tab('지도')).toHaveAttribute('aria-selected', 'true');
  await tab('근거').click();
  await expect(page.locator('.evidence-panel')).toContainText('a');
  await expect(page.locator('#compare-panel-map')).toBeHidden();
  await page.getByRole('button', { name: '근거 닫기', exact: true }).click();
  await expect(tab('지도')).toHaveAttribute('aria-selected', 'true'); await expect(tab('지도')).toBeFocused();
  await expect(page.locator('.maplibregl-canvas')).toHaveAttribute('data-preserved', 'yes');
  await tab('지도').press('Home'); await expect(tab('매트릭스')).toBeFocused();
  await expect(page.locator('.selected-card .candidate-name')).toContainText('a · 3층');
  const axis = page.locator('.mobile-cards').getByRole('button', { name: 'a 건물 적합성 근거', exact: true });
  await axis.click(); await expect(page.locator('#evidence-heading')).toBeFocused();
  await page.getByRole('button', { name: '근거 닫기', exact: true }).click(); await expect(axis).toBeFocused();
  for (const width of [375, 390, 1024, 390]) {
    await page.setViewportSize({ width, height: 844 });
    if (width < 1024) await tab('지도').click();
    await expect(page.locator('.maplibregl-canvas')).toHaveAttribute('data-preserved', 'yes');
    if (width < 1024) expect(await page.evaluate(() => {
      const credits = document.querySelector('.maplibregl-ctrl-attrib')!.getBoundingClientRect();
      return document.querySelector('.map-candidate-list')!.getBoundingClientRect().top >= credits.bottom;
    })).toBe(true);
    expect(await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - innerWidth))).toBe(0);
    await expect.poll(() => page.evaluate(() => Boolean((document.activeElement as HTMLElement)?.getClientRects().length))).toBe(true);
  }
  await tab('지도').press('End'); await expect(tab('근거')).toBeFocused();
  await expect(page.locator('#compare-panel-matrix')).toBeHidden();
  return { widths: [375, 390, 1024], overflow: 0, threeTabs: true, singleMapInstance: true, evidenceReturnFocus: true };
}
