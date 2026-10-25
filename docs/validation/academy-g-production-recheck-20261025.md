# G Production 재검증 — 2026-10-25

**통과.** 10/23 G 원격 승격은 이미 COMMIT됐으며 이번에는 데이터를 다시 승격하지 않았다. `touch_user_activity`의 정상 HTTP 204를 허용한 뒤 실제 Production의 저장 비교 재열기·새 분포 사용·데이터 기준일 표시를 확인했다. #39 Ready 전환 대상이며 머지는 한별이 수행한다. ③은 #39 머지 확인 및 Vercel 서버 변수 존재에 대한 한별 확인 후 별도로 진행한다.

## 수정과 실행

기존 모든 RPC `status === 200` 판정을 다음으로 한정 수정했다. `touch_user_activity` 이외의 RPC는 계속 200을 요구하며, HTTP 오류를 넓게 허용하지 않는다.

```ts
r.status === 200 || (r.name === 'touch_user_activity' && r.status === 204)
```

[실행 스크립트 수정 diff](academy-g-production-recheck-20261025.patch). 실행본은 `.local/g-promotion-20261025/production.spec.ts`, 설정은 같은 디렉터리의 `production.config.ts`다. 인증 토큰은 무시되는 비공개 `.env`에만 두었으며 기록·커밋하지 않았다. 기존 검증 uid의 세션 refresh HTTP 200, 같은 익명 uid 유지, 신규 signup 0회. 기존 검증 후보·비교를 재사용했고 다른 사용자의 데이터를 열지 않았다.

```sh
PYTHONPATH=. uv run --frozen python .local/g-promotion-20261025/run-js.py \
  node_modules/@playwright/test/cli.js test \
  -c .local/g-promotion-20261025/production.config.ts
```

최종 실행 `2026-10-25T12:21:14.123Z`~`2026-10-25T12:21:26.536Z`(UTC), Playwright **1 passed / exit 0**. `pnpm lint`, `pnpm typecheck`, `pnpm test`도 exit 0. 제품 코드·명세·migration 변경 없음.

첫 실행에서는 점수·날짜 판정 이후 패널 닫기의 안정성 대기가 30초 timeout됐다. 결과를 보존하고, 요청한 검증에 필요 없는 패널 닫기·스크린샷과 브라우저 가짜 분포 주입 단계를 제거했다. 최종 실행은 실제 RPC/화면만 검사하며, 가짜 응답을 성공 증거로 사용하지 않았다.

## 실제 화면·RPC 결과

- URL: `https://gilmok-weld.vercel.app/compare`.
- 저장 비교: 모델 `0.4.0`, 기존 `reference_snapshot=20261012T013000Z`, 후보 5개.
- 관측한 RPC 기준분포 응답 7회 모두 `20261016T040000Z`; fingerprint `ca9ca0f95422c2b7fe14353cf6f4a5b38c723e0e42acad11930b6ebab1c746d0`.
- 로컬 정본과 화면의 원정밀 총점·신뢰도 일치. 순위 b > e > a > c > d. 아래는 넷째 자리로 표시했다.

| 후보 | 총점 | 순위 | 신뢰도 |
| --- | ---: | ---: | ---: |
| b | 92.7877 | 1 | 90 |
| e | 84.9937 | 2 | 90 |
| a | 83.0108 | 3 | 90 |
| c | 82.2096 | 4 | 85 |
| d | 81.7561 | 5 | 90 |

근거 패널 → **데이터 출처·기준일**을 실제로 펼쳐 `기준분포 20261016T040000Z` 표시와 옛 ID `20261012T013000Z` 부재를 assertion으로 확인했다. 날짜는 **2026-10-16**이며 UI는 현재 compact snapshot ID 형식으로 표시한다. 채점 시각은 이번 실행 시각으로 별도 표시한다. 원천별 기준일을 새 분포 날짜로 일괄 바꾸었다는 뜻은 아니다.

실제 재열기는 최신 분포로 재계산하므로 분포 불일치 배지/문구는 없었다. 이 동작은 10/23 관측과 동일하다. 채점·조회 RPC HTTP 200, activity RPC HTTP 204, pageerror 0. 상세 수치와 실제 표시 문자열은 [결과 JSON](academy-g-production-recheck-20261025.json).

## 상태와 다음 단계

[원격 승격·백업·해시 보존 보고서](academy-g-remote-promotion-20261023.md)의 COMMIT 결과는 유효하며, 당시 HTTP204 오판에 따른 검증 중단은 이번 재검증 통과로 해소했다. 원격 원천·분포·캐시 재적재, 후보 좌표 교체, key 삭제, R2 쓰기는 하지 않았다.

③ #40은 조건부 승인이다. **#39 머지 확인 + 한별의 Vercel Production·Preview `JUSO_API_KEY`/`JUSO_COORD_API_KEY` 서버 전용 등록 확인** 전에는 dry-run/push를 시작하지 않는다. 이후 직전 dry-run에서 `20261021000000_juso_registration_coordinates.sql` 하나만 대기함을 확인하고 일반 push한다. push 직후 #40 Ready·머지 요청, 배포 후 신규 등록·Juso 출처·기존 좌표·쿼터 실증을 별도로 기록한다. ④ #41은 이번 승인에 포함되지 않는다.
