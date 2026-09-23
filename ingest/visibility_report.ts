/** Node proof and human-readable field comparison; pure engine has no IO/timers. */
import { readFileSync, writeFileSync } from 'node:fs';
import { computeVisibility } from '../lib/visibility/compute.ts';
import { bounds } from '../lib/visibility/geometry.ts';
import { score } from '../lib/scoring/score.ts';
import { loadPreset } from '../lib/scoring/presets.ts';
import type { Candidate, ScoreContext, ScoreInputs, ScoreReference } from '../lib/scoring/types.ts';
import type { VisibilityScene } from '../lib/visibility/types.ts';
const [input, output, markdown] = process.argv.slice(2);
if (!input || !output || !markdown) throw new Error('Expected input, output, markdown paths');
const data: { scene: VisibilityScene; primary: ScoreInputs; school: ScoreInputs; candidate: Candidate;
  context: ScoreContext; reference: ScoreReference } = JSON.parse(readFileSync(input, 'utf8'));
for (let i = 0; i < 3; i++) computeVisibility(data.scene);
const durations: number[] = [];
for (let i = 0; i < 30; i++) { const start = performance.now(); computeVisibility(data.scene); durations.push(performance.now() - start); }
const result = computeVisibility(data.scene);
if (result.status !== 'ready') throw new Error(result.reason);
const scored = score(data.primary, data.school, data.scene.buildings, result, data.candidate,
  loadPreset('academy_v0', data.primary.meta.radius_m), data.reference, data.context);
const sorted = [...durations].sort((a, b) => a - b);
const timing = { samples: 30, warmups: 3, median_ms: (sorted[14] + sorted[15]) / 2, p95_ms: sorted[28], max_ms: sorted[29], runs_ms: durations };
writeFileSync(output, JSON.stringify({ result, score: scored, node_timing: timing }, null, 2) + '\n');
const state = { visible: '가시', blocked: '차폐', excluded: '제외' };
const lines = [
  '# 역삼로 460 3층 노출 조건 v0.2 — 현장 대조표', '',
  `후보 (${data.candidate.lat}, ${data.candidate.lng}), 목표 높이 8.6m, 눈높이 1.5m.`,
  `visible_ratio **${result.visible_ratio.toFixed(8)} (${(100 * result.visible_ratio).toFixed(4)}%)**, exposure 점수 **${(100 * result.visible_ratio).toFixed(4)}**.`,
  `후보 도형: ${data.scene.candidate_building_id}. 건물 ${data.scene.buildings.length}개, 학교 ${data.scene.schools.length}곳.`,
  '', '관찰점의 높이가 1.5m일 때 간판 목표점까지의 직선 시선 모델이다. 역·학교 대표점 사이의 직선이며 실제 보도/출입구 경로가 아니다. 5186 격자 북쪽=0°, 동쪽=90°, 남쪽=180°, 서쪽=270°다. 지형은 반영하지 않는다.',
  '', '건물 출처: 국토교통부 GIS건물통합정보(Vworld), SHP 2026-09-06(CC BY) 및 WFS 보조 2026-09-20. 길목에서 좌표 변환·도형 수리·높이 추정. [출처와 이용 조건](../data-attribution.md).',
  '', '가시=시선 교차 없음, 차폐=다른 건물과 교차, 제외=관찰점이 바깥으로 30m 안에 나올 수 없어 계산 분모에서도 제거됨. 차폐 건물 ID는 시선을 가리는 건물 중 ID 순 첫 건이며 가장 가까운 건물이라는 뜻은 아니다.',
  '', '가로수·가로시설물·간판 크기 미반영, 현장 확인 필요', '', '| 집합 | 생성 | 이동 | 가시 | 차폐 | 제외 | 제외율 | 유효 가중치 | 가시 가중치 |', '|---|---:|---:|---:|---:|---:|---:|---:|---:|',
  ...Object.entries(result.summary).map(([group, s]) => `| ${group} | ${s.generated} | ${s.moved} | ${s.visible} | ${s.blocked} | ${s.excluded} | ${(s.excluded_ratio * 100).toFixed(2)}% | ${s.total_weight.toFixed(6)} | ${s.visible_weight.toFixed(6)} |`),
];
for (const station of data.scene.stations) {
  const samples = result.samples.filter(s => s.group === 'station' && s.anchor_id === station.id);
  const count = (status: string) => samples.filter(s => s.status === status).length;
  lines.push('', `## ${station.name} (${station.line}) — ${station.id}`, '',
    `후보로부터 ${station.distance_m.toFixed(2)}m. **20점 중 가시 ${count('visible')}점 / 차폐 ${count('blocked')}점 / 제외 ${count('excluded')}점**. 이동 ${samples.filter(s => s.moved_m > 0).length}점.`,
    '번호는 후보에서 역 방향으로 증가한다. 동/북 좌표는 이동 후 후보 기준 미터이며 이동거리는 원래 샘플로부터의 바깥 방향 이동이다.', '',
    '| 번호 | 동쪽(m) | 북쪽(m) | 이동(m) | 판정 | 차폐/제외 건물 ID |', '|---:|---:|---:|---:|---|---|',
    ...samples.map(s => `| ${s.step} | ${(s.point[0] - data.scene.candidate[0]).toFixed(2)} | ${(s.point[1] - data.scene.candidate[1]).toFixed(2)} | ${s.moved_m.toFixed(3)} | ${state[s.status]} | ${s.building_id ?? '—'} |`));
}
if (!data.scene.stations.length) lines.push('', '1km 내 역 없음: 역 동선 집합 없음.');
lines.push('', '## 링 방향별 판정', '', '괄호는 바깥 방향 이동거리(m). 표의 반경은 원래 반경이며 가중치도 원래 반경 기준이다.', '',
  '| 방위각 | 30m | 60m | 100m |', '|---:|---|---|---|');
