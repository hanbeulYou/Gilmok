# G 메타데이터 원인 추적·로컬 정정 — 2026-10-23

**결론: 분포 내용은 동일하고 메타데이터만 어긋났다.** ②는 재개하지 않았다. 이번 세션은 loopback 로컬 DB·로컬 파일만 사용했고 원격 DB/R2/API를 읽거나 쓰지 않았다. GitHub PR 본문 보고 갱신은 이 구분과 별개다.

## 1. 실행 경로 확정

원본 `gilmok_academy_transition_school_20261016`은 정상이다. 문제는 원본 DB를 시험으로 오염시킨 것이 아니라, **격리 복제본에서 정상 반환한 noop 시험이 운영 메타데이터를 커밋했고, 그 시험의 after/rollback 파일을 승격 target으로 선택한 것**이다.

| KST 시각 | 확인한 실행/증거 |
|---|---|
| 10/18 18:16:07.798 | 세션 tool call `call_8d63588b0ab4427c80d3a118712473b0`에서 `/tmp/verify-g-release.py` 작성. 현재 `/tmp` 원본은 없어 보존된 실행 입력에서 복구했다. |
| 18:16:14.953 | 최초 import 경로 오류 뒤 `PYTHONPATH=.`로 같은 스크립트 실행. `CREATE DATABASE gilmok_academy_transition_release_20261018 TEMPLATE gilmok_academy_transition_school_20261016`; 원본 연결에는 쓰지 않았다. |
| 18:16:25.935924 | 복제본 `refresh_snapshots`의 academies·score_reference 두 행 committed_at. 아래 noop 성공 실행이 만든 정확한 시각이다. |
| 18:16:48~18:18:25 | 성공 로그·12테이블 before/after 복원 확인, #41 density/RPC 응답 대조. #41 측정 스크립트는 `REPEATABLE READ READ ONLY`; 이 행의 작성자가 아니다. |
| 18:24:03 | 코드 커밋 `50b33db`: release strict callback·12테이블 백업 지원. |
| 18:24:05 | 문서 커밋 `19a665d`: 위 복제본 시험과 after/rollback 산출물을 기록. |
| 10/21~22 | `after/rollback/manifest.json`(081faf63…a1da7)을 승격 target으로 선택. 당시 검산은 분포/원천 바이트를 확인했지만 운영 ID·빈 manifest 정합성을 놓쳤다. 10/22 staging 대조에서 중단. |

복구한 실행 코드의 핵심은 다음과 같다.

```python
def unchanged_reference(d):
    return date(2026, 10, 18), {}, lambda c: None
atomic_promote(
    db, {'academies': (date(2026, 10, 18), {}, lambda c: None)},
    '20261018T091000Z', unchanged_reference, expected_state=baseline,
    release_loader=lambda d: publish_layer_release(d, reviews, review_version='20261014-v3'),
)
after_manifest = backup(db, after)
restore(db, before)
restore(db, after)  # 시험 메타데이터를 포함한 after를 마지막으로 복원
```

`atomic_promote → refresh.promote`는 loader가 noop이어도 요청 snapshot/빈 manifest를 기록한다. 실패 주입 `20261018T090000Z`는 P0001로 12테이블 모두 롤백됐고, 그 다음 **성공** 호출 `20261018T091000Z`가 두 운영 행을 남겼다. 학원 원천·학교 보완·분포 값은 유지됐다. 이는 추정이 아니라 복구한 호출 입력·DB committed_at·before/after 파일·커밋 시각의 대조 결과다. 복구 스크립트 SHA256: `5042cfafd4d898a1d4746f82df34966a324e1d3865ed106660ef50c1c8b38883`. 진단용 원문은 `.local/g-metadata-repair-20261023/original-verify-g-release.py.txt`에 보존하며 재실행하지 않는다.

## 2. 분포 바이너리 비교

10/18 ID를 가진 별도 분포는 없다(**0행**). 10/18 시험 전후 DB에도 실제 분포의 snapshot은 모두 10/16이다. 따라서 ‘10/18 실행 직후 분포’와 ‘10/16 원본 분포’를 COPY BINARY 전체 스트림으로 비교했다.

| 대상 | 행수 | 바이너리 크기 | SHA256 |
|---|---:|---:|---|
| 10/16 학교 보완 after | 162,032 | 19,778,983B | `06920d4b01467bacb70deab8d43c685293bb5b91375ff7e2a4e721a45443168d` |
| 10/18 시험 before | 162,032 | 19,778,983B | 동일 |
| 10/18 시험 after | 162,032 | 19,778,983B | 동일 |

gzip 해제 후 **바이트 배열 자체 동일**, 차이 행 **0**. 원본·시험 복제본 현재 DB의 재추출 해시도 동일하다. raw만 비교한 것이 아니라 snapshot·computed_at을 포함한 분포 행 전체를 비교했다. 정본 ID는 **20261016T040000Z**다.

## 3. 정정·시험 격리·새 고정 manifest

새 로컬 정본 DB는 `gilmok_academy_transition_canonical_20261023`이다. 원본과 잘못된 시험 복제본·기존 manifest는 증거로 그대로 보존한다. 새 정본의 `refresh_snapshots` 중 **academies·score_reference 2행만** 10/16 원본 COPY에서 복원했다. 학교 행은 이미 정상이어서 변경하지 않았다. 전체 refresh 테이블은 10/16 원본 바이트와 같아졌고, 다른 **11테이블은 10/18 target과 바이너리 불변**이다. 리뷰101/release1도 유지한다.

