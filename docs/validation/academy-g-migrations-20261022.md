# G 선행 migration ① 실행 — 2026-10-22

사용자 승인 범위는 #39·#41 migration 두 파일뿐이다. G 데이터 승격(②), #40 push·배포(③), #41 Ready(④)는 실행하지 않았다.

## 실행 및 보존 증거

| 순서 | 파일 | 기존 객체 변경 여부 |
|---|---|---|
| 1 | `20261012150926_academy_display_provenance.sql` | 없음. 신규 private 표시 테이블 2개·RLS/권한/comment 추가. |
| 2 | `20261016084609_academy_layer_rpc.sql` | 없음. 신규 private 검토/release 테이블 2개와 authenticated 전용 조회 RPC·RLS/권한/comment 추가. |

- 직전 `supabase db push --linked --dry-run`: exit 0, 0.508초. 위 두 파일만 대기함을 코드로 확인한 뒤 push했다.
- `supabase db push --linked --yes`: exit 0, 0.617초. `--include-all` 사용 없음.
- 원격 이력 **45 → 47건**. 추가 버전 `20261012150926`, `20261016084609`. 기존 45건은 version뿐 아니라 `to_jsonb(schema_migrations 행)` 전체를 키 정렬 JSON으로 직렬화한 SHA256이 전부 동일하다. 삭제 0건.
- 승인 파일 SHA256을 dry-run 전·push 직전 재확인했다. 해시·전체 CLI 출력·전후 이력의 행별 SHA256은 [JSON 증거](academy-g-migrations-20261022.json)에 있다.
- G source/reference/cache 데이터 승격 없음. Production 코드 변경·배포 없음. #40 구/신 timestamp push 없음.

## ③ 파일명 순서 조정

#40의 미적용 migration은 `20261016021224_juso_registration_coordinates.sql` → `20261021000000_juso_registration_coordinates.sql`로 이름만 변경한다. SQL 바이트가 같고 SHA256은 `b904c835d1695ad439a2737a552071face389a40aa96d734ae170de92cc576df`로 동일하다. #39·#41 적용 후 #40만 남기는 일반 dry-run exit 0, 0.354초. ③에서 `--include-all`을 쓰지 않는다. ③ 실제 실행 직전에도 다시 dry-run하며, 사용자 승인과 Vercel 서버 변수 존재 확인 후 push → 사용자 머지·Production 배포 순서를 지킨다.

## ② 승인 후 필수 검증 — 아직 미실행

1. 승격 직전 원격 source fingerprint를 재확인하고 실제 원격 12테이블 rollback 백업을 새로 만든다. 로컬 target snapshot을 원격 이전 상태 백업으로 대체하지 않는다.
2. **기존 Juso 99행의 갱신 전 모든 컬럼 값은 rollback 대상에 포함된다.** `ingest/verify_academy_transition.py`의 `BACKUP_TABLES`에 `public.geocode_cache`가 있고, `table_digest`는 provider 필터 없는 `SELECT *`를 COPY BINARY로 보존한다. 다만 원격 승격 전 백업은 아직 생성하지 않았으며, ②에서 99개 주소의 갱신 전 값·건수·해시를 백업/manifest와 대조한 뒤에만 갱신한다. 그 사이 새 행이 있으면 변경된 건수도 보고하고 보존한다.
3. 원자적 승격 후 a~e 총점 a **83.0108**, b **92.7877**, c **82.2096**, d **81.7561**, e **84.9937**, 순위 **b>e>a>c>d**를 원격에서 대조한다. 신뢰도 a/b/d/e 90·c 85, rent_efficiency 결측 불변도 확인한다.
4. 원천 fingerprint와 `score_reference_sets`/분포 ID **`20261016T040000Z`** 일치, 기존 Kakao/Vworld 캐시 행 해시 불변을 확인한다.
5. **Production 옛 코드에서 기존 저장 비교를 연다.** 기준분포 불일치 시 실제 배지·문구·총점 표시와 재계산 완료 후 상태를 캡처한다. 모델 버전 배지를 기준분포 불일치 배지로 대신하지 않는다. 불일치 상태가 재현되지 않으면 정상 재열기 결과와 미재현을 구분하고, 별도 통제된 응답 fixture로 동일 배포 코드의 불일치 안내 유무를 확인한다. 안내가 없으면 없다고 보고한다. 현재 안내가 있다고 사전 단정하지 않는다.
6. **Production에서 새 채점을 실행한다.** 실제 reference RPC 응답 snapshot과 `row.inputs.reference.snapshot`(근거 패널의 ‘데이터 출처·기준일 → 기준분포’)이 **`20261016T040000Z`**인지 확인한다. 저장 비교의 과거 snapshot이나 고정 preset 상수를 증거로 대신하지 않는다.
7. Production 배포 버전이 그대로임을 기록한다. 데이터 교체로 새 채점 결과는 바뀔 수 있으므로 ‘코드 불변’과 ‘결과 불변’을 혼동하지 않는다. 이후 중단·보고하고 ③ 승인을 기다린다.

이번 작업은 DDL 두 파일과 문서/파일명 검증이다. 채점·UI 코드 변경이 없어 E2E·성능 전체 검사를 반복하지 않았다.
