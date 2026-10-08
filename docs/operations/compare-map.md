# CompareMap 2D 운영

2026-10-07 · S3-3 A. [계획](../planning/s3-3-plan.md), [검증·migration hash](../validation/s3-3-a-20261007.md).

## 배포 순서와 사용자 단계

1. 원격 migration dry-run 보고 후 사용자 push 승인을 받는다. A는 새 read-only `compare_map_context(lat double precision,lng double precision)` 하나와 그 권한만 추가하며 기존 객체/행을 바꾸지 않는다.
2. push 직전 대상을 다시 확인한다. 승인된 hash와 파일 1개가 일치할 때 push한다. 별도 migration이 나타나면 멈추고 보고한다.
3. 익명 로그인 세션(authenticated)으로 a/b/c 좌표 RPC를 확인한다. center 정확 일치, 800/1000m 링, 역 1.2km·학교 1km, 기준일·결측 구분, anon EXECUTE 거부를 확인한다. SQL 첫 실행과 이후 30회 p95/HTTP를 분리 기록한다.
4. **사용자: Vercel Production·Preview에 공개 변수 `NEXT_PUBLIC_MAP_STYLE_URL=https://tiles.openfreemap.org/styles/liberty`를 추가하고 재배포한다.** Next.js의 공개 값은 빌드 때 고정된다. Supabase 공개 2개·주소 서버 키 설정은 [S3 기반 문서](s3-foundation.md)를 유지한다. style URL에는 비밀·토큰을 넣지 않는다. 새 지도 API 키/서버 비밀은 필요 없다.
5. Preview에서 등록/재열기→한글 지도·출처·반경·겹친 층 목록, 모바일 열기 전 지도 요청 0회, 타일 실패 시 점수/근거 유지 여부를 확인한다. 이후 사용자가 머지한다. B의 열 선택·모바일 3탭 마감은 별도 PR이다.

