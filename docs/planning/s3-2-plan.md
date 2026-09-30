# S3-2 등록·매트릭스 구현 계획

base: main

- 작성일: 2026-09-29 · 승인 반영: 2026-09-30. **S3-2 계획 승인, PR A 착수. 카카오 응답 저장 정책 충돌은 아래 추가 확인 항목을 따른다.**
- 계획 브랜치: `s3/registration-plan`, PR A 구현 브랜치: `s3/registration-data`. 기준 커밋: `e93740798da8e61560e707bb1315a4dd0194f7b1`(#21 머지). 각 구현 PR도 앞 PR 머지 후 최신 `main`에서 `s3/…`로 분기한다.
- A는 문서→DB/RPC/어댑터 검증·WIP 커밋→UI 순서로 진행한다. 원격 migration은 dry-run 보고 후 별도 승인하며, scoring v0.3 수식·프리셋은 유지한다.
- 기준: [AGENTS.md](../../AGENTS.md), [screens.md §0·§3·§4·§8](screens.md), [scoring-spec v0.3](scoring-spec.md), [S3 운영](../operations/s3-foundation.md), [S3-1 마감 검증](../validation/s3-1-closeout-20260929.md), [S2-4 v0.3](../validation/s2-4-v03-20260926.md), [S3-1의 확정된 S3-2 결정](s3-1-plan.md#9-예상-리스크와-후속-경계).

## 1. 목표와 범위

screens.md §8의 S3-2: **[R] 폼, RPC 3종 호출, 클라이언트 채점, ComparisonMatrix(슬라이더 포함), 결측·pending·배지, 근거 패널, 모바일 카드**를 구현한다. 사용자 추가 범위는 주소 자동완성 Route Handler·요청자별 Realtime·익명 계정 정리 정책·등록→채점→슬라이더→저장 Playwright E2E 1개다.

최종 완료 기준:

1. 역삼로460 3층 / 도곡로409 2층 / 역삼로546 3층을 주소→PNU→도형 경로로 등록하고, 800m·학교1km·임대료/면적 미입력에서 S2-4 v0.3의 8축·총점·신뢰도와 일치한다.
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
| 주소 캐시 | `public.geocode_cache(address,provider)`는 배치 전용·공용·단일 지점 | 사용자 검색 캐시를 uid별로 격리하는 제안은 §4.1·§10 D2 참조 |
| 주소 큐 | 비공개 작업1건에 `requester_uid` 하나, 공용 주소 중복 방지 | 같은 주소를 요청한 여러 uid를 각각 상태 관찰자로 연결 |
| Realtime | 비공개 캐시 직접 구독 금지, 상태3필드만 노출하기로 확정 | RLS 상태 투영 테이블과 조회 뷰. SQL VIEW 자체를 publication에 넣지 않음 |
| 저장 | candidates는 좌표·층·임대료·면적, comparisons는 후보ID배열·weights·preset_id | 주소·별칭·조회상태·버전·순서와 수정 시각을 추가. 기존 owner RLS 유지 |
| 원격 운영 | Auth anonymous 활성, authenticated timeout15초, 주소 트리거D·`INGEST_REMOTE_ENABLED=false` | 실증 창만 일시 활성화. 서비스 상시 처리 여부는 D5 결정 |
| Vercel | 공개 Supabase 변수2개만 존재 | S3-2에 서버 전용 `KAKAO_REST_API_KEY`만 추가 |

이미 승인된 두 불일치는 재결정하지 않는다: 분포 전체 대신 raw→백분위 RPC, 비공개 주소 캐시 대신 요청자별 상태 구독. screens.md 원문은 이번 계획에서 고치지 않는다. scoring-spec §1.1의 옛 `exposure_inputs_v021` 표기보다 현행 §5.5·코드·S3 인계의 **v022**를 따른다.

## 3. PR 분할 — 3개 권장

하나의 S3-2를 순서 있는 세 하위 태스크로 나눈다. 각 PR 설명에 해당 하위 완료 기준과 최종 S3-2 기준 중 충족한 항목을 구분한다. 2개로 합치는 대안은 §10 D1에 있다.

| PR / 브랜치 | 변경 범위·예상 파일 | 마이그레이션 | 해당 PR 완료 기준 |
| --- | --- | --- | --- |
| **A 데이터·등록 기반** / `s3/registration-data` | `app/api/address-search/route.ts`, `app/new/page.tsx`, `components/candidate/{AddressSearch,CandidateForm}.tsx`, `lib/geo/`, `lib/supabase/`, `lib/scoring/{types,percentile,score,axes}.ts`의 호환 어댑터, `lib/compare/load-candidate.ts`, 기존 Worker 연결 | 위치/context·raw 백분위 RPC, uid별 검색 캐시/일일 제한, 후보 저장 필드, 최소 상태 투영·관찰자 연결 | 주소 선택·검증→3종 채점 RPC→Worker→ScoreResult. 고정3곳 8축/총점/신뢰도 일치. 두 uid 권한·검색 제한·배치 캐시 보존. 기존 전체 분포 경로와 새 경로 동등성. 완성 매트릭스는 B |
| **B 비교·근거·실시간** / `s3/comparison-matrix` | `app/compare/page.tsx`, `components/compare/`의 매트릭스·슬라이더·배지·근거·모바일 카드, `lib/compare/{store,status,subscriptions}.ts` | A 상태 투영의 Realtime publication/권한 등 필요한 추가 변경만 | 데스크톱/모바일 동일 점수·근거·결측, 슬라이더 <100ms, 두 uid Realtime 격리, pending→ready 무새로고침, 3분 지연·재접속·순서 역전 검증 |
| **C 저장·익명 정리·종합 검증** / `s3/comparison-save-retention` | `lib/compare/persistence.ts`, 저장/프리셋 UI, `ingest/cleanup_anonymous.py`, `.github/workflows/cleanup-anonymous.yml`, `playwright.config.ts`, `tests/e2e/compare.spec.ts`, 검증·운영 문서 | 비교 저장 확장/명명 가중치 프리셋, activity·정리 함수/인덱스 | 익명 저장·재열기·owner RLS, E2E1개 통과, 정리 dry-run의 대상/제외 검증·로컬 실제 삭제 및 승격 보존, 최종 실제3곳/성능/실시간 증거 기록 |

**A 내부 체크포인트:** DB/RPC/채점 어댑터의 로컬 단위·DB 검증 후 WIP 커밋을 먼저 남긴다. 그 뒤 Route Handler·등록 폼·브라우저 Worker UI를 연결한다. 아직 확정되지 않은 카카오 저장 경로는 독립 DB/RPC 단계와 분리해 보류한다.

마이그레이션은 각 PR에서 `supabase migration new`로 생성하고 새 파일에만 작성한다. 계획 단계에서는 생성하지 않는다. 문서와 코드는 별도 커밋한다. 새 라이브러리는 지정 스택인 Zustand와 Playwright만 필요하며 버전 고정·lockfile·추가 이유를 해당 PR에 기록한다. 지도 라이브러리는 이번에 추가하지 않는다.

## 4. 등록·주소·RPC 계약

### 4.1 주소 자동완성과 캐시

Route Handler는 `runtime = nodejs`, `preferredRegion = icn1`으로 고정한다. 한국 사용자와 Kakao 호출을 한국 리전에서 처리하려는 사용자 결정이다. 원격 Supabase는 현재 도쿄(`ap-northeast-1`)이므로 DB와 동일 리전이라는 주장은 하지 않는다. [Vercel 리전 설정](https://vercel.com/docs/functions/configuring-functions/region)을 따르고 배포 시 함수 리전·왕복 시간을 확인한다.

`POST /api/address-search`의 JSON body는 제한된 길이의 검색어와 검색/선택 확인 모드다. 브라우저의 익명 사용자 JWT를 Authorization에 전달하고 Route Handler에서 Supabase Auth로 검증한다. 요청 body의 uid를 신뢰하지 않는다. Supabase에는 공개 키+그 사용자 JWT만 사용한다. Vercel에 service-role·DB 비밀번호·Management token을 추가하지 않는다.

제안 흐름:

1. 입력2자 이상·300ms debounce, 이전 요청 AbortController 취소, 결과는 최대10개·1페이지. 역순 도착 응답은 검색 세대 번호로 버린다. 검색어/주소는 URL·로그에 남기지 않는다.
2. DB가 인증된 uid와 KST 날짜로 검색 한도를 원자적으로 차감한다. **100회/uid/일** 제안, 캐시 hit를 포함한 Route 요청 기준이다. 같은 요청 재전달은 request id로 중복 차감하지 않는다. 기존 **새 건물 주소 작업 일10건**과 별개다. 서버리스 메모리 카운터에 의존하지 않는다.
3. 주소 검색0건일 때만 Kakao 키워드(장소) 검색으로 폴백한다. 오류를0건으로 취급하지 않는다. 결과에 `kakao_address`/`kakao_keyword` 출처를 표시하고 주소·키워드 실제 API 호출 수를 별도로 기록한다. 장소 선택 후 PNU가 필요하면 그 장소의 상세 주소를 주소 API로 확인하며 추가 호출도 주소 쿼터에 포함한다. `geocode_cache` 조회·응답 저장 경로는 다음 정책 확인의 결론 전까지 보류한다. Kakao 키는 서버 환경변수에서만 읽는다. 배치·건축물대장 외부 호출은 계속 `/ingest`다.
4. **TTL은 양수로 확정하지 않았다.** A 첫 단계의 [카카오 저장 정책 확인](../validation/s3-2-a-kakao-policy-20260930.md)에서 응답 캐시/저장이 승인된 D2와 충돌함을 확인했다. 응답을 저장하지 않는 변경안에 대한 사용자 결정을 기다린다. 401/403/429·타임아웃은 정상 빈 결과로 캐시하지 않는다. 주소 수정/지역 중심점을 상세 주소로 자동 확정하지 않는다. 반환된 도로명·지번 중 사용자가 선택한 상세 주소만 등록한다.
5. 서울 여부는 DB 경계로 최종 확인한다. 지역/도로 중심 결과·다중 결과를 첫 항목으로 자동 선택하지 않는다. 인증 실패·검색 제한·Kakao 실패는 각각 재시도/한도 안내로 표시한다.

**캐시 권장안(D2):** 기존 배치 `public.geocode_cache`는 PK·영속 캐시 정책·권한을 그대로 둔다. 새 `app_private.geocode_cache`에 `(user_id, normalized_query, mode, provider)` 키·정규화 응답·expires_at을 두고, auth.uid()로 범위를 제한한 좁은 RPC로만 읽고 쓴다. 다중 자동완성 응답은 기존 단일 Point 스키마에 억지로 넣지 않는다. 기존 캐시의 정확한 주소 결과가 필요한 경우에도 정확 키 조회 helper만 허용하며 전체 목록을 노출하지 않는다.

사용자 JWT로 호출 가능한 캐시 쓰기는 서버 호출임을 증명하는 관리자 권한이 아니다. 사용자가 직접 같은 RPC를 호출해도 **자기 캐시만** 바뀌고 공용 배치 캐시·다른 uid·원천 건물에는 영향을 못 주게 한다. 이 캐시 값을 공공 원천 검증 완료로 취급하지 않는다. DB는 최종 좌표·PNU/도형 포함 관계를 독립 검증한다. 공유 캐시의 쓰기 권한을 authenticated에 열거나 별도 Vercel 비밀을 추가하는 우회는 하지 않는다.

Kakao의 주소 검색 엔드포인트·좌표 x/y·법정동/산/본번/부번 필드는 [공식 문서](https://developers.kakao.com/docs/ko/local/dev-guide)와 기존 `ingest/building_on_demand.py`의 PNU 변환을 대조한다. 새 주소의 실제 API 응답·쿼터·캐시 이용 조건은 A 구현 중 확인하여 data-sources.md에 기록한다. 일100건은 승인된 제품 한도이며 계정 쿼터를 확인한 수치가 아니다. 양수 TTL은 허용 여부가 확인되지 않아 적용하지 않는다. 위 uid별 캐시 설계는 D2 승인 이력을 보존한 것이며 카카오 응답 저장을 구현하라는 현재 실행 지시가 아니다.

### 4.2 폼과 위치 확인

- `/new` 페이지를 기본으로 사용하고 `/compare`의 후보 추가에서 연결한다. 주소, 정수 층 **−5…−1 또는 1…30** 필수, 전용면적>0·보증금/월세/관리비≥0·별칭≤20자 선택. 빈 선택 입력은 NULL이며 0과 구분한다.
- 500㎡ 이상 안내·임대료 축 v0.3 미확정 안내를 폼에서 보여준다. 주소+층 중복은 경고 후 허용하고 후보5개 상한을 UI와 저장 함수 양쪽에서 검증한다.
- 등록용 `resolve_candidate_location` RPC(제안)는 선택된 Kakao 좌표·PNU를 받아 동일 PNU 도형과 ST_Covers를 확인하고, 후보 좌표·건물 식별자·매칭 사유·서울 내부 여부·서울 외곽 경계 거리·법정동명 context를 반환한다. 외부 API를 호출하지 않는다.
- **S2-4는 Kakao 좌표를 사용하고 그 좌표의 PNU 도형 포함을 확인했다. 도형 중심은 기록만 했으며 채점 좌표로 교체하지 않았다.** 같은 포함 좌표를 그대로 사용한다. 다동/겹침·PNU 불일치에서는 임의 중심/첫 도형을 고르지 않고 확인 필요로 남긴다.
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

- 요청에 preset id/reference_version0.1.2·radius800·schema1.3·원천 메타데이터/요청 지표/원시값을 담는다. 서버는 유한수·허용 키·최대7개를 검증하고 동일 문장 스냅샷의 기준분포만 읽는다.
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

기준은 [S2-4 Markdown](../validation/s2-4-v03-20260926.md)과 [전체 결과 JSON](../validation/s2-4-v03-20260926.json)이다. 입력1.3·reference0.1.2 snapshot `20260923T111436Z`·Worker0.2.2·academy_v0 0.3을 고정한다. 화면 예시 숫자를 기대값으로 사용하지 않는다.

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

실제 원격 데이터/주소 공급자 응답이 바뀌면 fixture 결과와 최신 실측을 나란히 기록하고 불일치 원인을 보고한다. 좌표를 몰래 교체하거나 프리셋을 조정해서 통과시키지 않는다. 기준분포 전수 재생성도 이번 범위가 아니다.

### 8.2 PR별 집중 검증

- **A:** raw 백분위의 동점·미관측 값·NULL·빈 모집단·최솟값/최댓값·거리 역방향·버전/소스 불일치, HTTP float8 정밀도. 기존 전체분포 score()와 새 adapter의 동일 입력 결과 대조. 주소 다중/보정/서울 밖/PNU 불일치·사용자별 cache 오염 격리·일 제한 동시 요청·10건 큐 정책 보존. Worker/Node 동등성 재사용.
- **B:** 두 uid·두 브라우저의 실제 Realtime 테스트(로컬 DB/Realtime). 같은 주소 공동 대기·남의 request_id·구독 직전 ready·재접속·이벤트 중복·삭제/층 변경 후 늦은 결과·3분 지연·Worker 실패를 검증한다. mock 이벤트만으로 Realtime 완료 처리하지 않는다.
- **B 성능:** 최대5후보·완전한 근거를 넣은 production build에서 슬라이더 연속100회 측정. 함수 실행 시간과 입력→React 반영→다음 paint 시간을 분리해 p50/p95/max·환경·메모리를 기록한다. 데스크톱과390px 모바일 viewport 각각100회 표본의 p95≤100ms를 통과 기준으로 삼고 max는 기록한다. RPC/Worker 호출 증가0·normalized/신뢰도 불변을 함께 확인한다. 실제 기기 성능과 viewport 에뮬레이션을 혼동하지 않는다.
- **C 정리:** 미저장30일 경계/31일·저장90일 경계/91일 미활동/최근 조회·저장/오래됐으나 승격/승격 진행/동시 활동/정책 도입 전 사용자를 고정 시각으로 구성한다. dry-run 대상·제외 집합과 행수를 검증하고 로컬 실제 삭제 후 보존 uid·후보·비교·공용 큐/캐시를 대조한다. 실패 뒤 중복 삭제 없이 재개되는지도 확인한다.
- **공통:** `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm build`. SQL 변경 PR은 `pnpm test:db`, C는 `pnpm test:e2e` 추가. 기존 마이그레이션/ScoreResult v0.3 검증 회귀를 유지한다.

### 8.3 Playwright E2E 1개와 실제 운영 검증

Playwright 단일 핵심 시나리오: 새 browser context의 익명 uid → [R]에서 대치동3곳 주소 선택/층 입력 → Worker 포함 채점 → 매트릭스의 기준값·신뢰도 확인 → demand 슬라이더 변경과 p95≤100ms/무RPC 확인 → 익명 비교 저장 → 새로고침으로 같은 uid·후보3개·가중치·순서 복원. 키보드로 선택할 수 있는 role/label을 사용한다.

CI는 로컬 Supabase와 고정 원천 snapshot을 사용하며 Kakao 경계만 기록된 공개 응답 fixture로 대체한다. 채점 RPC·순수 함수·Worker를 예상 점수로 mock하지 않는다. 전체 원천을 매 CI에 복원하기 어렵다면 A에서 필요한 최소 공간 원천과 기준분포 fixture를 추출·검산해 로컬 테스트 DB에 적재한다. 이는 테스트 데이터이며 운영 적재 범위 축소가 아니다.

별도의 승인된 원격 검증 창에서 실제 주소 검색·3곳 RPC/Worker 결과·브라우저 타이밍을 기록한다. pending1건은 상태 projection+Realtime까지 켠 상태로 등록하고 pg_net→Actions run→cache ready→화면 자동 갱신을 확인한다. 기존 56.397초 웹훅 관측은 처리시간 참고치이며 새 기능의3분 SLA 증거로 쓰지 않는다. B 실증 실패 시 variable=false·트리거D로 복귀한다. 사용자는 B 실증 통과 후 상시 운영을 승인했다. 통과 시 webhook 활성 상태를 유지하고 hourly sweep을6시간 간격으로 바꾸며, 실제 상태와 run URL을 보고한다. 변경은 B 범위이고 A에서 워커를 켜지 않는다.

정리 배치는 원격 dry-run만 실행해 대상 선정 증거를 기록한다. 결과는 `docs/validation/s3-2-*.md`에 PR별로 남기며 실제/fixture·로컬/원격·cold/warm·미실행 항목을 구분한다.

## 9. 사용자가 처리해야 할 단계

1. §10 D1~D6은2026-09-30 승인됐다. 추가 발견한 카카오 저장 정책 충돌의 변경안을 결정한다. 독립 DB/RPC 구현은 진행한다.
2. **Vercel gilmok의 Production·사용할 Preview에 `KAKAO_REST_API_KEY`를 서버 전용으로 등록한다.** `NEXT_PUBLIC_` 접두사 금지, 값은 채팅/문서에 보내지 않는다. 기존 공개 Supabase 변수2개를 유지하고 다른 서버 비밀은 추가하지 않는다. 키 등록 후 A 코드 배포에 반영한다.
3. Kakao Local API 사용 가능 상태·계정 쿼터/과금 설정을 확인한다. 확인된 조건을 구현 시 문서에 기록하며 새 결제/쿼터 상향은 자동 실행하지 않는다.
4. 각 DB 변경의 로컬 검증·원격 migration 대조·`db push --dry-run` 보고를 검토하고 원격 적용을 승인한다. 이번 계획 승인만으로 원격 migration이나 기존 데이터 삭제를 실행하지 않는다.
5. 실제 pending 실증 창과 승인된 공개 주소1건을 확정한다. 대기 중 작업이 다른 사용자 것과 섞였으면 그 현황을 먼저 보고받는다. B 실증 통과 후 상시 webhook과6시간 sweep 운영은 승인됐다. A에서 조기 활성화하지 않는다.
6. 익명 정리의 보존기간·저장 안내·dry-run 결과를 검토한다. **실제 원격 삭제·일일 스케줄 활성화는 추가 승인 대상**이다. 코드와 dry-run은 그 전에 준비한다.
7. 새 Preview 주소가 기존 허용 패턴 밖일 때만 Auth Redirect URL을 추가한다. S3-1에서 완료한 URL 등록·Auth anonymous 활성화를 다시 요구하지 않는다.

## 10. 승인된 결정과 추가 확인

2026-09-30 사용자 결정:

| ID | 확정 내용 |
| --- | --- |
| D1 | 3개 PR A/B/C |
| D2 | uid별 `app_private` 캐시. 단, A 첫 정책 확인에서 카카오 응답 저장과 충돌해 해당 경로 보류 |
| D3 | 일100회. TTL은 카카오 약관 확인 후 확정; 허용되는 양수 TTL을 아직 확인하지 못함 |
| D4 | 미저장 uid30일·저장 후보 있는 uid90일 미활동 정리 |
| D5 | B 실증 통과 후 상시 webhook 운영 승인. sweep은 매시간→6시간. A에서는 비활성 유지 |
| D6 | 인증 실패 시 재시도 후 검색. screens §2.3 문구는 별도 문서 커밋으로 정정 |

추가 승인: Route Handler icn1, 주소0건→장소 검색 폴백·출처/쿼터 분리, 슬라이더 p95≤100ms/max 기록, 카카오 정책 확인을 A 첫 항목으로 실행, DB/RPC/어댑터 WIP 커밋 후 UI 진행.

**새로 확인한 충돌:** [카카오 정책 조사](../validation/s3-2-a-kakao-policy-20260930.md)에서 응답 저장·캐시를 허용하는 TTL을 찾지 못했다. 실시간 검색 후 공공 원천과 비교하고 카카오 응답을 폐기하는 경로가 공식 안내에 부합하는 대안이다. D2의 응답 캐시 및 후보에 카카오 응답 좌표/주소를 영속 저장하는 부분은 사용자 변경 결정 전까지 구현하지 않는다. 기존 배치 캐시/R2 자료를 임의 삭제하지 않는다.

## 11. 주요 위험과 중단 조건

- **점수 불일치:** 백분위 동점/float8·원천 snapshot·서울 경계 context·좌표 경로를 각각 대조한다. UI 반올림이나 가중치 변경으로 차이를 가리지 않는다.
- **권한 누출:** cache/상태/request id를 두 uid로 조회·직접 RPC 호출·Realtime 수신 검증한다. shared cache 쓰기나 비공개 payload 노출이 있으면 UI 연결 전에 막는다.
- **삭제 경쟁:** 마지막 활동·계정 승격과 충돌할 때 보존 우선이다. 대상 manifest 이후 변경된 계정은 건너뛰고 보고한다. 운영 삭제 활성화는 로컬 보존 검증과 원격 dry-run 통과 후 별도 승인한다.
- **성능:** 800m/1km 두 호출과 새 백분위/context RPC·Worker 시간을 별도로 기록한다. cold skeleton과 warm 계산 성능을 혼동하지 않는다. 기존 SQL warm p95<1초를 악화시키는 변경은 원인을 보고하고 컴퓨트 변경을 자동 수행하지 않는다.
- **외부 서비스:** Kakao 실패와 주소 미발견을 구분하고 UID 교체만으로 일일 한도가 전체 남용을 막는다고 주장하지 않는다. CAPTCHA/추가 비밀·외부 rate-limit 서비스는 이번에 몰래 추가하지 않는다.
- **범위 확대:** 지도·공유·이메일 UI·서울 전체 건물 적재·프리셋v0.4·임대료 보정은 별도 스프린트다. S3-2는 본문의 네 사용자 완료 기준과 E2E를 충족하면 마감한다.

승인 전 계획 단계 확인: 저장소 문서/코드와 #21 머지 상태를 읽었고 공식 API 문서를 참조했다. 새 Kakao 실호출, 원격 DB 쓰기, 새 Realtime 구독, 정리 dry-run/삭제, 구현 테스트는 아직 실행하지 않았다.
