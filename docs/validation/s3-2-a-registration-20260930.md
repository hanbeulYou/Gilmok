# S3-2 A 등록·주소·브라우저 채점 검증

> 2026-10-01 후속 검증: Vineyard 팀으로 재연결·Preview 재배포 후 실제 icn1/Juso·Vworld200, 원격3곳 점수 일치·uid 격리·검색 한도·authenticated HTTP6조합을 통과했다. [최종 검증](s3-2-a-region-retry-20261001.md). 아래 내용은 당시 증거로 보존한다.

2026-09-30 · #22 Draft. #23 머지 `7eec24c`를 동기화했다. **로컬 구현·검증 완료, 최종 원격 migration 승인 대기**다. 원격 쓰기·Vercel 변수 변경·웹훅 활성화·공유 캐시 교체는 실행하지 않았다.

## 범위와 보존

- Juso 검색, 사용자 선택, 서버 재검증, Vworld 임시 좌표 1회, PNU 포함 검증, 등록 폼, 클라이언트 RPC/Worker/ScoreResult 연결을 구현했다. 검색 결과를 캐시하지 않는다. 키는 서버 환경에서만 읽는다.
- 상태는 fetching/scoring/scored/scored_provisional/error이며 첫 조회는 후보명·층을 유지한 스켈레톤이다. 주소 0건·다중·인증/쿼터·도형 겹침/PNU 불일치를 구분한다. 서울 밖 등록은 거부하며 건물 미적재는 허용하고 채점 결측 규칙을 따른다.
- 후보는 최대5곳, 같은 주소·층은 경고 후 허용한다. 층 −5…−1/1…30, 면적 양수, 금액 0 이상, 미입력 NULL, 별칭20자를 검증한다. 현재는 미저장 메모리 후보이며 새로고침 시 초기화됨을 표시한다. owner DB 저장·비교 저장은 C다.
- 기존 후보 필드/RLS·공유 캐시·점수 수식/가중치/신뢰도·전체 분포 RPC는 보존했다. 상태 전달을 위해 기존 score_inputs 본문을 내부 이름으로 이동하고 얇은 wrapper에서 uid별 request_id만 추가한다.
- Zustand5.0.8은 AGENTS의 지정 상태 스택으로, /new→/compare 전환 때 후보와 재시도 작업을 유지하기 위해 추가했다. 새 지도·차트 라이브러리는 없다.

## A0 T1 동일성

프리셋 academy_v0 v0.3, 입력1.3, reference0.1.2 snapshot20260923T111436Z, exposure0.2.2. 반경800m·학교1km·임대료/면적 NULL. A0 Juso/Vworld 좌표 그대로이며 기존 Kakao 기반 기관·기준 분포의 전량 전환은 별도 T2다.

| 항목 | a 역삼로460 3층 | b 도곡로409 2층 | c 역삼로546 3층 |
| --- | ---: | ---: | ---: |
| 총점 | 85.085004969152 | 93.399732739448 | 83.864481627843 |
| 신뢰도 | 90 | 90 | 85 |
| demand | 96.5636417498 | 99.7630097758 | 84.4178927619 |
| flow | 99.3340622205 | 98.8768512076 | 97.1871583342 |
| transit | 38.3368032600 | 81.7010897349 | 60.7872321613 |
| cluster | 97.4774057801 | 98.4100361975 | 85.9101443181 |
| exposure | 38.3838383838 | 51.3994910941 | 63.2812500000 |
| building | 100.0000000000 | 100.0000000000 | 100.0000000000 |
| environment | 93.4045917495 | 87.6534408801 | 91.9829399170 |
| rent_efficiency | NULL | NULL | NULL |

순위 b > a > c. 고정 입력의 전체 ScoreResult(8축·총점·신뢰도·근거)가 full-distribution 경로와 compact 경로에서 **deepStrictEqual** 통과했다. 원격 HTTP 검증으로 표현하지 않는다.

## 브라우저 실측

로컬 Next.js production build + 로컬 실제 Supabase + 실제 Juso/Vworld API + Chrome(headless). 주소 검색→정확한 도로명 결과 선택→층 입력→채점을 수행했다. 검색에 유사 지번/부번 결과가 함께 나오면 첫 행을 자동 선택하지 않고 정확한 도로명 결과를 선택했다.

| 후보 | 화면 총점 | 등록 버튼→점수 표시(ms) |
| --- | ---: | ---: |
| a | 85.09점 | 1126.175 |
| b | 93.40점 | 1013.619 |
| c | 83.86점 | 959.340 |

