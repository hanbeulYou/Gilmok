# 신규 등록 Juso 좌표 전환 로컬 검증 — 2026-10-16

base: main (`9023d75`). 원격 DB/R2 변경0, 기존 데이터 교체/삭제0. 실제 API 응답은 로컬에만 보관하며 좌표·키·개인 uid를 이 문서에 게시하지 않는다. 로컬 실증은 국내 IP이며 Vercel/해외 DB 저장 조건을 검증한 결과가 아니다.

## 구현과 실제 공개 주소 조회

새 TypeScript `createAddressProvider`를 컴파일하여 실제 Juso 검색/선택 재검색/좌표 API를 호출했다. 투영 콜백은 격리 로컬 DB의 새 `project_juso_coordinate`, 이후 기존 `resolve_candidate_location`을 READ ONLY로 호출했다. 검색6회·좌표3회, HTTP200 및 업무코드0 전부 성공. Vworld0회, 후보/공용 캐시 저장0회. API HTTP 시간은 검색27.53~105.09ms, 좌표22.23~25.75ms(각3/6건 단발; p95 성능 통과 측정으로 쓰지 않음).

| 주소 | PNU | 검색 / 좌표 HTTP | 도형 검증 / 출입구 ST_Covers | 과거 Vworld 출입구와 거리 |
|---|---|---|---|---|
| 역삼로 460 | 1168010600109120013 | 200 / 200 | matched / true | 0.036463m |
| 도곡로 409 | 1168010600109380022 | 200 / 200 | matched / true | 0.119462m |
| 역삼로 546 | 1168010600109670000 | 200 / 200 | matched / true | 0.157037m |

세 곳 모두 선택 건물관리번호가 좌표 응답과 일치하고 EPSG:5179→4326 좌표가 해당 PNU 도형 안에 있다. Juso와 Vworld 출입구 수치는 완전히 같지 않다. 기존 resolve RPC는 입력 좌표를 그대로 반환하며 중심으로 이동시키지 않는다. 이번 PR은 새 등록 공급자만 바꾼다. 과거 저장 후보/검증 fixture의 도형 중심을 자동 교체하거나 점수 동일성을 주장하지 않는다. 기존 데이터 재산출·8축 영향은 별도 승인 후 계획대로 수행한다.

## 검사

- `pnpm lint`, `pnpm typecheck`, `pnpm test` 통과: Vitest205, Python269.
- 로컬 DB 관련 테스트4개 통과: 기존 Vworld 카운터 호환, Juso 검색60+좌표40=총100 및 101회 거부, 다른 uid 독립, private table 접근 거부, authenticated 투영 허용/anon 거부, EPSG5179 원점(1000000,2000000)→(127.5,38), NULL/NaN/Infinity/범위 밖 거부.
- 어댑터7개: 유일 건물관리번호, 위조 선택 거부, 무효/복수/0건, 투영 실패, no-store, Juso 분리 쿼터, 키/한도 실패 시 호출0, 비밀 로그 보호. 기존 사용자 저장 계약/provider 타입은 유지한다.
- 새 DB `gilmok_juso_registration_20261016`은 기준 격리 DB의 복제이며 새 migration을 로컬 적용했다. 원격·기준 DB를 변경하지 않았다.

## 원격 dry-run (적용 안 함)

**기존 객체 변경 있음:** 호출량 새 열(default0) 추가 + 기존 `claim_address_call(text)` 본문 교체. 투영 RPC 추가. 트리거 추가/변경0, 기존 좌표/행/열 삭제0.

- `supabase db push --dry-run --db-url <remote session pooler>` exit0.
- 대상은 `20261016021224_juso_registration_coordinates.sql` **1개**.
- SHA256: `b904c835d1695ad439a2737a552071face389a40aa96d734ae170de92cc576df`.
- 로컬 복제 DB는 migration 이력이 없어서 CLI dry-run이 전체 과거 목록을 보인다. 그 목록을 실제 push하지 않았으며 로컬에는 새 SQL만 적용했다. 원격 dry-run의 단일 pending 결과와 구분한다.

원격 push/Preview·Production 실증은 승인 대기다. 해외 저장 회신을 기다리는 기존 #39 승격도 이 검증으로 승인된 것이 아니다. [기존 데이터 목록·롤백/배포 계획](../planning/juso-registration-retirement-plan.md).
