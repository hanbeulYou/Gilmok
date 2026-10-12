# 10/10 원천·기준 분포 불일치 복구

2026-10-11. #36 노출 오버레이와 분리한 운영 PR. 채점 v0.4.0·가중치·cluster 고정 스케일·입력 좌표는 유지한다. **2026-10-12 사용자 승인으로 `20261011T120000Z` 승격·production 복구 완료**. [원격 실행·로컬 정밀도 정정](../validation/reference-refresh-remote-20261012.md)을 따른다. 사용자는 이번 복구를 표시 소수 둘째 자리·순위·신뢰도 일치로 승인했으며 현재 snapshot을 유지한다. 정밀값 안정화는 [별도 PR 제안](percentile-precision-plan.md)으로 분리한다. 다른 snapshot 승격은 별도 승인 대상이다.

## 원인과 수정 범위

[10/10 월간 실행](https://github.com/hanbeulYou/Gilmok/actions/runs/38000642129)에서 living/transit/academies/schools/population은 각각 커밋됐지만 trades는 `ConnectionError`로 실패했다. 로그에는 연결 실패의 세부 원인이 없으며 API 응답 오류로 단정하지 않는다. `needs: refresh`의 reference와 warmup이 skipped가 되어 활성 분포는 `20260923T111436Z`에 남았다.

`reference_source_mismatch`는 의도한 출처 검증이다. 이를 무시하거나 NULL을 임의 점수로 바꾸지 않는다. demand/flow/transit가 결측이 되어 total=NULL이다. 현재 원천으로 분포를 다시 만들면 된다.

변경 파일: `ingest/refresh_monthly.py`, `ingest/score_reference.py`의 수집 트랜잭션 경계, `.github/workflows/refresh-monthly.yml`, 실제 PostgreSQL 회귀 시험, 운영/검증 문서. **마이그레이션 없음. 기존 DB 객체·함수·권한·트리거 정의 변경 없음.** 따라서 migration dry-run/push는 없다. 데이터 쓰기는 별도 승인 대상이다.

## 긴급 복구 실행안 — 로컬 전수 재생성 산출물 승격 권장

1. 원격을 REPEATABLE READ READ ONLY로 읽어 공공 조회 18테이블과 출처 메타데이터 5테이블을 격리 로컬 DB에 복제했다. 사용자·후보·비교·주소 큐는 복제하지 않았다. 캡처 42.5초, 원격 쓰기 0.
2. 서울 10,127셀 × 800/1000m = RPC 20,254회, 8지표 162,032행을 기존 TS 식으로 재생성했다. 로컬 467.063초(수집 452.544초). 저장 산출물을 다시 읽어 전수 재계산 불일치 0. 검증 snapshot은 `20261011T120000Z`다.
3. 원격 최신 source fingerprint와 산출물 fingerprint가 동일함을 재확인했다. 승인 뒤에도 적재 직전 `load_snapshot`의 source-table 잠금 + fingerprint 검사를 다시 수행한다. 달라졌으면 승격하지 않고 다시 로컬 전수 생성/비교부터 보고한다.
4. 승인 후 원본/분포/manifest를 불변 R2 revision에 게시·재읽기 검증하고, 기존 `refresh.promote` + `score_reference.load_snapshot`으로 분포만 단일 트랜잭션 승격한다. 원천은 갱신하지 않는다. 커밋 뒤 두 reference 테이블에 `VACUUM (ANALYZE)`, 6조합 예열, 실제 익명 세션의 a~e 재조회/채점으로 확인한다.

승격 대상 fingerprint: `160930013c9cf4c019bb8a8ef0835a239b9287004a28238720ff6d17ce31c6e8`. 분포 파일 SHA256·원본/manifest SHA256과 8축 비교는 [실측 기록](../validation/reference-refresh-20261011.md) 및 JSON에 고정한다. 계산 식의 reference preset 계약은 기존 `academy_v0 / 0.1.2`, 앱 채점 모델은 **0.4.0**으로 서로 역할이 다르다. cluster 상수는 재보정하지 않는다.

### 소요 시간과 원격 쓰기

- 로컬 전체 재생성 실측: 7분 47초. 재생성 완료 산출물의 승격은 R2 업로드/검증·162,032행 COPY·VACUUM·5후보/6조합 재검증을 포함해 **5~10분을 작업 창으로 예상**한다. 원격 승격 시간은 미실측이며 승인 후 단계별 실측으로 대체한다.
- 원격에서 전수 RPC를 다시 계산하는 대안: 30개 균등 간격 격자 × 2반경 읽기 전용 표본 평균 223.181ms, p95 620.597ms. 20,254회로 단순 환산한 수집만 **75.34분**. 콜드/웜 혼합·Mac→원격 경로의 표본 추정이며 전체 실행 보장이 아니다. 긴급 복구에는 이 중복 계산을 권하지 않는다.
- 쓰기: `public.score_reference`의 `academy_v0` 162,032행 교체, `public.score_reference_sets`의 해당 preset 1행 upsert, `ingest_private.refresh_snapshots`의 `source=score_reference` 1행 upsert. 위 세 변경은 한 커밋이다. 외부 R2에는 입력 26,342,237B·분포 735,018B와 manifest revision을 추가한다. 다른 preset/원천/개인 데이터는 수정하지 않는다.
- 원격 DB 크기 읽기 전용 관측: 891,358,355B. 승인 후 실행 직전에 디스크/WAL 여유를 재확인한다. 플랜/컴퓨트/디스크 변경은 하지 않는다.

### 롤백

- 실행 직전 위 두 public 테이블의 해당 preset과 private manifest 해당 행(또는 부재)을 CSV/JSON + SHA256으로 백업한다. 이전 활성 snapshot/fingerprint도 기록한다.
- 게시·검증·적재·제약 검사 실패는 커밋하지 않는다. 기존 활성 분포가 유지되며 미참조 R2 revision은 자동 삭제하지 않는다. 커밋 ACK를 잃으면 실패=롤백으로 단정하지 않고 활성 snapshot을 재조회한다.
- 커밋 후 새 분포에 문제가 확인되면 새 분포 값 삭제 → 백업 set 행 복구 → 백업 값 COPY → private manifest 복구를 **한 트랜잭션**으로 실행한다. 해당 작업도 명시적으로 승인된 복구 범위에서만 실행한다. VACUUM은 커밋 후 별도 연결이다.
- 이번 백업은 이미 불일치한 상태다. **이전 분포만 복원하면 total=NULL도 돌아온다.** 서비스까지 이전 정상 상태로 되돌리려면 10/10 이전 원천과 분포를 함께 복원해야 하며, 이는 이번 분포 승격과 다른 쓰기 범위라 별도 승인/manifest가 필요하다.

## 월간 재발 방지

기존 소스별 matrix 커밋을 단일 coordinator로 바꾼다. 단일 소스 재시도도 같은 경로에서 기준 분포를 함께 생성한다.

1. 선택한 모든 소스의 외부 수집·정규화·R2 게시/재읽기를 먼저 완료한다. 마지막 trades 수집이 실패해도 활성 원천/분포는 바뀌지 않는다.
2. 기존 소스별 advisory lock을 공유하고, 준비 전 source fingerprint를 기록한다. 승격 트랜잭션에서 source/metadata 테이블 쓰기를 잠그고 준비 중 변경이 없음을 확인한다. 일반 SELECT는 막지 않는다. 오래된 준비는 실패로 남긴다.
3. 단일 REPEATABLE READ 트랜잭션에서 기존 6소스 loader를 savepoint로 실행 → 같은 연결에서 아직 커밋되지 않은 원천으로 전수 기준 분포 수집 → 기존 TS 계산·R2 재읽기 전수 검산 → 분포/메타데이터 적재 → **한 번 COMMIT**. reference의 기본 단독 실행은 기존 읽기 전용 수집을 유지한다.
4. COPY/계산/게시/검증 중 하나라도 실패하면 모든 원천·분포·활성 manifest를 함께 롤백한다. 취소/연결 종료도 DB 수준에서 구/신 쌍 중 하나만 남긴다. ACK 유실은 `commit_unknown`으로 실패 종료하고 재조회한다. 같은 완료 snapshot 재시도는 현재 fingerprint를 검사하고 수집 없이 유지보수만 수행한다.
5. 커밋 뒤 VACUUM, 성공한 workflow 뒤 6조합 예열. VACUUM 실패는 `committed=true / maintenance_failed`로 구분한다. workflow 330분 한도, cancel-in-progress=false 유지. 한도를 넘겨 취소돼도 부분 교체하지 않는다.

원자성의 대상은 **조회 원천·출처 메타데이터·활성 기준 분포**다. 준비 단계의 불변 R2 객체 및 기존 영속 지오코딩 claim/cache는 API 중복 호출 방지를 위해 남는다. 이 보조 기록을 실패 시 되감지 않는다. 사용자 후보/주소 워커 상태와는 별도다.

리스크: 원격 전수 계산 동안 쓰기 잠금/이전 행 버전 보존이 길어지고 Micro의 CPU·WAL·디스크를 사용한다. 일반 조회는 이전 커밋을 읽지만 성능 무영향을 보장하지 않는다. 실측 75분은 참고치이며 다음 월간 전체 시간은 아직 미실측이다. 준비·커밋 단계별 시간과 실패 phase를 보고한다. 더 짧은 승격 창이 필요하면 독립 staging DB에서 계산한 뒤 원천/분포를 일괄 COPY하는 후속 설계를 검토하며, 이번 긴급 수정에서 별도 인프라를 도입하지 않는다.

로컬 증명: 실제 PostgreSQL 두 연결에서 커밋 전 구버전 쌍만 보이는지, 수집/원천 COPY/분포 생성/분포 COPY 실패·정상 커밋·VACUUM 실패·완료 재시도·준비 중 다른 갱신을 시험한다. 10/10 전수 복제 데이터에서도 새 ingested_at으로 다음 월간 상황을 만들고 실패/전수 재생성 성공을 재현한다. 원천 숫자는 조정하지 않으며 외부 API를 재호출하지 않는다.

## 사용자 안내 확인·제안

현재 `Badges.tsx`는 일반 결측을 표시하고 `format.ts`는 `reference_source_mismatch:*`를 전용 문구로 번역하지 않는다. “데이터 갱신 중” 안내와 출처 불일치 전용 재시도는 없다.

**별도 UI 수정 제안(이번 PR 미구현):** source mismatch를 발견하면 “데이터 갱신 중입니다. 잠시 후 다시 계산해 주세요.” 배지와 재계산 버튼을 보여주고, primary/school/reference 캐시를 함께 비워 재조회한다. 임대료 미입력 등 실제 결측과 구분하며 구버전 분포로 계산하지 않는다. 단일 DB 커밋이어도 브라우저의 서로 다른 HTTP 요청이 커밋 앞뒤를 걸칠 수 있으므로 이 안내/재조회는 여전히 유용하다. 채점 출처 검증을 완화하지 않는다.

## 사용자 승인·후속 단계

- 이 PR과 #36은 독립이다. 원격 분포 승격 승인 전에는 production NULL이 해소됐다고 표시하지 않는다.
- 검증 문서의 snapshot·파일 SHA·source fingerprint·쓰기 범위로 원격 승격 승인을 받는다. 승인 후 실측·원격 a~e 표·실행 결과를 같은 PR에 추가한다.
- workflow 변경은 main 머지 뒤부터 적용된다. 사용자가 머지한다. 기존 월간 실행/수동 소스 갱신이 진행 중이면 복구 승격을 병행하지 않는다.