각1회 관측이며 p95/콜드 성능 기준 판정이 아니다. 검색 대기 시간은 제외한다. 3후보에서 Worker 생성1회, pageerror0. 채점 RPC는 후보별 score_inputs800/1000 + exposure_inputs_v022 + score_reference_percentiles 각1회(총12회), activity RPC3회다. 데스크톱1280×900와 모바일390×844에서 점수·결측 배지를 확인했고 가로 넘침은 없었다. 서버 비밀은 브라우저에 전달하지 않는다.

스크린샷/원시 입력은 로컬 `.local/validation/s3-2-a-registration/`에 있고 비밀 값 없는 숫자 증거는 [JSON](s3-2-a-registration-20260930.json)에 기록한다.

## DB·자동 검증

- `pnpm lint`, `pnpm typecheck`, `pnpm build`, `pnpm visibility:build` 통과.
- Vitest101, Python258, DB194 통과. DB 테스트는 로컬 롤백 범위다.
- uid100회 제한·101번째 거부·공급자별70/30 카운터·두 uid 격리·공용 캐시 권한 거부·서버 시각 activity를 확인했다.
- 동일 주소 작업을 두 uid가 관찰해도 각각 다른 request_id다. owner SELECT만 허용하고 클라이언트 UPDATE는 거부한다. private cache ready 갱신이 두 owner의 투영에 반영된다. public 필드는 request_id/status/updated_at뿐이다. 800/1000m RPC가 동일 uid의 관찰 ID를 재사용한다.
- 관찰자 upsert의 address 인자/컬럼 모호성을 로컬 테스트에서 발견했다. 이미 적용한 파일을 수정하지 않고 후속 migration에서 명시적 constraint target으로 고쳤다. 전체 DB 재검증194개 통과.
- Realtime publication 구성까지 A. 실제 구독→화면 자동 재조회·실제 Actions pending 검증·6시간 sweep/상시 운영은 B다. 정리 배치30/90일 dry-run·저장은 C다.

## 최종 원격 dry-run — 적용 승인 요청

실행 2026-09-30T11:27:06.434690+00:00, 0.628초, exit0. `supabase db push --linked --include-all --dry-run`. A0 migration이 원격에서 먼저 적용되어 earlier WIP2개를 포함하기 위해 include-all을 명시했다. 원격 SQL 실행 검증이나 push는 아니다.

| 미적용 migration | SHA-256 |
| --- | --- |
| `20260930072813_registration_reference_percentiles.sql` | `5ac5e84e0f45e8ce05d65d4829afad6663477459a7fc8a93a962e643da5df9d7` |
| `20260930073201_registration_candidate_context.sql` | `bf18dafd1a2e368e877ce5310525662cedd6e36fa210d1d86f3a1c0462f01718` |
| `20260930110600_registration_usage_and_candidate_fields.sql` | `7df31b4645104715a6d20b64c256891d86e55ee88a54f8172f9673c3739a0d2b` |
| `20260930112203_registration_lookup_projection.sql` | `d3d96e6b5be4d5fcd432f4cd6ab8d2465e4e64dea8105e222e207d1f31e514ca` |
| `20260930112543_registration_lookup_conflict_target.sql` | `a6a010af91425ffe5f523effe5420c678693eb7c43d9b6eeb12510322028dcde` |

이 5개만 적용 대상으로 보고됐다. 후보 메타데이터·private quota/activity·uid별 상태 전달의 추가와 함수 wrapper이며 기존 cache 삭제·원천 교체는 없다. A0 `20260930083312`는 이미 적용되어 목록에 없다. 원격 push는 이 최종 목록의 사용자 승인 후 실행한다.

되돌릴 때는 프론트부터 기존 버전으로 되돌리고 새 CLI migration으로 wrapper를 제거한 뒤 내부 원본 함수를 public.score_inputs로 복귀한다. 상태 구독을 중단하고 새 RPC 권한을 회수하며 후보/카운터/관찰 데이터는 보존한다. 자동 rollback/과거 migration repair는 실행하지 않았다.

## 사용자 단계

1. 위5개 원격 push 승인.
2. Vercel에 서버 전용 JUSO_API_KEY·VWORLD_API_KEY 등록 후 재배포. 공개 변수는 기존2개 그대로다. A0 단계에서는 Vercel 변경을 하지 않았고 이 설정은 A Route Handler용이다. DB 관리자/서명 비밀은 추가하지 않는다.
3. 원격 적용·Preview 등록 검증 후 사용자가 머지. #22는 승인 전 Draft 유지. Juso 좌표 키 발급·13,542건 재산출·Kakao 키/cache 삭제는 별도 승인 범위다.
