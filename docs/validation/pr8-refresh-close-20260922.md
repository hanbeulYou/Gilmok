# PR 8 갱신 운영·S1 마감 검증 (2026-09-22)

base: main, PR 7 GitHub #10 이후. 원격 Supabase 전환·webhook 활성화·Secrets 업로드는 수행하지 않았다. score_inputs v1.2와 공개 RPC SQL은 변경하지 않았다.

## 실제 응답으로 확인한 사항

- MOIS 실제 2026-08 연령 CSV를 새로 다운로드하여 427개 서울 행정동 × 3연령대 = 1,281행으로 정규화했다. 5~9세 244,007명, 10~14세 341,692명, 15~18세 291,292명. 기존 인구 스냅샷과 데이터·source·source_version이 일치했다. 실제 원본→Parquet 게시→재읽기→기존 loader를 로컬 트랜잭션 안에서 실행하고 **롤백**했다. 활성 데이터는 바뀌지 않았다. PR 8에서 R2 새 원본 게시를 검증한 것은 아니며 이 확인은 로컬 RawStore를 썼다.
- 서울 생활인구 OA-22784 실제 목록에서 `250_LOCAL_RESD_202606.zip`, `202607`, `202608`에 해당하는 실제 다운로드 ID 2606/2607/2608을 확인했다. 구현은 이 값을 상수로 고정하거나 이름에서 추측하지 않고 목록을 읽는다. 이번에 새로 3개월 ZIP 전체를 받아 재적재한 것은 아니다.
- 로컬 `gh api .../dispatches` 수동 호출에 **HTTP 204 No Content**를 받았다. event_type은 `gilmok_address_pending`. 기본 브랜치에 새 workflow가 없는 상태이므로 이는 GitHub 접수 확인이며 실제 Actions job 실행 확인이 아니다.
- 로컬 address_dispatch CLI에 같은 event envelope를 전달했다. 실제 큐가 비어 있어 processed=0, pending=0, needs_review=0. 실제 외부 대장 API 재호출은 없었다.

로컬 원본/접수 기록: `.local/validation/pr8/` (비추적). 사용자 제공 API 키는 출력/커밋하지 않았다. PR 6·7의 실제 데이터 적재 및 6조합×30회 DB p95 14.803~61.198ms 근거는 [PR 7 v1.2](pr7-building-all-floors-20260922.md)를 승계한다. PR 8에서 RPC 벤치마크를 재실행했다고 주장하지 않는다.

## 실패·호환 증명

- 임시 테이블 삭제 후 CHECK 위반을 발생시켜 이전 행과 private active manifest가 모두 보존됨을 실제 로컬 DB 트랜잭션으로 확인했다. 더 오래된 실행 거부·동일 실행 중복 미반영도 확인했다.
- 수집·스키마·R2 단계 오류는 promotion/VACUUM을 호출하지 않는다. VACUUM 오류는 committed=true, maintenance_failed로 구분한다. 유지보수 연결 autocommit과 FULL 미사용을 테스트했다. 실제 운영 테이블에 PR 8 VACUUM을 실행한 것은 아니다.
- fixture pending 1건을 기존 process_one으로 처리하여 done/30일 ready 캐시·raw 파일을 확인했다. 외부 geocoder/BuildingHub는 고정 응답 fixture이며 테스트 전체를 롤백했다. 실제 공급자와 원격 Actions의 종단 간 검증은 활성화 때 수행해야 한다.
- dispatch allowlist와 payload 무시, 처리 건수 한도, 비밀/주소 없는 요약, 원격 활성화·프로젝트·TLS 가드, anon/authenticated의 private 상태표 접근 불가를 확인했다.
- 학원·학교·상가·실거래·임대동향 adapter는 기존 정규화 함수를 fixture로 호출하여 선택 소스만 교체하고 24개월/공간 연결 비활성을 유지하는지 확인했다. 생활인구는 게시본 3개월 재집계 연결 및 미검증 셀 차단, 교통은 실제 정규화/집계 함수로 92일 분모·두 교통수단 유지를 확인했다.
- CLI 생성 migration `20260922053832_refresh_snapshot_state`를 로컬 적용하고 `supabase migration list --local`로 확인했다. 새 테이블의 활성 상태는 0행이다. 원격 DB 연결은 하지 않았다. webhook trigger도 생성하지 않았다.

## 검사 결과와 한계

`pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm test:db` 통과. Python 단위 223건, Vitest 1건, DB 통합 126건이 통과했다. [actionlint v1.7.12](https://github.com/rhysd/actionlint/releases/tag/v1.7.12) 공식 checksum 확인 후 임시 디렉터리에서 모든 workflow 검사 통과(shellcheck/pyflakes 보조 검사 제외). 런타임 의존성은 추가하지 않았다.

원격 월간 6소스 전체·수동 건물 분기 전체·원격 VACUUM·webhook 실제 네트워크 송신은 미실행이다. R2/제공자 쿼터 및 GitHub hosted runner 디스크·메모리·총 사용 분은 운영 활성화 후 측정한다. hourly sweep 선택은 월 2,000분을 보장하는 결과가 아니라 10분 폴링을 피하라는 사용자 결정이다. 임대동향 공간 연결은 비활성, 원격 전환은 절차만 준비했다.