for (let bearing = 0; bearing < 360; bearing += 10) lines.push(`| ${bearing}° | ` +
  [30, 60, 100].map(r => { const s = result.samples.find(s => s.id === `ring:${bearing}:${r}`)!; return state[s.status] + (s.moved_m ? ` (+${s.moved_m.toFixed(2)})` : ''); }).join(' | ') + ' |');
lines.push('', '## 시간과 한계', '', `Node 순수 계산: 준비 3회, 측정 30회. 중앙값 ${timing.median_ms.toFixed(3)}ms, p95 ${timing.p95_ms.toFixed(3)}ms, 최댓값 ${timing.max_ms.toFixed(3)}ms.`,
  `근거: ${result.evidence.notes.join(', ')}.`,
  '', '건물/기준 분포 snapshot과 브라우저 Worker 시간·일치 검증은 동반 검증 문서를 따른다. 이 결과는 현장과 대조할 모델 출력이며 현장 검증 완료를 뜻하지 않는다.');
writeFileSync(markdown, lines.join('\n') + '\n');
// Standalone metric plan view for field comparison (not a map/style dependency).
const width = 1200, height = 820;
const points = [...data.scene.stations.map(s => s.point),
  [data.scene.candidate[0] - 150, data.scene.candidate[1] - 150],
  [data.scene.candidate[0] + 150, data.scene.candidate[1] + 150]];
