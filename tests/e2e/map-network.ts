import { expect, type Page } from '@playwright/test';

// Real MapLibre/WebGL and RPC; only CI's external basemap is deterministic.
export async function mapFixture(page: Page) {
  await page.route('https://map.gilmok.test/**', route => route.fulfill({ contentType: 'application/json',
    body: JSON.stringify({ version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#edf2ef' } }] }) }));
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
  await page.getByRole('button', { name: '같은 좌표 후보 3곳', exact: true }).click();
  const floors = page.getByRole('group', { name: '같은 좌표 후보 층 목록', exact: true });
  await expect(floors).toContainText('a · 3층'); await expect(floors).toContainText('d · 4층'); await expect(floors).toContainText('e · 1층');
  await floors.getByRole('button', { name: /d · 4층/ }).click();
  await expect(page.locator('.map-candidate-list').getByRole('button', { name: /d · 4층/ })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.maplibregl-ctrl-attrib')).toContainText('OpenFreeMap');
  await expect(page.locator('.maplibregl-ctrl-attrib')).toContainText('OpenStreetMap');
  const totals = await page.locator('.desktop-matrix [data-total]').evaluateAll(elements => elements.map(e => (e as HTMLElement).dataset.total));
  await page.route('**/rest/v1/rpc/compare_map_context', route => route.fulfill({ status: 503, contentType: 'application/json', body: '{"message":"map test outage"}' }));
  await page.locator('.map-candidate-list').getByRole('button', { name: /b · 2층/ }).click();
  await expect(page.locator('.map-context-status')).toContainText('자료를 불러오지 못했습니다');
  expect(await page.locator('.desktop-matrix [data-total]').evaluateAll(elements => elements.map(e => (e as HTMLElement).dataset.total))).toEqual(totals);
  await page.unroute('**/rest/v1/rpc/compare_map_context');
  await page.getByRole('button', { name: '주변 자료 다시 시도', exact: true }).click();
  await expect(page.locator('.map-context-status')).toContainText(/학교 \d+곳/);
  await expect(page.getByTestId('compare-map')).toHaveAttribute('data-map-idle', 'true');
  return { groups: groups.length, candidates: groups.flatMap(group => group.ids).length, exactScoringCoordinates: true, groupedFloors: [1, 3, 4], mapFailureIsolated: true };
}
