# S3-2 등록·매트릭스 구현 계획

base: main

- 작성일: 2026-09-29 · 승인 반영: 2026-09-30. **S3-2 계획 승인. 사용자 결정으로 카카오를 전면 제거하고 Juso로 전환한다. A0 계획은 승인되었다. A0 구현과 #22는 공급자 인터페이스를 맞춰 병행하고 데이터는 A0 머지 후 동기화한다.**
- A0 계획/구현 브랜치: `s3/juso-transition`, PR A WIP: `s3/registration-data`([#22](https://github.com/hanbeulYou/Gilmok/pull/22)). 기준 커밋: `e93740798da8e61560e707bb1315a4dd0194f7b1`(#21 머지). 각 구현 PR도 앞 PR 머지 후 최신 `main`에서 `s3/…`로 분기한다.
- A0는 Juso 검색+Vworld 좌표로 3곳 검증을 진행한다. 13,542건 재산출은 JUSO_COORD_API_KEY 발급 후 별도 실행·보고한다. #22 DB/RPC/어댑터→UI는 인터페이스 계약을 맞춰 병행한다. 원격 migration은 dry-run 보고 후 별도 승인하며, scoring v0.3 수식·프리셋은 유지한다.
- 기준: [AGENTS.md](../../AGENTS.md), [screens.md §0·§3·§4·§8](screens.md), [scoring-spec v0.3](scoring-spec.md), [S3 운영](../operations/s3-foundation.md), [S3-1 마감 검증](../validation/s3-1-closeout-20260929.md), [S2-4 v0.3](../validation/s2-4-v03-20260926.md), [S3-1의 확정된 S3-2 결정](s3-1-plan.md#9-예상-리스크와-후속-경계).

## 1. 목표와 범위

screens.md §8의 S3-2: **[R] 폼, RPC 3종 호출, 클라이언트 채점, ComparisonMatrix(슬라이더 포함), 결측·pending·배지, 근거 패널, 모바일 카드**를 구현한다. 사용자 추가 범위는 주소 자동완성 Route Handler·요청자별 Realtime·익명 계정 정리 정책·등록→채점→슬라이더→저장 Playwright E2E 1개다.

최종 완료 기준:

1. 역삼로460 3층 / 도곡로409 2층 / 역삼로546 3층을 주소→PNU→도형 경로로 등록하고, 800m·학교1km·임대료/면적 미입력에서 A0가 검증·승인한 새 fixture의 v0.3 8축·총점·신뢰도와 일치한다. 전환 전 S2-4 결과와의 차이는 A0에서 보고한다.
2. 최대5개 후보의 축 행 머리 슬라이더로 RPC·Worker 재호출 없이 재계산한다. 조작→계산→화면 반영을 실측하며 p95≤100ms를 통과 기준으로 삼고 max는 기록한다.
3. pending 후보가 새로고침 없이 ready로 전환되고 건물 점수·총점·신뢰도·근거가 함께 갱신된다.
4. 익명 정리 배치의 dry-run에서 미저장30일·저장 후보 있는 uid90일 미활동 대상과 보존 대상을 구분함을 검증한다. 원격 삭제 자동 실행은 별도 승인 전까지 비활성이다.
5. Playwright에서 등록→채점→슬라이더→익명 저장→동일 uid 재열기 흐름 1개가 통과한다.

S3-3의 2D 지도, S3-4의 3D·노출 샘플 시각화, S3-5의 랜딩·이메일 승격 UI·공유 리포트는 구현하지 않는다. exposure **계산 Worker**는 이번 점수에 필요하므로 포함한다. 익명 저장은 이번 E2E를 위해 포함하되 공유·이메일 연결을 요구하지 않는다(screens §4.7 및 사용자 명시 범위).

## 2. 현재 구현과 대조한 사항

| 항목 | 현재 상태 | S3-2 처리 |
| --- | --- | --- |
| `/compare` | `lib/supabase/preview.ts`가 고정 좌표 RPC1회·익명 세션 재사용 | 인증 중복 방지를 재사용하고 후보별 조회 조정기로 분리 |
| 백분위 | `score_reference_distribution(text,integer)`는 전체 float8 분포를 반환 | 기존 RPC는 배치/검산용 보존. raw→백분위 새 RPC와 순수 함수 입력 어댑터 추가 |
| 채점 | `lib/scoring/score.ts`의 `score()`·`reweight()`는 v0.3 | 수식·가중치·결측·신뢰도 정책 유지. 분포 공급 방식만 호환 확장 |
| exposure | `exposure_inputs_v022`, `workers/visibility.worker.ts`, `lib/visibility/client.ts` | 기존 5186 scene·model0.2.2를 그대로 사용 |
| 위치·신뢰도 보조값 | 검증 스크립트가 PNU 도형 포함·서울 경계 거리·법정동명 별도 조회 | 등록용 위치/context RPC로 실제 DB 값을 제공. 서울 여부를 UI에서 추정하지 않음 |
| 주소 캐시 | `public.geocode_cache(address,provider)`는 공용·단일 지점 | Juso 선택 주소 결과로 통합. 검색 목록/개인 입력과 분리, 일반 사용자 쓰기 금지 |
| 주소 큐 | 비공개 작업1건에 `requester_uid` 하나, 공용 주소 중복 방지 | 같은 주소를 요청한 여러 uid를 각각 상태 관찰자로 연결 |
| Realtime | 비공개 캐시 직접 구독 금지, 상태3필드만 노출하기로 확정 | RLS 상태 투영 테이블과 조회 뷰. SQL VIEW 자체를 publication에 넣지 않음 |
| 저장 | candidates는 좌표·층·임대료·면적, comparisons는 후보ID배열·weights·preset_id | 주소·별칭·조회상태·버전·순서와 수정 시각을 추가. 기존 owner RLS 유지 |
| 원격 운영 | Auth anonymous 활성, authenticated timeout15초, 주소 트리거D·`INGEST_REMOTE_ENABLED=false` | 실증 창만 일시 활성화. 서비스 상시 처리 여부는 D5 결정 |
| Vercel | 공개 Supabase 변수2개만 존재 | A0 이후 Juso 검색/좌표 키를 서버 전용으로 사용. Kakao 등록 금지 |

이미 승인된 두 불일치는 재결정하지 않는다: 분포 전체 대신 raw→백분위 RPC, 비공개 주소 캐시 대신 요청자별 상태 구독. screens.md 원문은 이번 계획에서 고치지 않는다. scoring-spec §1.1의 옛 `exposure_inputs_v021` 표기보다 현행 §5.5·코드·S3 인계의 **v022**를 따른다.

## 3. PR 분할 — A0 선행 + 승인된 A/B/C

승인된 A/B/C 앞에 공급자 교체 A0를 둔다. 각 PR 설명에 해당 하위 완료 기준과 최종 S3-2 기준 중 충족한 항목을 구분한다.

| PR / 브랜치 | 변경 범위·예상 파일 | 마이그레이션 | 해당 PR 완료 기준 |
| --- | --- | --- | --- |
| **A0 공급자·단계별 전환** / `s3/juso-transition` | Juso 검색+Vworld 임시 좌표·배치·workflow·provenance·3곳 검증 | provider CHECK/provenance 확장, 기존 cache 보존. 13,542건 기관/분포 전환은 좌표 키 발급 후 별도 실행 | 이번: 3곳 PNU/도형/8축 T1·migration dry-run. 후속: 전량/T2·고정5셀·승인 manifest |
| **A 데이터·등록 기반** / `s3/registration-data` | `app/api/address-search/route.ts`, `app/new/page.tsx`, `components/candidate/{AddressSearch,CandidateForm}.tsx`, `lib/geo/`, `lib/supabase/`, `lib/scoring/{types,percentile,score,axes}.ts`의 호환 어댑터, `lib/compare/load-candidate.ts`, 기존 Worker 연결 | 위치/context·raw 백분위 RPC, 공용 Juso 캐시 접근/uid별 일일 제한, 후보 저장 필드, 최소 상태 투영·관찰자 연결 | 주소 선택·검증→3종 채점 RPC→Worker→ScoreResult. 고정3곳 8축/총점/신뢰도 일치. 두 uid 권한·검색 제한·배치 캐시 보존. 기존 전체 분포 경로와 새 경로 동등성. 완성 매트릭스는 B |
| **B 비교·근거·실시간** / `s3/comparison-matrix` | `app/compare/page.tsx`, `components/compare/`의 매트릭스·슬라이더·배지·근거·모바일 카드, `lib/compare/{store,status,subscriptions}.ts` | A 상태 투영의 Realtime publication/권한 등 필요한 추가 변경만 | 데스크톱/모바일 동일 점수·근거·결측, 슬라이더 p95≤100ms(max 기록), 두 uid Realtime 격리, pending→ready 무새로고침, 3분 지연·재접속·순서 역전 검증 |
| **C 저장·익명 정리·종합 검증** / `s3/comparison-save-retention` | `lib/compare/persistence.ts`, 저장/프리셋 UI, `ingest/cleanup_anonymous.py`, `.github/workflows/cleanup-anonymous.yml`, `playwright.config.ts`, `tests/e2e/compare.spec.ts`, 검증·운영 문서 | 비교 저장 확장/명명 가중치 프리셋, activity·정리 함수/인덱스 | 익명 저장·재열기·owner RLS, E2E1개 통과, 정리 dry-run의 대상/제외 검증·로컬 실제 삭제 및 승격 보존, 최종 실제3곳/성능/실시간 증거 기록 |

**A 내부 체크포인트:** DB/RPC/채점 어댑터의 로컬 단위·DB 검증 후 WIP 커밋을 먼저 남긴다. 그 뒤 Route Handler·등록 폼·브라우저 Worker UI를 연결한다. 카카오 저장 경로는 폐기한다. A0의 새 기준 fixture/캐시 신뢰 경계를 받아 UI를 연결하며, #22의 독립 WIP 코드는 보존한다.

마이그레이션은 각 PR에서 `supabase migration new`로 생성하고 새 파일에만 작성한다. 계획 단계에서는 생성하지 않는다. 문서와 코드는 별도 커밋한다. 새 라이브러리는 지정 스택인 Zustand와 Playwright만 필요하며 버전 고정·lockfile·추가 이유를 해당 PR에 기록한다. 지도 라이브러리는 이번에 추가하지 않는다.

## 4. 등록·주소·RPC 계약

### 4.1 주소 자동완성·등록 좌표와 배치 캐시

2026-09-30 A0 승인(D2): **사용자 Route Handler는 공용 캐시에 쓰지 않는다. 검색은 무캐시 실시간(`no-store`), 좌표는 등록 시 1회 조회하여 해당 uid의 후보 행에만 저장한다.** 공용 `public.geocode_cache`는 Actions/직접 DB URL 배치만 쓴다. uid별 응답 캐시·서명 RPC·캐시 서명키는 만들지 않는다. A0에서 Vercel 변수를 추가하지 않는다.

- Route Handler `runtime='nodejs'`, `preferredRegion='icn1'`: 국내 사용자와 국내 주소 API의 왕복을 줄이는 선택. 현재 Supabase Tokyo와 같은 리전이라는 뜻은 아니다.
- 인증 실패 시 재시도 후 검색. uid별 KST 하루100회는 공급자 쿼터와 별개 남용 제한이다. 검색/좌표/Vworld 호출량을 각각 기록하고 키·응답 echo·개인 검색어를 운영 로그에 남기지 않는다.
- Juso 검색은 도로명·지번·건물명 목록을 반환한다. 사용자가 선택한 `admCd/mtYn/lnbrMnnm/lnbrSlno`로 PNU를 구성한다. 주소0건·다중·인증/쿼터 오류를 구분하며 인증 실패를 폴백으로 숨기지 않는다.
- A0에서는 `JUSO_API_KEY` 검색 + **Vworld 좌표**로 3곳만 검증. `lib/geo/address-provider.ts` 계약 v1과 `/ingest/juso.py`의 검색/좌표 공급자 분리 구조를 #22와 맞춘다. 좌표의 실제 provider와 원CRS를 보존하며 Vworld 좌표를 Juso 출입구 좌표로 표시하지 않는다.
- JUSO_COORD_API_KEY 발급·좌표 적용 승인 후 좌표제공 API(5179→4326 저장/5186 계산)로 교체한다. 기존 키가 생겼다는 이유만으로 전량 실행하지 않는다. 좌표 API 5초10건 제한은 모든 실행 인스턴스 합계로 지킨다.
- 선택 식별자/PNU→도형 포함 검증. 미포함/다동/다른 PNU는 그대로 사유를 표시한다. 중심점·최근접 도형으로 자동 교체하지 않는다.
- `KAKAO_REST_API_KEY`는 Vercel에 등록하지 않는다. #22는 서버 공급자 구현과 필요한 배포 키를 후속 검토하며 DB 관리자키/서명키는 추가하지 않는다. 배치·대장 조회는 `/ingest`만 호출한다.

### 4.2 폼과 위치 확인

- `/new` 페이지를 기본으로 사용하고 `/compare`의 후보 추가에서 연결한다. 주소, 정수 층 **−5…−1 또는 1…30** 필수, 전용면적>0·보증금/월세/관리비≥0·별칭≤20자 선택. 빈 선택 입력은 NULL이며 0과 구분한다.
- 500㎡ 이상 안내·임대료 축 v0.3 미확정 안내를 폼에서 보여준다. 주소+층 중복은 경고 후 허용하고 후보5개 상한을 UI와 저장 함수 양쪽에서 검증한다.
- 등록용 `resolve_candidate_location` RPC(제안)는 선택된 Juso(또는 검증된 Vworld) 좌표·PNU를 받아 동일 PNU 도형과 ST_Covers를 확인하고, 후보 좌표·건물 식별자·매칭 사유·서울 내부 여부·서울 외곽 경계 거리·법정동명 context를 반환한다. 외부 API를 호출하지 않는다.
- **전환 전 S2-4는 Kakao 좌표를 사용했다. A0에서 Juso 출입구 좌표의 같은 PNU/도형 포함을 새로 검증한다.** 미포함이면 거리·사유를 보고하고 중심점으로 바꾸지 않는다. 다동/겹침·PNU 불일치에서는 임의 중심/첫 도형을 고르지 않고 확인 필요로 남긴다.
- 도형 미적재는 등록 자체를 막지 않는다. 서울 안이면 주소 대장 경로·exposure 결측을 그대로 적용한다. 서울 밖 신규 등록은 screens §3대로 막고, 과거/복원 후보가 밖에 있을 경우에는 원래 결측 이유를 표시한다.

### 4.3 세 종류의 채점 RPC와 호출 순서

여기서 **3종은 RPC 종류 수**다. `score_inputs` 두 반경 때문에 정상 등록의 채점 호출 수는4회다. 위치 확인·검색/상태/저장 helper는 별도이며, 슬라이더에는 호출이 없다.

| 종류 | 호출·입력 | 출력·소비 |
| --- | --- | --- |
| `score_inputs` | 같은 후보 좌표·층·주소로 800m와1000m 병렬 | 주 입력은800m, 학교 수요만1000m. 기존1.3 데이터 의미 유지 |
| `exposure_inputs_v022` | 같은 좌표. 위 두 조회와 병렬 | 5186 scene에 요청 층 주입→기존 Worker0.2.2→ExposureInput |
| `score_reference_percentiles` (신설 제안) | 앞의800/1000m와 context로 `extractReferenceRaw()` 수행 후 raw7개를 한 번에 전송 | demand·flow·transit3지표·environment·포화 근거의 백분위, 모집단·coverage·source/snapshot 메타데이터 |

`cluster` 점수는 기존 p50=3.332204510175204, p99.97=7.070653980704802 상수만 사용한다. 포화 백분위는 근거 전용이다. raw 연산·축 합성·규칙·신뢰도·총점은 브라우저의 기존 순수 함수로 수행한다. 서버가 ScoreResult를 새로 계산하는 구조로 바꾸지 않는다.

백분위 계약은 다음을 만족한다.

- 요청에는 preset id·radius800·최대7개 지표/원시값을 담는다. 서버는 유한수·허용 키를 검증하고 동일 문장 스냅샷의 기준분포만 읽는다. 응답의 reference_version0.1.2·schema1.3·원천 메타데이터는 기존 순수 함수의 공통 검증에서 입력과 대조한다.
- 기존 `lib/scoring/percentile.ts` 그대로: 동일값 수 E>0이면 `100×(L+(E+1)/2)/N`, E=0이면 `100×L/N`. L은 엄격히 작은 값 수, N은 비NULL 모집단이다. NULL·빈 모집단·소스/버전 불일치는 기존 reason을 유지한다. Postgres의 percent_rank/cume_dist로 대체하지 않는다.
- raw를 반올림하지 않고 float8로 대조한다. 역거리의 100−p 방향은 기존 순수 함수에서 적용한다. 응답을 요청 raw/key/radius/snapshot과 묶어 오래된 결과를 다른 후보에 쓰지 않는다.
- `ScoreReference` 전체 분포 경로는 기존 검산용으로 보존하고, 사전 계산된 백분위 입력 타입을 추가한다. `referencePercentile()`의 메타데이터 검증·출력 계약을 공유한다. 가짜 분포 배열을 만들어 점수를 맞추지 않는다.
- 근거 패널용 히스토그램은 snapshot별 소규모 집계 bin20개·경계값·모집단 크기만 반환/캐시한다. 원시 분포 전체는 내려받지 않는다. 클라이언트가 이미 가진 백분위 표시와 분포 모양을 구분하고 cluster 고정 스케일을 백분위 점수처럼 그리지 않는다.

후보별 입력 세대 번호·좌표·층·reference snapshot으로 조회와 Worker 결과를 묶는다. 삭제/층 변경 후 도착한 예전 응답은 버린다. Strict Mode 중복 등록·RPC·signup을 공유 Promise로 막는다. 후보 내3회 초기 조회는 병렬, 동시에 처리하는 후보는 우선2개로 제한하고5곳 실측으로 확인한다. Worker는 재사용하고 슬라이더에서는 호출하지 않는다.

## 5. 화면·로딩·잠정 상태

### 5.1 콜드 첫 실행 2~4초

기존 원격 SQL 첫 실행은 일부 조합에서 약3.8~4.1초였다. HTTP·백분위·Worker 완료 시간을 합쳐야 하므로 **4초 내 완료를 보장하는 타이머로 쓰지 않는다.** authenticated의15초 statement_timeout을 유지한다.

| 상태 | 화면 | 점수 처리 |
| --- | --- | --- |
| draft | 폼과 필드 오류 | 미채점 |
| fetching | 후보명/층은 즉시, 총점·8축은 스켈레톤. `aria-busy`와 “주변 데이터를 불러오는 중” | 0점·이전 후보 점수를 먼저 표시하지 않음 |
| 2초 경과 | 같은 스켈레톤에 “첫 조회는 조금 더 걸릴 수 있습니다” | 단지 오래 걸린다는 이유로 잠정 점수를 만들지 않음 |
| scoring | 사용 가능한 데이터 축은 준비, “노출 계산 중” 표시 | 입력/백분위가 검증된 뒤 Worker가 늦으면 v0.3의 exposure pending으로 계산하고 잠정 표시 |
| scored_provisional | 건물 “확인 중”, 총점·신뢰도 옆 “잠정”; 다른 축은 정상 | building pending의 기존60점과 신뢰도−15를 그대로 유지. UI에서 임의 NULL/0으로 바꾸지 않음 |
| ready | 일반 점수·근거 | ready 재조회가 끝난 뒤 잠정 해제, 총점400ms 변경 효과. reduced-motion은 즉시 반영 |
| pending/processing 3분 | “건물 정보 확인 지연 — 나중에 다시 열면 반영됩니다” | 타임아웃이 ready를 뜻하지 않음. 상태 구독은 유지, 저장 가능 |
| RPC 실패/Worker 실패 | 해당 오류·재시도; 전체 실패는 배너 | 소스 조회 실패를 관측0으로 취급하지 않음. 같은 uid의 마지막 저장 결과만 시각·버전을 붙여 읽기 전용 표시 |

15초 DB timeout과 별도로 HTTP 전체 요청의 유한 대기/취소를 둔다(초안25초). 자동 무한 재시도·주기적 score_inputs 폴링은 하지 않는다. 실패한 호출만 재시도하되 원천 snapshot이 바뀌었으면 입력 묶음을 함께 갱신한다.

### 5.2 매트릭스·근거·모바일

- ≥1024px: 총점 고정행+8축 행, 후보 최대5열. 기본 총점 내림차순, NULL은 마지막, 동률은 안정적인 기존 순서. 수동 열 드래그 고정 후에는 슬라이더로 순서를 바꾸지 않는다.
- 각 축 행 머리 슬라이더0~40. 드래그 중에는 `reweight()`만 적용하고 열 순서는 유지, 놓을 때 재정렬한다. 초기화·수정됨 표시·키보드 조작을 제공한다. confidence와 normalized는 가중치로 바뀌지 않는다.
- 결측은 회색 “—/평가 불가”와 한글 사유, pending은 확인 중, 총점에는 잠정·N축 재배분. 0점은 숫자0으로 구분한다. 전 축 가중치0은 v0.3대로 total=NULL이며 가중치를 자동 복원하지 않는다.
- 포화 low/mid/high·원시값·서울 백분위·외부 통학 수요 한계, academy_eligible의3값·R6 위험 문구를 기존 evidence/derived에서 읽는다. 경고색을 새 점수로 사용하지 않는다.
- 셀 클릭1회에 원시값·백분위/모집단·규칙·결측/추정·재배분 근거. 후보 선택은8축 아코디언+confidence.reasons 전체+meta.sources 기준일+all_floors 표다. 알 수 없는 reason도 원문을 보존해 누락하지 않는다.
- 임대료는 사용자 입력/월 환산·㎡당 값·매매 참고값만 표시하고 점수는 NULL(미입력 또는 v0.3 미확정). exposure 근거는 성공·결측·대기 모두 “가로수·가로시설물·간판 크기 미반영, 현장 확인 필요”를 표시한다.
- <1024px: 후보 세로 카드·8축 막대·총점/신뢰도·스와이프 선택, 상단 가중치 바텀시트, 근거 탭을 제공한다. 지도 탭의 실제 화면과3탭 완성은 S3-3다. 이번에 작동하지 않는 지도 기능을 만들지 않는다.

## 6. Realtime pending→ready

1. 공용 작업 큐는 그대로 유지한다. `app_private.candidate_lookup_watchers`(제안)에 사용자별 불투명 request_id·uid·내부 작업 연결을 둔다. 기존 큐의 최초 requester_uid만으로 구독 소유권을 판정하지 않는다.
2. `public.candidate_lookup_status`는 **request_id·status·updated_at 3필드만** 가진 상태 투영 테이블이다. private 관찰자 매핑을 확인하는 좁은 함수로 owner RLS를 강제하고 클라이언트 쓰기를 금지한다. 조회 뷰도 security_invoker로 동일 세 필드만 제공한다.
3. 이 투영 테이블만 Realtime publication에 추가한다. 주소·PNU·대장 payload·uid·내부 작업ID를 이벤트에 싣지 않는다. 일반 SQL VIEW 직접 구독 대신 투영 테이블의 INSERT/UPDATE를 구독하는 구현으로 S3-1의 상태 뷰 계약을 충족한다. DELETE 이벤트는 사용하지 않는다. [Supabase Postgres Changes·RLS 문서](https://supabase.com/docs/guides/realtime/postgres-changes)를 따른다.
4. `score_inputs`의 제한된 주소 조회 helper가 요청자 관찰자를 연결하고 `meta.building_lookup.request_id`를 추가 반환한다. 기존 필드와1.3 의미는 유지하는 additive 변경으로 검증한다. 800/1000m 동시 호출과 같은 주소의 여러 uid는 공용 작업을 중복 생성하지 않고 각자의 request_id를 받는다.
5. 작업 processing·캐시 ready/not_found/ambiguous·작업 실패가 커밋될 때 상태 투영도 갱신한다. 작업 done만으로 ready로 표시하지 않고 **실제 캐시 상태**를 확인한다. 원천/캐시 payload는 계속 비공개다.
6. 브라우저는 구독 SUBSCRIBED 후 현재 상태를 다시 조회한다. 구독 전에 ready가 된 경우도 놓치지 않는다. 재접속에도 상태를1회 조회하고 중복/역순 이벤트는 updated_at과 후보 입력 세대로 무시한다.
7. ready면 해당 후보의 주800m 입력을 다시 조회한다. 위치·층·소스가 같으면 학교 입력·reference·Worker는 재사용하고 `score()`와 현재 가중치 `reweight()`를 실행한다. building뿐 아니라 pending 신뢰도 감점·총점·근거도 함께 갱신한다. 소스 fingerprint가 달라지면 필요한 입력/백분위까지 새로 받는다.
8. 삭제·다른 uid·페이지 이탈 시 구독을 해제한다. auth token 갱신을 Realtime에 전달한다. 상태 미도착3분은 지연 표시이며, 실제 실패는 실패 사유/재시도 정책으로 구분한다.

두 uid가 같은 주소를 요청하는 경우와 서로 다른 주소를 요청하는 경우를 모두 검증한다. RPC로 유효한 자기 요청을 만든 적 없는 uid는 request_id를 알아도 조회/구독할 수 없어야 한다. local 실제 Realtime 테스트로 event payload 키가 정확히3개인지 확인한 뒤 원격 검증한다.

## 7. 저장과 익명 사용자 누적 정리

### 7.1 저장

- candidates에 주소·별칭·PNU/도형 연결 메타데이터·updated_at·pending request 연결을 추가한다. 도형 미적재 후보를 저장할 수 있게 연결 필드는 nullable이다. 입력 임대료는 기존 owner RLS 안에만 둔다.
- 후보 입력의 deposit_krw/monthly_rent_krw/maintenance_krw/exclusive_area_m2는 기존 DB deposit/user_rent/management_fee/area_m2에 명시적으로 매핑한다. 후보 삭제는 소유 비교의 candidate_ids도 같은 트랜잭션에서 정리하고 빈 비교는 제거해 고아 ID를 남기지 않는다.
- comparisons는 원래 후보ID배열의 순서와 weights를 재사용하고 preset_version·reference snapshot·updated_at을 추가한다. owner 검증과1~5개 제한은 DB에서도 유지한다. 하나의 저장 RPC 트랜잭션으로 후보·비교를 저장해 부분 저장을 막는다.
- 재조회 시 같은 uid의 입력·가중치·순서·잠정 상태를 복원한다. `ScoreResult`/기준일의 마지막 스냅샷은 uid별 로컬 캐시에 보관해 전체 RPC 실패 때만 읽기 전용으로 표시하고 새 원격 입력과 섞지 않는다. 새 브라우저에는 다른 uid의 캐시를 복원하지 않는다.
- 명명 가중치 프리셋은 owner RLS의 작은 `user_weight_presets`로 저장한다. preset v0.3 원본은 수정하지 않는다. 0~40 슬라이더 값을 보존하고 정규화된 비율을 함께 검증해 복원 시100점짜리 슬라이더로 변하지 않게 한다. 전체0인 프리셋 저장은 안내 후 막되 비교 total=NULL 계약은 유지한다.
- 첫 익명 저장에 브라우저 변경/저장소 초기화 시 복구 불가와 승인된 미활동 보존기간을 알린다. 계정 승격·공유 화면은 S3-5이며 이번에 확대하지 않는다.

### 7.2 정리 정책 제안

**확정: 미저장 uid는30일, 저장 후보가 있는 uid는90일 미활동 후 그 소유 데이터와 함께 정리한다. GitHub Actions 일1회04:00 KST.** S3-2 완료 기준은 원격 dry-run까지다. 원격 실제 삭제·스케줄 활성화는 대상 보고 후 별도 승인한다.

[Supabase 공식 문서](https://supabase.com/docs/guides/auth/auth-anonymous)는 익명 사용자 자동 정리를 제공하지 않으며 오래된 익명 사용자를 SQL로 정리하는 예를 제공한다. 다만 그 예의 created_at만으로 **미활동**을 판정하지 않는다. 다음 정책은 이 제품의 제안이다.

- `app_private.user_activity(user_id,last_active_at)`에 서버 시각으로 기록한다. 앱 진입·전경 복귀·유효 검색/등록/저장 시 갱신하고, 전경에서1시간 간격으로만 갱신한다. 백그라운드 타이머/토큰 자동 갱신만으로 계정을 영구 보존하지 않는다. 클라이언트가 미래 시각·다른 uid를 쓸 수 없다.
- 기준은 `greatest(created_at,last_sign_in_at,last_active_at,소유 후보/비교 updated_at)`이 실행 기준시각−보존기간(미저장30일/저장 후보 있는 uid90일)보다 오래됐는지다. auth.users.updated_at만으로 활동을 추정하지 않는다. 기존 사용자는 정책 도입일을 activity 기준으로 초기화해 갑작스러운 삭제를 막는다.
- 반드시 현재 auth.users.is_anonymous=true이며 이메일/전화/외부 identity 연결 또는 진행 중인 계정 승격이 없는 사용자만 대상이다. activity·Auth 상태를 삭제 직전 다시 읽고, 등록 사용자·최근 활동·최근 저장·승격 사용자는 제외한다.
- 구현 위치: `/ingest/cleanup_anonymous.py`, `.github/workflows/cleanup-anonymous.yml`. 기존 GitHub Secrets의 원격 Session pooler DB URL을 사용한다. Vercel secret 추가나 브라우저 Admin API 호출은 없다. UTC cron은 `0 19 * * *`이며04:00 KST 예약은 정확한 실행 시각 보장이 아니다.
- 기본은 dry-run. 별도 `AUTH_CLEANUP_ENABLED=false`와 수동 `--apply`/승인된 대상 보고 해시를 요구한다. `INGEST_REMOTE_ENABLED`를 켜서 익명 정리를 실행하지 않는다. 주소 워커와 수명주기를 분리한다.
- dry-run은 기준시각·후보 uid 수·후보/비교/캐시 행수·최신 활동 범위·제외 사유 수·선정 해시만 보고하고 이메일·토큰·입력 주소·임대료는 기록하지 않는다. 실제 uid 목록이 필요한 승인 manifest는 공개 docs가 아닌 접근 제한 artifact에 둔다.
- 적용은 최대100uid씩 짧은 트랜잭션, 실행당 상한500uid 제안. auth.users와 activity를 일관된 순서로 잠그고 조건을 재검사해 로그인/승격/활동과의 경쟁을 방지한다. 원격 DB 직접 SQL 삭제 경로는 로컬 Auth API로 세션·연결 계정·FK 영향을 먼저 검증한다.
- 소유 candidates/comparisons는 기존 `ON DELETE CASCADE`를 사용하고 새 owner 데이터도 같은 정책이다. 공유 원천·공용 건물 캐시·공용 작업 큐는 삭제하지 않는다. 기존 큐 requester_uid는 SET NULL, 관찰자만 삭제한다. Storage 객체 소유 등 아직 없는 연관 데이터가 발견되면 대상에서 제외하고 보고한다.
- 이미 발급된 JWT가 남아도 새 쓰기 RPC는 현재 Auth uid 존재를 확인한다. 삭제 후 클라이언트는 저장소를 정리하고 새 익명 세션을 명시적으로 준비하며 실패를 무한 signup으로 재시도하지 않는다.

## 8. 검증 계획

### 8.1 v0.3 고정 기준

전환 전 기준은 [S2-4 Markdown](../validation/s2-4-v03-20260926.md)과 [전체 결과 JSON](../validation/s2-4-v03-20260926.json)이다. 입력1.3·reference0.1.2 snapshot `20260923T111436Z`·Worker0.2.2·academy_v0 0.3을 고정한다. 화면 예시 숫자를 기대값으로 사용하지 않는다.

| 항목 | a 역삼로460 3층 | b 도곡로409 2층 | c 역삼로546 3층 |
| --- | ---: | ---: | ---: |
| 총점 | 85.085005 | 93.372948 | 83.863983 |
| 신뢰도 | 90 | 90 | 85 |
| demand | 96.563642 | 99.763010 | 84.417893 |
| flow | 99.334062 | 98.876851 | 97.187158 |
| transit | 38.336803 | 81.701090 | 60.787232 |
| cluster | 97.477406 | 98.410036 | 85.910144 |
| exposure | 38.383838 | 50.890585 | 63.281250 |
| building | 100 | 100 | 100 |
| environment | 93.404592 | 87.653441 | 91.973459 |
| rent_efficiency | NULL | NULL | NULL |

주소→PNU→도형의 고정 조건:

| 후보 | 위도 | 경도 | PNU |
| --- | ---: | ---: | --- |
| a | 37.5025724504279 | 127.057585738094 | 1168010600109120013 |
| b | 37.4973692137569 | 127.055167024731 | 1168010600109380022 |
| c | 37.5042868910393 | 127.062872712855 | 1168010600109670000 |

위 좌표는 검증 JSON의 값이며 새로 추정한 좌표가 아니다. 각 PNU 도형의 해당 좌표 포함·register_pk/후보ID가 기준 JSON과 맞는지도 검사한다. 모든 normalized·total은 기준 JSON 대비 절대오차≤1e−9와 표의 소수6자리 일치를 확인하고, confidence/derived/missing_reason은 정확 일치한다. computed_at 같은 실행 시각만 비교에서 분리한다. 최종 순위는 b>a>c다.

이 표는 카카오를 사용한 **전환 전 기준**이다. A0는 기존 입력 T0/후보 좌표만 Juso로 바꾼 T1/기관·reference까지 갱신한 T2의 8축·총점·신뢰도·순위를 나란히 기록한다. 기존 좌표/분포로의 재현과 새 자료의 값을 구분한다. A0 승인 후 A/B/C는 새 fixture와 동일하게 채점하는지 검증한다. reference 전수 재생성은 A0의 데이터 전환 범위에 포함하되 v0.3 cluster 고정 상수·가중치는 변경하지 않는다. b>a>c를 유지시키려고 좌표·프리셋을 조정하지 않는다.

### 8.2 PR별 집중 검증

- **A:** raw 백분위의 동점·미관측 값·NULL·빈 모집단·최솟값/최댓값·거리 역방향·버전/소스 불일치, HTTP float8 정밀도. 기존 전체분포 score()와 새 adapter의 동일 입력 결과 대조. 주소 다중/보정/서울 밖/PNU 불일치·공유 cache 무단 쓰기 거부·일 제한 동시 요청·10건 큐 정책 보존. Worker/Node 동등성 재사용.
- **B:** 두 uid·두 브라우저의 실제 Realtime 테스트(로컬 DB/Realtime). 같은 주소 공동 대기·남의 request_id·구독 직전 ready·재접속·이벤트 중복·삭제/층 변경 후 늦은 결과·3분 지연·Worker 실패를 검증한다. mock 이벤트만으로 Realtime 완료 처리하지 않는다.
- **B 성능:** 최대5후보·완전한 근거를 넣은 production build에서 슬라이더 연속100회 측정. 함수 실행 시간과 입력→React 반영→다음 paint 시간을 분리해 p50/p95/max·환경·메모리를 기록한다. 데스크톱과390px 모바일 viewport 각각100회 표본의 p95≤100ms를 통과 기준으로 삼고 max는 기록한다. RPC/Worker 호출 증가0·normalized/신뢰도 불변을 함께 확인한다. 실제 기기 성능과 viewport 에뮬레이션을 혼동하지 않는다.
- **C 정리:** 미저장30일 경계/31일·저장90일 경계/91일 미활동/최근 조회·저장/오래됐으나 승격/승격 진행/동시 활동/정책 도입 전 사용자를 고정 시각으로 구성한다. dry-run 대상·제외 집합과 행수를 검증하고 로컬 실제 삭제 후 보존 uid·후보·비교·공용 큐/캐시를 대조한다. 실패 뒤 중복 삭제 없이 재개되는지도 확인한다.
- **공통:** `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm build`. SQL 변경 PR은 `pnpm test:db`, C는 `pnpm test:e2e` 추가. 기존 마이그레이션/ScoreResult v0.3 검증 회귀를 유지한다.

### 8.3 Playwright E2E 1개와 실제 운영 검증

Playwright 단일 핵심 시나리오: 새 browser context의 익명 uid → [R]에서 대치동3곳 주소 선택/층 입력 → Worker 포함 채점 → 매트릭스의 기준값·신뢰도 확인 → demand 슬라이더 변경과 p95≤100ms/무RPC 확인 → 익명 비교 저장 → 새로고침으로 같은 uid·후보3개·가중치·순서 복원. 키보드로 선택할 수 있는 role/label을 사용한다.

CI는 로컬 Supabase와 고정 원천 snapshot을 사용하며 Juso/Vworld 외부 경계만 승인된 공개 응답 fixture로 대체한다. 채점 RPC·순수 함수·Worker를 예상 점수로 mock하지 않는다. 전체 원천을 매 CI에 복원하기 어렵다면 A에서 필요한 최소 공간 원천과 기준분포 fixture를 추출·검산해 로컬 테스트 DB에 적재한다. 이는 테스트 데이터이며 운영 적재 범위 축소가 아니다.

별도의 승인된 원격 검증 창에서 실제 주소 검색·3곳 RPC/Worker 결과·브라우저 타이밍을 기록한다. pending1건은 상태 projection+Realtime까지 켠 상태로 등록하고 pg_net→Actions run→cache ready→화면 자동 갱신을 확인한다. 기존 56.397초 웹훅 관측은 처리시간 참고치이며 새 기능의3분 SLA 증거로 쓰지 않는다. B 실증 실패 시 variable=false·트리거D로 복귀한다. 사용자는 B 실증 통과 후 상시 운영을 승인했다. 통과 시 webhook 활성 상태를 유지하고 hourly sweep을6시간 간격으로 바꾸며, 실제 상태와 run URL을 보고한다. 변경은 B 범위이고 A에서 워커를 켜지 않는다.

정리 배치는 원격 dry-run만 실행해 대상 선정 증거를 기록한다. 결과는 `docs/validation/s3-2-*.md`에 PR별로 남기며 실제/fixture·로컬/원격·cold/warm·미실행 항목을 구분한다.

## 9. 사용자가 처리해야 할 단계

1. A0 계획 승인·로컬 T1 검증 완료. #22는 주소 공급자 계약을 맞춰 병행하며 A0 머지 후 데이터 기준만 동기화한다. [결과](../validation/s3-2-a0-juso-20260930.md)를 검토한다.
2. **Juso 검색 API와 검색API(좌표)를 각각 발급**해 `.env`의 `JUSO_API_KEY`, `JUSO_COORD_API_KEY`에 넣고 완료만 알린다. A 코드 배포 때 Vercel Production/사용할 Preview에 서버 전용으로 등록한다. 기존 공개 Supabase 변수2개는 유지하며 `NEXT_PUBLIC_`를 주소 키에 붙이지 않는다. Kakao 키는 등록하지 않는다.
3. Tokyo DB/R2/백업/CI에 대한 공개 API 좌표 조건 적용 범위를 확인한다. 현재 미확정이며 조건부 서울 이전안은 A0 §9를 따른다. 공용 cache 쓰기는 배치 DB URL만 허용하며 추가 서버 서명키는 없다.
4. 기존 `.env`·Actions Secrets의 `KAKAO_REST_API_KEY`는 제거 대상으로 표시한다. A0의 Juso workflow/데이터 검증 후 제거 목록을 실행한다. 이번 계획 작성에서는 키/Secrets를 수정하지 않는다.
5. 원격 SQL/데이터는 최종 `supabase db push --dry-run`과 복원/교체 manifest·점수 차이를 보고한 뒤 승인한다. B 실제 pending→ready 실증 통과 뒤 상시 webhook 운영은 기존 승인대로 진행하고 sweep은6시간 간격으로 변경한다.
6. UI/주소 재산출 결과를 검토한다. 인증 URL이 달라질 때만 기존 운영 절차대로 등록하며 이미 완료한 URL 등록을 반복 요구하지 않는다.

## 10. 승인된 결정과 A0 추가 확인

| ID | 현재 결정 |
| --- | --- |
| D1 | A/B/C 3개 기능 PR은 유지, 공급자·데이터 교체 A0 별도 승인, #22와 계약만 맞춰 병행 |
| D2 | 사용자 검색 무캐시·등록 좌표 후보 행만 저장. 공용 geocode_cache는 배치/DB URL만 쓰며 서명키·Vercel 추가 변수 없음 |
| D3 | uid 일100회 유지, 공급자 캐시 TTL 제약 없음. Juso 검색/좌표/Vworld 호출량 별도. 좌표5초10건 공통 제한 |
| D4 | 미저장 uid30일·저장 후보 있는 uid90일 미활동 정리 |
| D5 | B 실증 통과 후 상시 webhook 운영 승인. sweep 매시간→6시간. A/A0에서는 비활성 유지 |
| D6 | 인증 실패 시 재시도 후 검색. screens §2.3 정정은 #22의 별도 문서 커밋(e90f004)에 있으며 A0와 섞지 않음 |

유지: Route Handler icn1, 슬라이더 p95≤100ms/max 기록, A의 DB/RPC/어댑터 WIP 후 UI. 신규 결정: Juso 무캐시 검색·등록1회 좌표/후보 저장·배치 전용 공용 cache. A0의 실제 검색·Vworld 좌표3곳 및 해외 정책 원문 확인 결과는 A0 검증 문서를 따른다. Juso 좌표/전량 전환과 원격 쓰기는 별도 승인 범위다.

## 11. 주요 위험과 중단 조건

- **점수 불일치:** 백분위 동점/float8·원천 snapshot·서울 경계 context·좌표 경로를 각각 대조한다. UI 반올림이나 가중치 변경으로 차이를 가리지 않는다.
- **권한 누출:** cache/상태/request id를 두 uid로 조회·직접 RPC 호출·Realtime 수신 검증한다. shared cache 쓰기나 비공개 payload 노출이 있으면 UI 연결 전에 막는다.
- **삭제 경쟁:** 마지막 활동·계정 승격과 충돌할 때 보존 우선이다. 대상 manifest 이후 변경된 계정은 건너뛰고 보고한다. 운영 삭제 활성화는 로컬 보존 검증과 원격 dry-run 통과 후 별도 승인한다.
- **성능:** 800m/1km 두 호출과 새 백분위/context RPC·Worker 시간을 별도로 기록한다. cold skeleton과 warm 계산 성능을 혼동하지 않는다. 기존 SQL warm p95<1초를 악화시키는 변경은 원인을 보고하고 컴퓨트 변경을 자동 수행하지 않는다.
- **외부 서비스:** Juso/Vworld 실패와 주소 미발견을 구분하고 UID 교체만으로 일일 한도가 전체 남용을 막는다고 주장하지 않는다. CAPTCHA/추가 비밀·외부 rate-limit 서비스는 이번에 몰래 추가하지 않는다.
- **범위 확대:** 지도·공유·이메일 UI·서울 전체 건물 적재·프리셋v0.4·임대료 보정은 별도 스프린트다. S3-2는 본문의 네 사용자 완료 기준과 E2E를 충족하면 마감한다.

A0 계획 단계 확인: #21 main·#22 WIP와 공식 문서, 로컬/원격 SELECT inventory를 대조했다. 이번에는 새 주소 API 조회·DB 쓰기·migration dry-run·삭제·Secrets/Vercel 변경을 하지 않았다. #22에서 이전에 실행한 두 RPC dry-run은 A0 새 실행안의 승인 근거를 대신하지 않는다.

### A0 승인 반영 — 2026-09-30

#22는 A0와 병행한다. 공유 계약은 `lib/geo/address-provider.ts`이며 데이터/fixture 교체는 A0 머지 후 동기화한다. 기존 A0 §5의 서명 캐시 쓰기 제안과 Vercel 추가 서명키는 폐기했다. 카카오 키/cache 삭제는 재산출·8축 차이 보고·manifest 승인 후에만 실행한다. 해외 저장 제한 확인 및 조건부 서울 이전안은 [A0 계획](s3-2-a0-juso-plan.md)을 따른다.


## 2026-09-30 PR A 구현·A0 동기화

#23 머지 `7eec24c03ff7d221ad2a251c6079b82f3cd1ba32`를 #22에 merge했다. A0 T1의 Juso/Vworld 좌표를 최신 검증 기준으로 사용한다. v0.3 프리셋·분포·공공 기관 데이터는 바꾸지 않았다.

- `/new` 주소 자동완성은 Juso 실시간 검색이며 500ms debounce와 이전 응답 취소를 적용한다. 다중 결과는 사용자가 고른다. 서버에서 같은 도로명주소·건물관리번호·PNU와 전체 선택 필드를 다시 확인하고 Vworld 좌표를 1회 조회한다. `no-store`; 공유/uid별 캐시 쓰기 없음.
- uid당 KST 100회는 외부 호출 예약 합계다. 검색, 등록 재검증 검색, Vworld 좌표를 각각 1회로 센다. 실패도 차감하며 공급자별 카운터를 별도로 둔다. 현재 경로에서 등록 1회는 Juso 재검증+Vworld로 2회다. Juso 좌표 키는 아직 사용하지 않는다.
- 좌표·PNU·provider 원CRS·원좌표는 브라우저 후보 객체에 결합한다. A는 미저장 비교만 지원하고 새로고침 시 초기화된다. C의 owner 후보 행 저장에 사용할 DB 필드는 추가했다. 공유 캐시에는 전달하지 않는다.
- `score_inputs` 800/1000m + `exposure_inputs_v022` 병렬, raw 백분위 RPC와 재사용 Worker를 연결했다. exposure RPC에는 floor 인자가 없으므로 응답 scene에 사용자의 층을 넣는다. 후보 작업은 최대2개, Worker는1개다. RPC/Worker 재시도에 좌표를 다시 조회하지 않는다.
- A의 상태 투영·관찰자 연결을 구현했다. 공용 작업 하나에 uid별 불투명 ID를 부여하고 `meta.building_lookup.request_id`로 전달한다. 공개 테이블/뷰는 3필드와 owner RLS만 노출한다. Realtime publication에 투영 테이블만 추가하며 화면 구독·재조회·상시 웹훅 실증은 B다.
- `app_private.user_activity`는 실제 등록 화면 진입/주소 호출에 서버 시각을 기록한다. C에서 전경 복귀·1시간 활동 기록과 30/90일 선정·삭제 배치를 완성한다. 기존 계정은 migration 실행 시각으로 보수적으로 초기화한다.
- 기존 JSON 미리보기는 후보 점수 목록으로 교체했다. 임시 목록은 A의 연결 검증용이며 B의 매트릭스·슬라이더·근거 패널을 대신하지 않는다.

### 사용자 단계 — A 배포

1. 최종 migration 5개의 dry-run 보고를 검토하고 원격 push를 승인한다. 적용 전에는 #22를 Draft로 유지한다.
2. Vercel에 **서버 전용** `JUSO_API_KEY`, 임시 좌표 공급자용 `VWORLD_API_KEY`를 등록한다. 기존 공개2개 외의 DB 관리자키·서명키는 필요하지 않다. `JUSO_COORD_API_KEY` 전환·전량 재산출은 별도 승인 단계다. A0의 Vercel 추가 변수 없음은 A0 실행 범위였으며 이 두 키는 A의 Route Handler 배포 요구사항이다.
3. 원격 적용·키 등록 후 Preview에서 주소 등록을 확인하고 사용자가 머지한다. 이 세션은 Vercel 설정·공유 캐시·Kakao 키 삭제·상시 웹훅 활성화를 실행하지 않는다.

자세한 결과와 남은 단계는 [PR A 검증](../validation/s3-2-a-registration-20260930.md)을 따른다.