const minX = Math.min(...points.map(p => p[0])), maxX = Math.max(...points.map(p => p[0]));
const minY = Math.min(...points.map(p => p[1])), maxY = Math.max(...points.map(p => p[1]));
const scale = Math.min(1060 / (maxX - minX), 570 / (maxY - minY));
const cx = 600 + (data.scene.candidate[0] - (minX + maxX) / 2) * scale;
const cy = 415 - (data.scene.candidate[1] - (minY + maxY) / 2) * scale;
const escapeXml = (v: string) => v.replace(/[<>&"']/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&apos;' })[c]!);
const xy = (p: readonly number[]) => [cx + (p[0] - data.scene.candidate[0]) * scale,
  cy - (p[1] - data.scene.candidate[1]) * scale];
const colors = { visible: '#13834b', blocked: '#d24a28', excluded: '#a0a5ac' };
const svg = [`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`,
  '<rect width="1200" height="820" fill="#fff"/>',
  '<style>text{font-family:Arial,sans-serif;font-size:12px} .title{font-size:22px;font-weight:bold}</style>',
  '<defs><clipPath id="map"><rect x="15" y="75" width="1170" height="680"/></clipPath></defs>',
  `<text x="25" y="32" class="title">역삼로 460 · 3층 · 노출비율 ${(result.visible_ratio * 100).toFixed(4)}%</text>`,
  '<text x="25" y="56">초록: 가시 · 주황: 차폐 · 회색: 30m 이동 불가 | 원: 링 샘플 · 네모/번호: 후보→각 역 20점</text>',
  '<a href="https://github.com/hanbeulYou/Gilmok/blob/main/docs/data-attribution.md"><text x="25" y="71" style="font-size:10px">출처: 국토교통부 GIS건물통합정보(Vworld), SHP 2026-09-06 CC BY + WFS 2026-09-20 · 길목: 좌표 변환·도형 수리·높이 추정</text></a>',
  '<g clip-path="url(#map)">'];
for (const b of data.scene.buildings) {
  const box = bounds(b.polygons), [left, bottom] = xy(box.slice(0, 2)), [right, top] = xy(box.slice(2));
  if (right < 15 || left > 1185 || bottom < 75 || top > 755) continue;
  const path = b.polygons.map(p => p.map(r => r.map((point, i) => `${i ? 'L' : 'M'}${xy(point).map(v => v.toFixed(1)).join(',')}`).join(' ') + 'Z').join(' ')).join(' ');
  svg.push(`<path d="${path}" fill="${b.id === data.scene.candidate_building_id ? '#90c8f6' : '#f4f4f4'}" stroke="#d5d5d5" stroke-width=".5" fill-rule="evenodd"/>`);
}
for (const radius of [30, 60, 100]) svg.push(`<circle cx="${cx}" cy="${cy}" r="${radius * scale}" fill="none" stroke="#68788c" stroke-width=".7"/><text x="${cx + 5}" y="${cy - radius * scale - 4}">${radius}m</text>`);
for (const station of data.scene.stations) {
  const [x, y] = xy(station.point);
  svg.push(`<path d="M${cx},${cy} L${x},${y}" fill="none" stroke="#9167b9" stroke-dasharray="4 3"/><text x="${x - 20}" y="${y - 16}">${escapeXml(station.name)} (${escapeXml(station.line ?? "")})</text>`);
}
for (const s of result.samples.filter(s => s.group !== 'school')) {
  const [x, y] = xy(s.point), color = colors[s.status];
  if (s.group === 'ring') svg.push(`<circle cx="${x}" cy="${y}" r="3.4" fill="${color}" stroke="white" stroke-width=".7"/>`);
  else svg.push(`<rect x="${x - 4}" y="${y - 4}" width="8" height="8" fill="${color}" stroke="white"/><text x="${x - 3}" y="${y - 10}">${s.step}</text>`);
}
svg.push(`<circle cx="${cx}" cy="${cy}" r="4" fill="#1762b0"/><text x="${cx + 10}" y="${cy + 15}">후보</text>`);
for (const bearing of [0, 90, 180, 270]) {
  const a = bearing * Math.PI / 180;
  svg.push(`<text x="${cx + Math.sin(a) * 125 * scale - 12}" y="${cy - Math.cos(a) * 125 * scale}">${bearing}°</text>`);
}
svg.push('</g>', '<text x="25" y="780">가로수·가로시설물·간판 크기 미반영, 현장 확인 필요 · 북쪽 위 / 동쪽 오른쪽 · EPSG:5186 미터 평면</text>',
  `<text x="25" y="801">역 ${data.scene.stations.length}곳 ×20점: 가시 ${result.summary.station.visible}, 차폐 ${result.summary.station.blocked}, 제외 ${result.summary.station.excluded} · 학교 ${result.summary.school.generated}점은 도표 혼잡을 줄이기 위해 그림에서만 생략(가시율에는 포함)</text>`, '</svg>');
writeFileSync(markdown.replace(/\.md$/, '.svg'), svg.join('\n') + '\n');
console.log(JSON.stringify({ visible_ratio: result.visible_ratio, summary: result.summary, node_timing: timing }));