2026-10-07 A는 사용자 승인 후 원격 migration 적용과 실제 Preview 실증을 완료했다. 사용자가 공개 style URL을 Production·Preview에 등록했고 agent는 PR Preview만 재배포했다. [원격 수치·화면](../validation/s3-3-a-20261007.md#7-사용자-승인-후-원격-적용preview-실증)을 따른다. Production 지도 배포는 사용자 머지 이후이며 이 기록과 구분한다.

## 조회·원천 정책

- MapLibre4.7.1/내장 Worker·지도 CSS는 CompareMap 동적 모듈 안에만 둔다. desktop 비교 셸 표시 뒤 로드, mobile은 명시적 진입 뒤 로드한다. 저장된 후보를 포함해 `candidate.lat/lng`를 그대로 사용한다.
- 지도 RPC는 selected 후보의 초기 채점 종료 후 동시 1개만. `lat/lng + admin_boundaries/subway_positions/schools` fingerprint 기준 세션 메모리 캐시·진행 중 요청을 공유한다. 층·가중치·칩 같은 좌표 이동으로 새 서버 요청을 만들지 않는다.
- 새 함수는 공개 공간 원천만 SELECT한다. 사용자 후보·대장 큐·private geocode cache·score_inputs를 호출하거나 변경하지 않는다. 지도 원천 오류는 채점 결측으로 바꾸지 않는다.
- 좌표 없는 학교 수는 원천 전체 수다. 반경 안 개수로 추정하지 않는다. 서울 밖/원천 미적재/범위 내 0건을 구분한다. 지도 추정 원천은 팝업에서 표시한다.
- 지도 브라우저는 OpenFreeMap CDN을 직접 호출한다. 타일 요청에는 뷰 영역이 드러나지만 후보 별칭·임대료·uid·PNU를 URL/속성에 붙이지 않는다. [출처·이용 조건](../data-attribution.md#2d-배경-지도-s3-3-a-2026-10-07)을 유지한다.

## 오류·롤백

- style URL 누락, WebGL 불가, 타일 실패: 지도 영역에 상태·재시도 표시. 기존 비교 점수·근거·저장은 계속 사용할 수 있다. 지도 RPC는 15초 timeout이며 실패 응답은 캐시하지 않는다.
- 사용자별 원천·지도 캐시를 DB에 만들지 않는다. DB가 부담되면 먼저 지도 RPC 동시 1개와 실제 warm p95를 확인한다. 원격 Micro/공개 전 Small 조건은 기존 운영 문서를 따른다. 임의 compute·반경·원천 해상도 조정은 하지 않는다.
- 프론트 장애 롤백은 이전 Vercel 배포로 되돌린다. 추가 함수는 기존 클라이언트에서 호출하지 않으므로 그대로 남길 수 있다. 데이터 복원·DROP이 필요 없다.
- RPC를 임시 차단해야 하면 별도 운영 승인 후 `REVOKE EXECUTE ON FUNCTION public.compare_map_context(double precision,double precision) FROM authenticated;`를 실행하고 지도 오류 격리를 확인한다. 복구는 같은 시그니처에 `GRANT EXECUTE ... TO authenticated;`다. 배포 시 자동 실행하지 않는다.
- INGEST_REMOTE_ENABLED·주소 트리거·6시간 sweep·JUSO_COORD_ENABLED·AUTH_CLEANUP_ENABLED는 지도 배포에서 변경하지 않는다.

## 검증 재현

1. 로컬 Supabase에 migration을 적용한 뒤 `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm test:db`, `pnpm test:e2e`를 실행한다. 통합 테스트는 로컬 DB만 허용하며 rollback한다. E2E의 공급자/배경 style은 공개 고정 fixture, Auth/RPC/MapLibre/WebGL/노출 Worker는 실제다.
2. 같은 공개 환경변수로 #29/#30/A를 각각 production build하고 `/compare` HTML의 초기 script/link와 지도 비동기 파일을 나눈다. 파일별 `gzip(...,level=9,mtime=0)` 길이를 합산해 [기록 JSON](../validation/s3-3-a-20261007.json)의 목록과 대조한다. 소스맵·CDN 응답·API JSON을 앱 JS 예산에 섞지 않는다.
3. live 점검은 실제 Liberty URL로 production build/start, 새 BrowserContext에서 a 등록→첫 map idle을 측정한다. BrowserContext의 response/request.sizes로 Worker 타일까지 수집한다. page 단위 CDP Network만으로 합산하면 Worker 전송량이 누락될 수 있다. 공개 URL·상태·바이트만 기록하고 인증 헤더·토큰은 출력하지 않는다.
4. 모바일은 새 BrowserContext에서 열어 지도 진입 전 지도 chunk/style/tile/glyph/sprite/RPC 0회를 확인한다. desktop 지도 열린 a~e 5후보에서 슬라이더 100회×3세트 각각 p95≤100ms, 각 세트·전체 max 기록, RPC/노출 Worker scene 요청 증가 0회를 확인한다.

## 원격 검증 대상 고정

로컬 `.env`의 NEXT_PUBLIC_SUPABASE_URL/공개 키는 개발 DB일 수 있다. 원격 검증은 승인된 SUPABASE_PROJECT_REF·linked Session pooler와 원격 API origin의 일치를 먼저 확인한다. Preview의 실제 Supabase 요청 origin도 같은 프로젝트인지 검증한다. 로컬 HTTP 결과를 원격 실측에 넣지 않는다.

콜드 관측을 위해 migration 직후 새 함수의 직접 SQL을 HTTP보다 먼저 실행한다. 첫 호출과 이후30회를 분리하고 EXPLAIN BUFFERS의 shared hit/read를 함께 남긴다. DB 재시작·캐시 강제 초기화 없이 측정했으면 완전한 I/O 콜드라고 표시하지 않는다.

## S3-3 B 선택·모바일 운영 (2026-10-07)

[PR #32](https://github.com/hanbeulYou/Gilmok/pull/32)은 선택 동기화와 모바일3탭을 마감한다. [검증](../validation/s3-3-b-20261007.md)·[S3-4 인계](../planning/s3-3-plan.md#15-b-완료와-s3-3-마감)를 따른다. **새 migration/기존 DB 객체 변경/추가 환경변수/의존성 변경 없음**. 기존 지도 공개 URL을 그대로 사용하며 사용자 단계는 PR 검토·머지다. Preview 검증이 Production 반영을 뜻하지 않으며 main 배포는 머지 후다.

- 모바일의 임시 `지도 보기` 버튼을 매트릭스/지도/근거3탭으로 대체한다. 기본은 매트릭스, 첫 지도 진입 전 JS/CSS·지도 RPC·타일 요청0. 재진입은 같은 지도 인스턴스와 뷰를 보존하고 resize한다.
- 열/총점/카드/칩/마커는 같은 선택을 사용한다. 묶음 마커에서는 층 목록으로 후보를 고른다. 방향키·Home/End, 층 목록 Escape, 근거 닫기 시 이전 조작 위치 복귀를 지원한다.
- 모바일 출처는 후보 칩과 겹치지 않도록 자연스러운 흐름에 둔다. 화면 폭375/390/1024px에서 출처 링크와 탭·키보드 포커스를 확인한다.
- 회귀 확인은 실제 Auth/RPC/Worker의 a~e 점수, 선택만 변경 시 채점 호출0, 슬라이더 p95≤100ms/max 기록, 새 모바일 세션의 지도 미진입 요청0으로 한다. Realtime 검증의 ready 전환/선택 유지도 확인한다.
- 프론트 문제는 이전 Vercel 배포로 롤백한다. B는 DB 롤백이나 webhook/cron/좌표/정리 스위치 변경을 요구하지 않는다. 기존 Micro 유지·Small 전환 후 공개 합본 재시험 조건은 별개다.

## S3-4 P0 슬라이더 검증 정책 (2026-10-08)

- PR CI: `SLIDER_PERFORMANCE_POLICY=ci pnpm test:e2e`. 100회×3세트의 p95 중앙값≤100ms. 단일 세트의 초과도 숨기지 않고 p95/max·100개 원시 시간을 JSON/log에 기록한다. 실패해도 `e2e-proof` artifact를 14일 보존한다. 재시도는 0이며 실패 세트를 버리지 않는다.
- Production 빌드: `E2E_APP_MODE=production SLIDER_PERFORMANCE_POLICY=production pnpm test:e2e`. 로컬 Supabase·공개 주소/타일 fixture 환경에서 Next build/start로 실행하고 **3세트 각각 p95≤100ms**를 적용한다. 기본 정책도 production(엄격)이며 CI 변수로 제품 판정을 대체하지 않는다. 실제 배포·CDN·기기 검증 여부는 별도로 표기한다.
- 양쪽 모두 input→두 번의 rAF까지, nearest-rank p95(100개 중 index94)로 측정한다. 각 세트 전에 같은 5후보·가중치를 유지하고 지도 idle을 확인한다. 각 세트 후 가중치·점수·열 순서를 복원하고 실제 점수 변경·RPC/Worker 추가 호출0을 확인한다. 기존 standalone `verify_browser.py`도 같은 측정 함수를 사용하며 production 각 세트 기준으로 판정한다.
- 문서 전용 PR(`docs/**`, `**/*.md`, `**/*.mdx`, 루트 Markdown 포함)은 E2E 준비·브라우저/성능 테스트만 건너뛴다. lint/typecheck/test/build/test:db는 그대로 실행하고 main push는 전체 검증한다. Git 전체 diff에 코드·설정·삭제/이름 변경이 섞이거나 diff 판정이 불가능하면 E2E를 실행한다. 최상위 `paths-ignore`로 workflow 전체를 생략하지 않는다([GitHub 경로 필터 안내](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onpushpull_requestpull_request_targetpathspaths-ignore)).
- #33의 p95 116.8ms 실패는 사용자 확인 결과 CI 러너 변동이며 점수 정상이다. 재조사·과거 실패 소급 통과 처리 없이 [P0 신규 검증](../validation/s3-4-p0-20261008.md)을 기록한다.

## S3-4 P1 건물 3D 운영

- 동일 MapLibre 인스턴스에서 2D/3D를 전환한다. 선택 후보 중심 zoom17/pitch55°, 600ms easeTo. 2D 복귀는 이전 center/zoom/bearing을 복원하고 회전을 제한한다. reduced-motion은 즉시 전환한다. 화면 선택은 localStorage `gilmok-map-mode`에 기억한다(최초2D). 저장된3D 선호로 지도에 들어오면 3D 진입으로 처리한다.
- `BuildingScene3D`/표시 좌표 RPC는 최초3D 진입에만 로드한다. 2D나 근거만 보는 새 세션에는 추가3D JS/CSS·RPC·노출 Worker 요청0. 모바일도 건물3D까지 지원하며 deck.gl/샘플 오버레이는 P2다.
- 항상 “건물 3D 자료: 강남구 적재분” 및 현장 확인 문구를 표시한다. 전체1.23km 일부 미적재와 점수 링 범위 밖을 구분한다. 서울 밖·원천 미적재·적재 범위 안 관측0개는 서로 다른 안내다. 배경 타일 건물로 결측을 채우지 않는다.
- 새 Vercel 환경변수/라이브러리 없음. 기존 `NEXT_PUBLIC_MAP_STYLE_URL` 사용. 원격 `project_exposure_geometry`가 없거나 실패하면 점수를 보존하고 오류·재시도·2D 복귀를 제공한다.
- 배포: additive migration dry-run·hash·기존 객체 변경 여부 확인 → 사용자 push 승인 → 원격 SQL30회/익명 로그인 HTTP 및 Preview 3D 확인 → 사용자 PR 머지. [P1 검증](../validation/s3-4-p1-20261008.md)을 따른다.
- 롤백: 프론트 P1 되돌리기 또는 새 함수 EXECUTE 회수 후 2D 사용. 이 함수에는 데이터가 없으며 기존 후보/비교/주소/원천 행을 수정하지 않는다.

```sql
-- 새 표시 기능만 비활성화. 기존 객체/행은 보존한다.
REVOKE EXECUTE ON FUNCTION public.project_exposure_geometry(jsonb) FROM authenticated;
-- 프론트가 2D로 복귀한 뒤 새 함수 자체를 제거할 때만 실행한다.
DROP FUNCTION public.project_exposure_geometry(jsonb);
```

FPS 실측은 M5 Pro 실제 GPU·AC 전원·저전력 해제·60Hz 화면·Chrome foreground·1440×1000CSSpx/DPR2에서 production build/start로 한다. `E2E_APP_MODE=production E2E_REAL_GPU=1 E2E_REAL_MAP_STYLE=1 BUILDING_3D_FPS=1 SLIDER_PERFORMANCE_POLICY=production pnpm test:e2e`. 실제 renderer를 확인하고 SwiftShader를 거부한다. zoom17/14.5에서 각각60초×3회, 회전/팬/줌 중 Map render 간격·rAF·Chrome frame trace와 보이는 건물 수를 남긴다. 각 회 평균≥55fps, render 간격p95≤33.4ms, 50ms초과 비율≤1%. P1은 건물만이며 P2 오버레이를 포함한 재측정은 별도다. 내장 GPU 일반 노트북 검증은 공개 전 체크리스트에 남긴다.

2026-10-08 P1: 사용자 요청으로 실제 GPU FPS 측정을 보류했다. 기능·번들·dry-run은 [검증 문서](../validation/s3-4-p1-20261008.md)에 기록하고 Draft를 유지한다. 사용자의 AC/60Hz 환경 설정 완료 통보 후 위 명령을 실행하며, headless E2E 통과를 FPS 통과로 대체하지 않는다.
