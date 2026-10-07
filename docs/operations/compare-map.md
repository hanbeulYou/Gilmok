# CompareMap 2D 운영

2026-10-07 · S3-3 A. [계획](../planning/s3-3-plan.md), [검증·migration hash](../validation/s3-3-a-20261007.md).

## 배포 순서와 사용자 단계

1. 원격 migration dry-run 보고 후 사용자 push 승인을 받는다. A는 새 read-only `compare_map_context(lat double precision,lng double precision)` 하나와 그 권한만 추가하며 기존 객체/행을 바꾸지 않는다.
2. push 직전 대상을 다시 확인한다. 승인된 hash와 파일 1개가 일치할 때 push한다. 별도 migration이 나타나면 멈추고 보고한다.
3. 익명 로그인 세션(authenticated)으로 a/b/c 좌표 RPC를 확인한다. center 정확 일치, 800/1000m 링, 역 1.2km·학교 1km, 기준일·결측 구분, anon EXECUTE 거부를 확인한다. SQL 첫 실행과 이후 30회 p95/HTTP를 분리 기록한다.
4. **사용자: Vercel Production·Preview에 공개 변수 `NEXT_PUBLIC_MAP_STYLE_URL=https://tiles.openfreemap.org/styles/liberty`를 추가하고 재배포한다.** Next.js의 공개 값은 빌드 때 고정된다. Supabase 공개 2개·주소 서버 키 설정은 [S3 기반 문서](s3-foundation.md)를 유지한다. style URL에는 비밀·토큰을 넣지 않는다. 새 지도 API 키/서버 비밀은 필요 없다.
5. Preview에서 등록/재열기→한글 지도·출처·반경·겹친 층 목록, 모바일 열기 전 지도 요청 0회, 타일 실패 시 점수/근거 유지 여부를 확인한다. 이후 사용자가 머지한다. B의 열 선택·모바일 3탭 마감은 별도 PR이다.

현재 A는 로컬/실제 공개 CDN 검증과 원격 dry-run까지다. 원격 DB push·Vercel 지도 배포 확인으로 표현하지 않는다.

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
4. 모바일은 새 BrowserContext에서 열어 지도 진입 전 지도 chunk/style/tile/glyph/sprite/RPC 0회를 확인한다. desktop 지도 열린 a~e 5후보에서 슬라이더 100회 p95≤100ms, max 기록, RPC/노출 Worker scene 요청 증가 0회를 확인한다.
