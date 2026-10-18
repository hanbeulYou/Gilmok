# 학원 점 레이어 B — 합성 UI 검증

2026-10-18 · base `main 9023d75` · `s3/academy-layer-ui` · **Draft / G 원격 승격 전 Ready 금지**

합성 fixture만 사용했다. 원격·로컬 실데이터 DB와 R2는 읽거나 쓰지 않았고, 외부 주소 API도 호출하지 않았다. 모든 테스트 데이터 요청은 Playwright에서 차단·합성 응답하며, 허용하지 않은 요청은 실패시킨다. 지도는 실제 MapLibre 렌더러에 합성 배경 스타일을 사용한다. 이 결과를 실제 RPC·타일·production 네트워크 성능으로 해석하지 않는다.

**마이그레이션 없음. 기존 DB 객체 변경 없음. 원격 dry-run/push 없음.** 아직 Draft인 A(#41)의 `lib/map/academies.ts` 계약과 단위 테스트를 동일한 내용으로 재사용하고, B에서 선택 취소용 `cancel()`만 추가했다. 원격 공개는 G 게시 → A RPC 적용 → B 실데이터 검증 순서다.

## 구현과 검증

| 항목 | 결과 |
|---|---|
| 표시 | 선택 후보 1곳, 줌 ≥15, MapLibre GeoJSON source + circle 3개. 기관 DOM Marker 0. 다른 분야 옅은 보라 / 같은 분야 진한 보라 / 보류 주황 외곽선 |
| 합성 입력 | 1,500기관, 분야별 500, 보류 99(동일 분야 33), 동일 좌표 10기관. 명시/미표기/모호층 및 HTML처럼 생긴 공개 기관명 포함 |
| 반경 N | 800m, cluster `n_field=500` = RPC 동일분야 수 500 = 지도 N 500 = 근거 `반경 500곳`. 보류 기관도 포함 |
| 화면 M | `queryRenderedFeatures`의 고유 기관 ID를 같은 분야로 집계. 데스크톱 2D 검증 뷰 M=345. pan/zoom 후 idle·moveend에서 갱신하므로 N과 별개 |
| 팝업 | 공개 기관명·분야·명시층만. 미표기/모호층은 `층 미표기`. 보류 배지와 `점수에서 자동 제외하지 않습니다.`. 상세주소·전화·대표자 미표시, React text escaping 확인 |
| 동일 좌표 | 한 팝업 안에서 겹친 기관 선택. 기관 ID를 합치거나 점수에서 빼지 않음 |
| 후보 전환 | 250ms debounce. 이전 HTTP abort 확인, 늦은 이전 상태가 새 ready를 덮지 않음. 최근 5개 완료 응답 메모리 캐시, uid 변경/언마운트 시 폐기 |
| 줌 <15 | 레이어 숨김 + 팝업 닫기. GeoJSON/완료 데이터 유지. 다시 확대해도 RPC 추가 0 |
| 결측/상태 | too_dense / coordinate_replacement_pending / source_mismatch / outside_coverage 각 다른 안내. 오류/미확인과 0건 구분. 응답 N이 채점 N과 다르면 점을 표시하지 않음 |
| 모바일 | 첫 화면 지도/학원 번들·RPC 0. 지도 탭 진입 후 N=500, 노출 오버레이 미진입 유지 |
| 노출 오버레이 | 884개 합성 건물 + 108샘플 + 1,500기관 동시 표시. 동일 픽셀에서 실제 deck pick과 academy hit를 모두 확인한 후 노출 샘플 선택만 실행, 기관 팝업 0. 별도 기관 클릭은 팝업 표시 |
| 출처 | 서울특별시교육청/OA-20528(원천 NEIS), 공공누리 제1유형과 Juso 좌표를 별도 표시. 원천 제공 분야/개원 상태, 명시층·출입구 위치 한계, 서울 좌표 미확보 수 표시 |

테스트 중 MapLibre가 비숫자 GeoJSON 최상위 ID를 렌더 조회에 유지하지 않아 M=0이 되는 문제가 드러났다. 표시용 속성 `academy_id`에 **동일한 원본 ID**를 넣고 `promoteId`로 지정해 고쳤다. RPC 응답/점수/좌표는 바꾸지 않았다. 노출 샘플은 지면보다 1.5m 높으므로 중첩 클릭 검증도 deck viewport 투영으로 수행했다.

조회일은 `source.fetched_at`이 있을 때만 사용한다. 현재 계약에 별도 좌표 조회일이 없으므로 `미확인`으로 표시하며 적재일·revision을 조회일로 바꾸어 쓰지 않는다. 실제 RPC 응답은 이번 B에서 확인하지 않았다. G 이후 실제 자료의 조회일 계약 확인이 남아 있다.

## 번들·슬라이더

Next production build, Node 22.22.0 / 동일 공개 합성 환경변수. `.next/app-build-manifest.json`의 `/compare/page` JS 목록을 동일 방식으로 gzip 비교했다. 근거 패널도 열 때 lazy-load하도록 바꿔 첫 진입 증가를 없앴고, 패널 마운트 후 제목 포커스 이동을 유지했다.

| 측정 | 이전 | B | 판정 |
|---|---:|---:|---|
| `/compare` 초기 JS gzip | 200,651 B | 196,122 B | −4,529 B, 증가 0 |
| 학원 lazy JS gzip (계약·picker 포함) | — | 5,329 B | ≤15KiB |
| 학원 CSS gzip | — | 351 B | ≤2KiB |
| 지도 미진입 학원 JS/RPC | — | 0 / 0 | 통과 |

슬라이더는 실제 production build를 로컬 headless Chromium(software GPU)에서 실행했다. 학원 레이어를 표시한 상태에서 100회×3세트, 값 변화·원값/순위 복원·추가 학원 RPC 0을 함께 검증했다. 아래는 이 세 검증을 추가한 최종 재실행 수치다. 실제 배포된 production/GPU 실측과는 구분한다.

| 세트 | p95(ms) | max(ms) |
|---|---:|---:|
| 1 | 33.5 | 61.6 |
| 2 | 33.5 | 33.9 |
| 3 | 33.5 | 33.6 |

p95 중앙값 **33.5ms ≤100ms**, 전체 max **61.6ms**. 각 세트도 ≤100ms다. 직전 전체 기능 실행에서는 p95 33.8/33.9/34.0ms, 중앙값 33.9ms, max 51.3ms였다. 실패값을 버리거나 재시도로 통과시킨 결과가 아니다.

## FPS 미완료

2026-10-18 21:07:37 KST에 `pmset -g batt`, `system_profiler SPHardwareDataType`, CoreGraphics 화면 모드 및 `ProcessInfo.isLowPowerModeEnabled`를 다시 읽었다.

- Apple M5 Pro / AC Power / 배터리 100% / 저전력 모드 false.
- 내장 화면 **120.0Hz**, 논리 해상도 1512×982, DPR 2.
- 승인된 60Hz 조건과 달라 **FPS 측정은 실행하지 않았다**. OS 설정은 변경하지 않았다. FPS 테스트 skip은 통과가 아니다.

사용자가 60Hz 설정을 알려주면 사전 확인을 다시 수행한다. `ACADEMY_REAL_GPU=1 ACADEMY_FPS=1 pnpm test:e2e:academy --grep 'real GPU FPS'`는 하드웨어 조건을 읽고 불일치 시 중단한다. headed Chrome, viewport 1440×1000/DPR2, 2D 줌15 / 3D 줌17·pitch55(노출 포함), 합성 1,500기관·884건물, pan 60초×3회, 3초 워밍업 제외, **MapLibre render 이벤트** 간격을 집계한다. 실제 GPU renderer·평균 ≥55fps·p95 ≤33.4ms를 확인한 후 기록을 보완한다. M5 Pro가 아닌 CI software GPU 결과로 FPS 통과를 선언하지 않는다.

## 재현·완료 기준

`pnpm lint`, `pnpm typecheck`, `pnpm test` 통과(Vitest 231 / Python 단위 269). `pnpm test:e2e:academy`: 기능·슬라이더 **6 통과**, FPS **1 보류**. 이후 슬라이더 원값 복원/추가 요청 0 assertion을 추가한 단독 시험도 통과했다. CI에 동일 합성 E2E와 결과 artifact를 연결했다. 상세 수치와 원본 슬라이더 300회 값은 [JSON](academy-layer-b-20261018.json)을 따른다.

- [x] 선택 후보·줌·circle layer·분야 강조·N/M·최소 팝업·보류 배지.
- [x] 네 상태 안내, 취소/경합, 캐시 유지, 근거 N 일치.
- [x] 모바일, 2D/3D·노출 동시 표시, lazy/번들, 슬라이더 회귀.
- [ ] 승인 환경에서 2D/3D FPS 실측.
- [ ] G 원격 승격 및 A 적용 후 실제 a/b/c 800/1000m N·좌표·기관 표시·응답/렌더 성능 대조. 그 전 Ready/공개 금지.

다음 단계는 G의 Juso 회신·품질 자료·원천/층/기준분포/검토 플래그/release 원자적 승격 승인이다. 이후 실제 a/b/c 및 최대 밀도 셀로 다시 확인한다. 이 PR에는 원격 승격, Vworld/카카오 데이터·키 삭제, 채점 모델·기준분포 변경이 없다.