- 학원 운영 ID: `20261016T032916Z`, 원래 비어 있지 않은 manifest 복원.
- 분포 운영/본체/manifest ID: **20261016T040000Z**, 원래의 전체 manifest 복원.
- fingerprint: **`ca9ca0f95422c2b7fe14353cf6f4a5b38c723e0e42acad11930b6ebab1c746d0`**.
- 신규 `rollback_probe`: loopback + 전용 DB만 허용; 정상 반환/P0001 모두 `force_rollback=True`. 메타데이터와 reference raw를 시험 변경한 뒤 **12테이블 불변**을 두 경우에서 확인했다. 기존 월간 atomic release 실패 시험도 별도로 실행한다.
- 신규 `freeze_promotion`/CLI `freeze`: 분포 행·set·운영 snapshot·비어 있지 않은 manifest의 ID/행수/preset/fingerprint와 현재 원천을 READ ONLY snapshot에서 대조한 뒤 파일을 고정한다. 기존 `backup`은 진단/rollback 보관용이며 자동으로 승격 자격을 갖지 않는다. 이전 시험 복제본은 새 검사에서 `Reference refresh manifest is empty`로 거부된다.

새 고정 manifest:

```text
.local/g-metadata-repair-20261023/canonical/rollback/manifest.json
SHA256 b5d8d7d636a262a2c986be00a5d0ce52dcc09696435e9251968ba062bd1af604
```

[manifest 사본](academy-g-canonical-manifest-20261023.json). 기존 `081faf63…a1da7`은 이력용으로 보존하고 현재 승격 후보에서는 제외한다. 새 SHA에 대한 원격 실행 승인은 아직 받지 않았다.

로컬 staging에 **12개 파일을 각각 COPY**, 제약·행수·재추출 binary SHA/gzip SHA를 전수 대조했다. staging 자체의 분포 본체/set/운영 manifest도 새 guard를 통과했다. 지난 원격 백업은 오직 오프라인 비교 자료로 읽어, academies·schools·score_reference 외 다른 운영 provenance가 동일함을 확인했다. **원격 staging 실행이나 원격 dry-run으로 표현하지 않는다.**

정정 검산 스크립트의 첫 점수 수집은 autocommit 연결에서 `ON COMMIT DROP` 임시 테이블이 바로 사라져 실패했다. 분포/manifest 불일치가 아니며 원격 실행도 없었다. 기존 수집 함수의 계약대로 명시적 로컬 트랜잭션 안에서 재호출했다. 정상 종료/P0001 롤백·staging·점수 입력 수집을 다시 확인한 최종 검증은 14.579초였다. 최종 manifest는 덮어쓰지 않았다.

## 4. a~e 및 무작위 5셀 재채점

v0.4.0·동일 후보/반경/임대료 미입력·실제 exposure 순수 계산을 유지했다.

| 후보 | 이전 총점 | 새 정본 총점 | 순위 | 신뢰도 |
|---|---:|---:|---:|---:|
| a | 83.0108 | 83.0108 | 3 | 90 |
| b | 92.7877 | 92.7877 | 1 | 90 |
| c | 82.2096 | 82.2096 | 4 | 85 |
| d | 81.7561 | 81.7561 | 5 | 90 |
| e | 84.9937 | 84.9937 | 2 | 90 |

순위 **b>e>a>c>d** 유지. 10후보 모두 **계산 시각 computed_at만 달라지고 나머지 ScoreResult 전체가 정확히 동일**하다. 따라서 8축·총점의 IEEE 정밀값, 신뢰도와 사유, 근거, 결측도 동일하다. a~e는 rent_efficiency만 결측이고, 무작위 5셀의 기존 결측도 유지된다. 반올림된 화면 값만 비교한 결과가 아니다. [점수/보존 증거 JSON](academy-g-metadata-repair-20261023.json).

## 5. 백업 유효기간과 다음 승인 경계

[운영 사전 점검](../operations/data-refresh.md#승격-사전-점검과-백업-유효기간-2026-10-23)에 운영 메타데이터↔manifest ID/비어 있지 않음 검사를 추가했다. 원격 rollback 백업은 **생성 완료 후 최대 1시간 + 동일 연속 실행 창**에서만 재개용으로 유효하고, 중단·관련 상태 변경 시 즉시 만료된다.

**10/22 원격 백업은 재개용으로 만료됐다.** 역사적 복원 증거로만 보존한다. ②를 다시 승인받으면 반드시 새 원격 백업을 만들고 Juso 갱신 전 값·Kakao/Vworld·후보/비교·운영 이력 해시를 다시 검산한다. 새 target에서도 원격 ingest_runs 전체를 로컬 2행으로 덮어쓰지 않으며, 기준분포 운영 행까지 포함한 선택적 단일 트랜잭션 범위를 재확인해야 한다.

이번에는 ② 재개·③·원격 migration·원격 쓰기·R2 접근·Production 검증을 수행하지 않았다. 코드와 문서는 별도 커밋으로 남기며, 기존 G 로컬 전용 커밋을 임의로 게시하지 않는다.

## 검사·커밋

- 코드 커밋 `ad8bfe3`: 승격 metadata guard·READ ONLY freeze·정상 종료도 롤백하는 local probe·회귀 시험.
- `pnpm lint`, `pnpm typecheck`, `pnpm test` 모두 exit 0. Vitest **208**, Python **319** 통과.
- `uv run --frozen pytest tests/integration/test_monthly_atomic.py -q`: 전용 임시 DB의 **13개** 통과. 원격 연결 없음.
- 실제 정본 DB에서 정상 반환/P0001 각각 12테이블 digest 불변, 새 manifest 12파일 staging 전수 일치.
- 원격 승격 재시도 없이 보고 후 중단한다.
