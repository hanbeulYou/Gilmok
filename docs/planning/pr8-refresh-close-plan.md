# PR 8 — 갱신 스케줄과 S1 마감

base: main (PR 7, GitHub #10 머지 후). 사용자 승인 후 구현. 원격 전환은 문서화만 한다.

## 승인 범위와 구현 파일

- `.github/workflows/refresh-{monthly,manual,source}.yml`: 월간 6개 소스와 수동 상가·SHP·임대동향, 소스별 중복 실행 제어.
- `ingest/refresh.py`, `refresh_sources.py`: 기존 수집/정규화/loader 재사용, R2 원본 재읽기 후 소스별 원자 교체, 커밋 후 별도 연결 VACUUM ANALYZE.
- `ingest/population.py`, `living_population.py`: 실제 다운로드 양식/목록 ID로 월 자료 취득. 대용량 SHA256은 스트리밍 처리.
- 주소 A안 유지: `ingest/address_dispatch.py`, `address-queue.yml`. 사용자가 10분 폴링을 취소하고 **DB Webhook → repository_dispatch + hourly sweep**으로 승인했다. 데이터 API는 Python `/ingest`만 호출한다. Edge Function은 추가하지 않는다.
- `docs/operations/`: 운영·원격 전환·수동 webhook 활성화 절차. 원격 Secrets/DB/webhook은 아직 활성화하지 않는다.
- `AGENTS.md`, 기획서, 데이터 소스 명세: S1 완료·S2 인계·R2 보존 정책.

초기 예상과 달리 최신 기준일 및 R2 manifest를 데이터와 원자적으로 확정하기 위한 private `refresh_snapshots` 한 테이블이 필요하다. CLI로 새 migration을 생성하고 로컬에만 적용한다. 공개 RPC와 입력 계약은 바꾸지 않는다. 현재 main 계약은 v1.1 수정 및 all_floors 추가를 포함한 **v1.2**다. v1.1 검증 이력을 보존한다.

## 검증과 완료 기준

- 수집·스키마·R2 실패 및 DB 교체 중 실패에서 이전 행/manifest 유지, 오래된 실행 거부·동일 실행 중복 반영 방지.
- VACUUM 실패는 데이터 커밋과 구별. private 상태표 anon/authenticated 접근 금지.
- dispatch allowlist, untrusted payload 무시, bounded worker, pending→ready·30일 캐시.
- 실제 MOIS 응답과 생활인구 목록 확인, 로컬 수동 repository_dispatch 접수. main 반영 전에는 GitHub workflow 실행까지 검증했다고 기록하지 않는다.
- `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm test:db`.
- S1 실제 데이터 6조합×30회 및 EXPLAIN 기준은 PR 7 v1.2 근거를 승계한다. RPC를 변경하지 않는다.

## 리스크와 중지 조건

소스 게시 지연·스키마 변경·미검증 신규 격자는 해당 소스 갱신 실패로 이전 스냅샷 유지. 건물 대장 전수는 쿼터를 고려해 완료된 수동 수집 산출물을 입력받는다. 임대동향 공간 연결은 계속 비활성. private Actions 비용은 hourly sweep 외 월간 적재 시간도 포함하여 실측해야 한다. 원격 용량·실행 시간은 아직 검증하지 않았으며 자동 축소/유료 전환은 하지 않는다. S2 채점 로직은 scoring-spec 승인 이전에 구현하지 않는다.
