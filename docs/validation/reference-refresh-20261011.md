# 원천·기준 분포 일관성 복구 검증 — 2026-10-11

> 2026-10-12 후속: 승인 snapshot 원격 승격·production 총점 복구 완료. 이 문서는 최초 CSV 복제 검증 기록을 보존한다. b의 로컬 기대값에 정밀도 손실이 있었으며 정확한 원천 복제 대조·정정값은 [원격 검증](reference-refresh-remote-20261012.md)을 따른다. 아래 승인 대기/미실행 표시는 10/11 당시 상태다.

#36과 독립. **로컬 검증 완료, 원격 쓰기/복구 실행 승인 대기.** [실행·롤백 계획](../planning/reference-refresh-recovery-plan.md), [기계 판독 결과](reference-refresh-20261011.json).

## 원인

[10/10 월간 실행](https://github.com/hanbeulYou/Gilmok/actions/runs/38000642129)의 앞 5소스는 success, trades는 `ConnectionError / committed=false`, reference와 warmup은 skipped였다. 세부 연결 종료 이유는 기존 로그에 없어 추측하지 않는다. 출처 메타데이터 검증이 demand/flow/transit를 NULL로 만들어 총점도 NULL이다. 버전 검증을 끄는 수정은 하지 않았다.

## 재생성 전후 a~e

프리셋/모델 v0.4.0, 800m(학교 입력 1000m), 현재 Juso/Vworld 검증 좌표·PNU 경로와 같은 좌표, 실제 exposure 순수 엔진(Worker와 동일 코드), 임대료 미입력. 비교 전은 **10/10 원천 + 9/23 활성 분포**이며 이전 정상 검증값과 구분한다. 변경 없는 축은 값을 한 번만 썼다. 값은 4자리 반올림, JSON에 원정밀도 보존.

| 후보 | demand | flow | transit | cluster | exposure | building | environment | rent_efficiency | total 전 → 후 | 신뢰도 전 → 후 | 순위 전 → 후 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| a 역삼로 460 3층 | NULL → 96.4748 | NULL → 99.2945 | NULL → 38.3368 | 97.5273 | 30.7071 | 85.0000 | 93.4046 | NULL | NULL → 83.0756 | 30 → 90 | — → 3 |
| b 도곡로 409 2층 | NULL → 99.7630 | NULL → 98.7977 | NULL → 81.8170 | 98.4582 | 46.2595 | 95.0000 | 87.6534 | NULL | NULL → 92.6163 | 30 → 90 | — → 1 |
| c 역삼로 546 3층 | NULL → 84.0920 | NULL → 96.8303 | NULL → 60.7872 | 86.0254 | 50.6250 | 95.0000 | 91.9829 | NULL | NULL → 82.5310 | 30 → 85 | — → 4 |
| d 역삼로 460 4층 | NULL → 96.4748 | NULL → 99.2945 | NULL → 38.3368 | 97.5273 | 26.8687 | 75.0000 | 93.4046 | NULL | NULL → 81.8209 | 30 → 90 | — → 5 |
| e 역삼로 460 1층 | NULL → 96.4748 | NULL → 99.2945 | NULL → 38.3368 | 97.5273 | 38.3838 | 100.0000 | 93.4046 | NULL | NULL → 85.0586 | 30 → 90 | — → 2 |

복구 후 **b > e > a > c > d**, 사용자 지정 이전 순위와 동일하다. a/e/d의 비가중 가시점은 32/108, 층 주목도만 다르며 채점식 변경은 없다. 복구 후 rent NULL은 임대료 미입력에 따른 의도한 결측이다.

### 이전 정상 v0.4.0 검증값과 비교

[10/7 고정 검증](scoring-v040-20261007.md)의 8축을 그대로 대조했다. 아래 Δtotal은 복구 후 − 이전 정상값이다.

| 후보 | demand | flow | transit | cluster | exposure | building | environment | rent_efficiency | 이전 total | Δtotal |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| a | 96.5636 | 99.3341 | 38.3368 | 97.4774 | 30.7071 | 85.0000 | 93.4046 | NULL | 83.1020 | -0.0264 |
| b | 99.7630 | 98.8769 | 81.7011 | 98.4100 | 46.2595 | 95.0000 | 87.6534 | NULL | 92.6029 | 0.0134 |
| c | 84.4179 | 97.1872 | 60.7872 | 85.9101 | 50.6250 | 95.0000 | 91.9829 | NULL | 82.6720 | -0.1411 |
| d | 96.5636 | 99.3341 | 38.3368 | 97.4774 | 26.8687 | 75.0000 | 93.4046 | NULL | 81.8474 | -0.0264 |
| e | 96.5636 | 99.3341 | 38.3368 | 97.4774 | 38.3838 | 100.0000 | 93.4046 | NULL | 85.0850 | -0.0264 |

순위 변경이 없으므로 순위 역전 원인 분석 대상은 없다. 원천 갱신에 따른 수치 변화는 demand/flow/transit/cluster에 있으며 exposure/building/environment/임대료 상태는 동일하다. cluster 고정 상수·가중치·채점 v0.4.0을 유지했다.

## 전수 생성·승격 후보 manifest

- 원격 READ ONLY 캡처 `2026-10-11 12:28:24.707960+00:00`: 18 공공 조회 테이블 + 5 출처 메타데이터 테이블, 42.500초. snapshot과 모든 파일 행수/CSV SHA256은 JSON에 기록. 원격 쓰기 0.
- 로컬: 10,127셀 × 2반경 = 20,254 RPC, 162,032 분포 행. 전체 **467.063초**. 저장/재읽기 후 전수 재계산 불일치 **0**.
- 신규 reference snapshot `20261011T120000Z`. source fingerprint `160930013c9cf4c019bb8a8ef0835a239b9287004a28238720ff6d17ce31c6e8`.
- `2026-10-11 12:40:48.764081+00:00` 원격 재조회 fingerprint와 일치. 원격 활성 분포는 여전히 `20260923T111436Z` / `bd9603fd3a7aab0ec79b4c9a8590f10d2a1ffcd22a7f0ce1e5565ae702262b17`. 승인 직전에도 검사하며 원천이 바뀌었으면 승격 중단.

| 산출물 | bytes | SHA256 |
|---|---:|---|
| `rebuilt/inputs.parquet` | 26,342,237 | `26318f293f7a6c7765338540ddf80445cbd69645bc563de13a8583e55b643025` |
| `rebuilt/reference.parquet` | 735,018 | `e57e5d4b53a67c5fef9f68d9a575a617022e76378acf3dc1a75436e4dbc04913` |
| `rebuilt/manifest.parquet` | 4,473 | `32664e93145e1658c1630dafd80925fcfabf847c8d946b4e9417c04c63fb735a` |

원격 Micro 읽기 전용 30셀×2반경 표본은 평균 223.181ms, p95 620.597ms. 원격에서 20,254회 직접 재수집 시 약 75.34분 추정(실측 전체 시간이 아님). 검증된 로컬 산출물 승격을 권장하며 승인 후 5~10분 작업 창을 예상한다. 원격 DB 관측 891,358,355B. 원격 기본 statement_timeout=2min, idle-in-transaction/transaction timeout=0; 코드에서는 문장별 timeout·TCP keepalive를 사용한다.

쓰기: academy_v0 분포 162,032행 + set 1행 + 해당 refresh manifest 1행, R2 불변 revision 3개. 원천/후보/비교 수정 없음. 원격 실행 및 rollback 범위는 [계획](../planning/reference-refresh-recovery-plan.md#롤백)을 따른다. 기존 분포로만 되돌리면 NULL 상태도 돌아온다는 한계를 명시했다.

## 월간 원자성 시뮬레이션

1. 실제 PostgreSQL 회귀 8건: 수집/원천 COPY/분포 생성/분포 COPY 실패, 정상 커밋, VACUUM 실패, 동일 완료 snapshot 재시도, 준비 중 다른 원천 변경. 관찰자 연결에서는 커밋 전 구버전 쌍만 보이고 실패 후에도 구버전 쌍이다.
2. 위 10/10 전체 복제 DB에서 여섯 소스의 수치는 유지하고 ingested_at을 11/10으로 바꿔 다음 월간 버전 변경을 시뮬레이션했다. 외부 API 재호출 없음. 운영 coordinator를 그대로 쓰며 실패 세 경우와 정상 전수 20,254회 계산을 실행했다.

| 실데이터 시나리오 | 시간 | committed | 외부 읽기 관측 | 결과 |
|---|---:|---|---|---|
| collection | 1.489s | False | 0회 구버전 쌍 | 구버전 쌍 유지 |
| reference | 11.162s | False | 7회 구버전 쌍 | 구버전 쌍 유지 |
| reference_copy | 12.113s | False | 7회 구버전 쌍 | 구버전 쌍 유지 |
| success | 553.391s | True | 8회 구버전 쌍 | 신규 source/ref fingerprint 일치 |

계산/적재 실패 시 새 원천만 남는 상태를 재현하지 못했다. 정상 시 source fingerprint와 새 reference fingerprint가 동일하며, 실패 시 두 fingerprint와 모든 활성 manifest가 시험 전과 동일하다. 이 시험은 미래 API의 가용성을 보장하는 것이 아니라 **실패해도 부분 교체하지 않는 커밋 경계**를 검증한다. R2 원본·영속 지오코딩 claim/cache는 원자적 활성 쌍의 범위 밖이며 재호출 방지를 위해 남는다.

재현: 일관된 원천/분포가 있는 폐기 가능한 로컬 `gilmok_s3_replay_*` DB에서 아래 실행. 이 명령은 해당 **로컬 DB**의 ingested_at/분포를 시험용으로 변경하므로 운영 DB에는 사용할 수 없다.

```sh
pnpm score:reference:build
uv run --frozen python -m ingest.verify_monthly_atomic \
  --database gilmok_s3_replay_reference1011 \
  --directory .local/monthly-simulation-new
```

## 검사·남은 작업

- lint / typecheck / Vitest 201 / Python 단위 269 통과. 월간 8 + 기존 refresh/reference 14 = 집중 DB 22건 통과.
- 마이그레이션 없음. 기존 DB 객체 정의/권한/트리거 변경 없음. #36 미수정.
- 현재 UI는 일반 결측과 내부 사유 코드만 표시하며 데이터 갱신 전용 안내는 없다. [갱신 배지·묶음 재조회 제안](../planning/reference-refresh-recovery-plan.md#사용자-안내-확인제안)을 기록했고 UI는 바꾸지 않았다.
- 원격 분포 승격·익명 HTTP 재검증·월간 workflow 운영 실행은 미실행. 사용자 승인/PR 머지 후 각각 확인한다.
