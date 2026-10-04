# 데이터 갱신 운영

PR 8은 로컬 S1을 마감하고 실행 경로를 준비한다. 원격 전환·Secrets 등록·웹훅 활성화는 수행하지 않는다. 입력 계약은 [data-sources.md 3절](../planning/data-sources.md#3-score_inputs-s2-채점-입력-계약-v12)의 v1.2이며 RPC는 변경하지 않는다.

## 실행 일정과 범위

| 워크플로우 | 실행 | 범위 |
|---|---|---|
| refresh-monthly | 매월 10일 03:17 KST / 수동 재시도 | living, transit, academies, schools, population, trades |
| refresh-manual | 수동, 분기 운영 | stores, buildings, rent |
| address-queue | pending 이벤트 / 6시간 간격(UTC 00/06/12/18시 23분) sweep / 수동 | 주소 캐시 큐 최대 10건 |

월간 생활인구·교통은 직전 완료 월까지 3개월, 실거래는 24개월을 교체한다. 인구는 직전 완료 월, 학원·학교는 조회 시점 자료다. 월간 재시도에서는 source를 하나 선택할 수 있다. 미공개 월·스키마 변경·90% 미만 교통 연결률·신규 미검증 생활인구 셀은 실패로 처리하고 이전 집계를 유지한다. 생활인구 경계가 추가되면 기존 검증 절차로 경계를 먼저 보완한다. 누락 월을 오래된 월로 몰래 대체하지 않는다.

```sh
# 로컬 기본. 실제 적재 및 R2 게시가 발생하므로 대상/월 확인 후 실행.
uv run --frozen python -m ingest.refresh --source population --end-month 2026-08
# GitHub: 워크플로우가 main에 반영되고 원격 준비를 완료한 이후
# gh workflow run refresh-monthly.yml -f source=transit -f end_month=2026-08
```

원격은 `--target remote`, `INGEST_REMOTE_ENABLED=true`, 프로젝트 ref와 일치하는 TLS DB URL 및 R2를 모두 요구한다. 기본 동작은 로컬이며 원격에서 임시 로컬 저장소로 대체하지 않는다. 기존 verify_* CLI에는 로컬 전용 연결이 있으므로 원격 실행용 명령으로 쓰지 않는다.

## 수동 파일 준비

R2 raw/에 원본을 게시하고 파일명 → key·sha256 형태 JSON을 만든다. JSON 자체도 raw/에 게시하여 workflow_dispatch의 `asset_manifest_key`로 전달한다. SHA256이 다른 파일은 적재하지 않는다.

```json
{"stores.zip":{"key":"raw/manual/stores/2026-Q3/stores.zip","sha256":"실제 파일의 SHA256 64자리"}}
```

- stores: `stores.zip`(소상공인시장진흥공단 분기 원본). `end_month`는 해당 자료 기준 월.
- buildings: `buildings.zip`(공식 SHP), `register-manifest.json`, `titles.parquet`, `floors.parquet`. 기존 `ingest.building_register.RegisterClient`의 재개 가능한 수집으로 SHP PNU 전체에 대한 대장 수집을 완료한 뒤 게시한다. manifest의 groups·행 수를 SHP 및 Parquet와 대조한다. 대장 전수 API 수집은 일일 쿼터 때문에 단일 Actions 실행에 넣지 않는다. WFS 보조는 기존 SHP+강남구 경계 범위로 수집한다. ZIP 원본과 대장 원본 모두 보존한다.
- rent: `rone-cls-office-names.json`, `rone-cls-names.json`, `rone-cls-small-names.json`, `rone-cls-collective-names.json`, `rent-intersections.json`. PR 6 검증과 같은 R-ONE 공식 분류 응답 및 교차 근거 파일이다. `quarter`도 지정한다. 공간 정의가 검증되지 않았으므로 district/region 연결을 활성화하지 않는다. 이 실행기로 임의 경계를 켤 수 없다.

```sh
# 로컬 수동 예: manifest에는 실제 게시 key와 SHA256 필요
uv run --frozen python -m ingest.refresh --source stores --end-month 2026-06 \
  --asset-manifest /path/to/assets.json
```

## 스냅샷 보존과 유지보수

1. 소스별 advisory lock으로 동시 적재를 막고 수집·정규화·R2 게시 및 재읽기를 끝낸다.
2. 기존 loader의 단일 트랜잭션에서 조회 테이블과 `ingest_private.refresh_snapshots`를 함께 갱신한다. 더 오래된 기준일/실행 스냅샷은 거부하고 동일 실행은 중복 반영하지 않는다. 다른 소스와는 독립적으로 성공/실패한다.
3. 커밋 뒤 **별도 연결·autocommit**에서 대상 테이블만 `VACUUM (ANALYZE)` 한다. VACUUM FULL은 실행하지 않는다. 잠금 대기 5초·문장 15분 한도다.
4. 수집/원본 검증/DB 적재 실패는 `refresh_failed, committed=false`: 이전 데이터와 manifest 유지. R2에 미참조 원본이 남을 수 있다. VACUUM 실패는 `maintenance_failed, committed=true`: 새 스냅샷은 유효하며 유지보수만 재실행한다. 성공한 갱신을 실패한 것처럼 되돌리지 않는다.

실행 결과 `report.json`만 Actions artifact로 30일 보관한다. 원본·개인 주소·키는 artifact/로그에 넣지 않는다. 원본은 R2에 별도 보관한다. 지오코딩의 호출 claim은 중복 유료 호출을 막기 위해 조회 테이블 롤백과 독립적으로 남는다.

## 설정과 비용

Repository variable `INGEST_REMOTE_ENABLED` 기본 미설정/false: 모든 원격 적재 job을 건너뛴다. 준비 후에만 true. `SUPABASE_PROJECT_REF`, 필요 시 `VWORLD_SERVICE_URL`도 variable로 지정한다. Environment `ingest-production`에는 `.env.example`의 사용 소스별 API 키, `SUPABASE_DB_URL`, R2 네 항목을 Secrets로 등록한다. 로컬 `.env`를 로그나 artifact에 복사하지 않는다. GitHub dispatch token은 Actions 수집 키와 별개이며 Supabase Vault에 저장한다.

6시간 sweep은 최대 월 124회(31일), 이벤트 워커와 월간 적재가 추가된다. GitHub 호스팅 실행 시간 과금 때문에 **월 2,000분 이내를 보장하지 않는다**. 10분 폴링의 월 4,464회를 피하는 설계다. 비활성 job에는 runner가 배정되지 않는다. 활성화 이후 실제 월간 사용량을 확인하고 예산 초과 시 수동 운영으로 전환한다. 자동 유료 전환은 하지 않는다. 대량 생활인구 처리에는 runner 디스크·메모리·330분 job 제한도 실제 확인해야 한다. PR 8에서 원격 월간 전체 실행 시간을 측정한 것은 아니다.

## 시즌 비교를 위한 R2 정책

새 실행의 raw 및 집계 Parquet, 소스별 manifest를 UTC 실행 스냅샷별 불변 key로 보존한다. manifest에는 소스 기준일·입력 계약 버전·Git SHA·원본 key/체크섬을 남기고 DB에는 현재 manifest만 둔다. 이전 실행 객체를 덮어쓰거나 lifecycle로 자동 만료시키지 않는다. 실패 실행의 미참조 객체도 자동 삭제하지 않는다. 원래 수동 SHP ZIP도 보존한다.

계절 비교는 해당 시점의 기준일·연령대·집계 범위·소스 버전을 맞춘 후 S2 명세로 정의한다. 과거에 저장하지 않은 기간은 복원 가능하다고 간주하지 않는다. 최소 한 해 비교 자료가 쌓이기 전에도 자동 삭제하지 않으며 보존 기간 변경은 별도 결정으로 한다.

S2-1: 월간 갱신 성공 뒤 [score_reference 배치](score-reference.md)를 후속 job으로 실행한다. 원본 갱신 실패 시 reference job도 실행하지 않는다. 각 reference에 소스 버전이 기록되므로 채점 시 현재 입력과 일치하는지 확인해야 한다.


## D5 상시 운영 전환 (2026-10-02)

사용자가 이벤트 즉시 처리와 `23 */6 * * *` sweep을 승인했다. 이 PR의 cron은 main 머지 후 적용된다. KST 실행 시각은 03:23·09:23·15:23·21:23이다.

**상시 운영 시작일: 아직 없음.** 실제 공개 주소 실증에서 Actions 지오코딩이 실패해 `INGEST_REMOTE_ENABLED=false`, `gilmok_address_dispatch` disabled로 롤백했다. [실증·실패 run](../validation/s3-2-d5-20261002.md)을 따른다. 실패를 ready로 간주하거나 상시 활성화 상태로 남기지 않는다.

재개 절차:

1. main에 이 PR이 머지됐는지, Secrets에 `JUSO_API_KEY`·`VWORLD_API_KEY`·대장/R2/DB 키가 있는지 확인한다. `JUSO_API_KEY`는 이번 승인 범위에서 등록했다. 값은 출력하지 않는다.
2. 보존된 공개 주소 `서울특별시 강남구 강남대로92길 33`의 실패 코드와 공급자 호출 실패 원인을 확인한다. 고정 코드 `juso_transport_failed`·`juso_business_error`·`vworld_coordinate_failed`는 비공개 큐에서 확인한다. 오류 원문·URL·키는 로그에 넣지 않는다.
3. 원인 해결 후 `gh variable set INGEST_REMOTE_ENABLED --body true`, DB `ALTER TABLE ingest_private.building_address_requests ENABLE TRIGGER gilmok_address_dispatch` 순서로 활성화한다. 보존한 실패 요청 한 건만 pending으로 재개한다.
4. 새 익명 세션에서 같은 공개 주소를 등록해 webhook repository_dispatch → Actions 성공 → cache ready → RPC ready → 무새로고침 화면 갱신을 확인한다. 모든 단계를 통과한 시각을 이 문서의 상시 운영 시작일로 기록하고 true를 유지한다.

롤백 절차:

1. `gh variable set INGEST_REMOTE_ENABLED --body false`로 다음 이벤트·스케줄 job을 차단한다. 이미 실행 중인 run은 자동 중단되지 않으므로 상태를 확인하고 새 작업을 막는다.
2. DB에서 `ALTER TABLE ingest_private.building_address_requests DISABLE TRIGGER gilmok_address_dispatch`를 실행한다. Vault 토큰·큐·캐시를 삭제하지 않는다.
3. 필요하면 cron을 이전 `23 * * * *`로 되돌리는 PR을 만든다. variable=false인 동안 어떤 cron도 워커를 실행하지 않는다. 실패/processing 요청을 보존하고 원인·run URL·최종 두 스위치를 기록한다.

`INGEST_REMOTE_ENABLED`는 월간 적재에도 쓰는 기존 공통 스위치다. 익명 정리는 별도 `AUTH_CLEANUP_ENABLED=false`이며 이 전환으로 삭제나 정리 스케줄을 활성화하지 않는다.

### 2026-10-04 D5 재개 조건

상시 운영은 시작하지 않았다. 사용자 결정에 따라 C(#26) 머지 후 D5를 재실증한다. 현재 `INGEST_REMOTE_ENABLED=false`·주소 트리거 비활성을 유지한다. 읽기 전용 공급자 진단은 아래처럼 큐 실행과 분리할 수 있다. 진단 job은 DB/큐/R2에 접근하지 않으며 운영 variable과 무관하게 Juso/Vworld만 각 1회 조회한다.

```sh
gh workflow run address-queue.yml --ref s3/address-always-on -f diagnose_only=true
```

#25 머지 후에는 `--ref main`을 사용한다. [10월 4일 진단](../validation/s3-2-d5-20261002.md#2026-10-04-공급자-진단--vworld-http-502-재현)은 Juso 성공·Vworld HTTP 502였다. Juso 검색키/Vworld 키는 Actions에 있고 Juso 좌표키는 현재 임시 경로의 필수 변수가 아니다. 공급자 성공을 확인한 뒤 기존 pending/failed 요청을 재개하는 운영 실증을 수행한다. 502가 지속되면 전환하지 않고 오류를 보고한다.

### D5 등록 좌표 재사용 (2026-10-04 사용자 결정)

운영상 원인은 **Vworld 국내 IP 제한(동일 키·도메인 icn1 200 / iad1·Actions 502)**으로 기록한다. 주소 워커는 등록 PNU·좌표를 비공개 큐에서 읽고 대장만 조회한다. Actions의 Vworld 지오코더 성공을 운영 재개의 조건으로 삼던 앞 절의 절차를 이 방식으로 대체한다. 수동 공급자 진단은 과거 장애 증거용이며 정상 워커 처리에는 필요 없다.

`address-queue` 실제 처리 job에는 VWORLD_API_KEY를 주입하지 않는다. `refresh-source`의 Vworld 키는 건물/법정동 WFS용으로 유지하지만 좌표 조회 경로에서는 사용하지 않는다. `JUSO_COORD_ENABLED` 미등록/false 또는 좌표키 부재이면 좌표 없는 작업은 needs_coord로 보류하고 건수를 출력한다. `INGEST_REMOTE_ENABLED=true`만으로 Juso 좌표 API를 활성화하지 않는다. 월간 신규 주소의 보류는 해당 소스 promotion을 중단하여 기존 스냅샷을 보존한다.

재개 순서: C(#26) 머지 → #25 최신 main 동기화 → D5 migration 1개의 최종 dry-run·승인·push → #25 main 반영 → 공개 주소 등록으로 입력 저장 확인 → webhook/Actions(좌표 API 0회)/ready/화면 자동 갱신 검증 → 상시 운영 시작일 기록. 기존 실패 1건은 삭제하지 않고 같은 주소의 새 등록 PNU·좌표로 재개한다. 좌표 API 활성화/키 등록과 실제 원격 삭제는 이 순서에 포함되지 않는다.

롤백: `INGEST_REMOTE_ENABLED=false`, 주소 dispatch 트리거 DISABLE. 추가 열·needs_coord 행·공유 캐시는 보존한다. 이전 프론트의 score_inputs 5인자 호출은 그대로 동작하지만 좌표 없는 워커 작업은 보류된다. 타임스탬프·투영·쿼터·RLS는 기존 정책을 유지한다.
