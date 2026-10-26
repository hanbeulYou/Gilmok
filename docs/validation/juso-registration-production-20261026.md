# Juso 신규 등록 Production 전환 — 2026-10-26

③ 승인 범위로 #39 머지·서버 키 등록 확인 → migration 1개 push → #40 Ready → 한별 머지 → Production 배포 → 신규 등록·DB 보존 검산을 수행했다. **신규 등록·채점·저장은 성공했다. 전체 Production E2E는 초기 `touch_user_activity` HTTP401 때문에 실패로 기록한다.** 이후 activity는204였다. 401을 허용 응답으로 바꾸거나 제품 코드를 고치지 않았다. 원인 미확정이며 별도 진단 대상이다. ④ #41, 키 삭제, 기존 후보 좌표 교체는 실행하지 않았다.

## 실행과 migration

- 한별이 Vercel Production·Preview의 서버 전용 `JUSO_API_KEY`·`JUSO_COORD_API_KEY` 등록을 확인했다. 값은 출력하지 않았다.
- #39 merge `61676db879dbecd9dae62744dab90c6f77694ca6`, 2026-10-25 13:09:42 UTC 확인. #40 브랜치를 최신 main에 동기화했다.
- 직전 `supabase db push --linked --dry-run` exit0, **`20261021000000_juso_registration_coordinates.sql` 하나만 대기**. 소요 1.319초. SHA256 `b904c835d1695ad439a2737a552071face389a40aa96d734ae170de92cc576df`. 내용 변경·`--include-all` 없음.
- 일반 `db push --linked --yes` exit0, 0.548초. 사후 검산 종료 `2026-10-25T13:12:43.935617+00:00`. #40 본문을 갱신하고 즉시 Ready 전환·한별 머지 요청.
- **기존 객체 변경:** `app_private.address_daily_usage.juso_coordinate` 열 추가, `claim_address_call(text)` 교체, `project_juso_coordinate` 신설. 기존 데이터 삭제·좌표 변경 없음.
- migration 이력47→48, 기존47건 전체행 불변. 기존 후보11행 전체 값·쿼터13행 기존 필드 불변. 새 카운터 초기값0. authenticated EXECUTE/anon 불허 확인. 합계100 제한 및 legacy Vworld 카운터 누적 코드 유지.
- #40 merge `8caadcb32ffb57c06aa577bcb1ecb3d882572bdc`, 2026-10-26 14:45:29 UTC. Production READY 14:46:17 UTC, `dpl_6mJsx73iuKf3SppE28fyRyqvvnmc`. `vercel inspect`로 `gilmok-weld.vercel.app`이 `gilmok-7i58f66aq-vineyard.vercel.app`을 가리킴을 확인했다.
- push와 배포 사이에는 실제로 약25시간33분의 간격이 있었다. Ready/머지 요청은 push 직후 했으나 사용자 머지를 대신 실행하지 않았다. 그 구간은 구 Production의 Vworld 경로가 동작할 수 있었으며, 기간 전체의 등록 요청 부재까지 검증한 것은 아니다.

## 실제 신규 등록

가짜 응답·공급자 fixture 없이 Production `/new`에서 **서울특별시 강남구 역삼로460, 3층**, 임대료 미입력으로 검색→선택→좌표→PNU 도형 검증→채점→안내 확인 후 익명 저장했다.

| 항목 | 실측 |
| --- | --- |
| 검색 / 좌표 Route Handler | 모두 HTTP200 / 실제 `icn1` |
| 좌표 공급자 | `juso` |
| 원본 CRS | EPSG:5179, X=960896.1846965668 / Y=1944903.6257312004 |
| 저장 위도 / 경도 | 37.5025724246771 / 127.057585444512 |
| 선택·도형·저장 PNU | `1168010600109120013` (대치동912-13), 모두 일치 |
| 도형 포함 판정 | `matched`, covering building1 |
| 총점 / 신뢰도 | 83.01156632018979 / 90 |
| 기준분포 | `20261016T040000Z` |
| 저장 결과 | 후보1개와 비교 저장 성공, DB `address_provenance.location.coordinate_provider='juso'` |
| 기존 후보 | 사전11행의 geom·PNU·address_provenance 모두 불변 |
| 기존 쿼터 | 사전13행 모든 기존 필드 불변 |
| 최종 등록 uid의 실제 쿼터 | total3 / juso_search2 / juso_coordinate1 / vworld_coordinate0 |

검색2회는 사용자 검색1회와 선택 위조 방지를 위한 등록 시 주소 재조회1회다. 같은 uid/day의 세 공급자 카운터와 합계를 실제 DB에서 확인했다. 100회 경계는 유지된 SQL 조건을 확인했으며, 이번 원격 실증에서 호출100회나 카운터 강제변경을 수행하지 않았다.

이번 총점은 G의 고정 검증 좌표 a(83.01075192604473)보다 0.00081439414505점 높다. 신규 등록의 Juso 출입구 좌표를 사용했기 때문에 고정 좌표와 다르며 transit 점수가38.336803260049486→38.3419610896348이다. 나머지7축은 고정 a와 같고 화면 둘째 자리 표시는83.01로 같다. 모델·가중치·기준분포를 조정하지 않았다.

## 검증 한계·실패 기록

- `pnpm lint`, `pnpm typecheck`, `pnpm test` 최종 exit0. 실제 공급자 검색·좌표, score_inputs·exposure·reference·save_comparison_v2 모두200.
- 첫 스크립트는 SVG 숫자에 innerText를 사용해 실패했고 textContent로 고쳤다. 다음은 저장 버튼 이름을 잘못 지정해 실패했고 실제 문구 `안내 확인하고 저장`으로 고쳤다. 두 시도에서는 저장에 도달하지 못했다.
- 과거 실패 스크립트를 testDir 하위에 보존하면서 마지막 실행에 함께 수집된 사실을 확인했다. 마지막 runner는 **3 failed / exit1**이며, 과거 스크립트2개와 현재 스크립트1개다. 구성에 `testIgnore: ['**/attempt-*/**']`를 추가했으나 이후 원격 등록을 다시 실행하지 않았다. 중복 시험도 실제 API를 호출했고 합성 결과로 대체하지 않았다.
- 현재 스크립트는 등록·채점·저장까지 완료한 뒤 초기 activity401 및 후속204를 관측해 최종 HTTP assertion에서 실패했다. 테스트에서401을 무시하지 않았다. 응답 본문/요청 인증 헤더는 수집하지 않아 정확한 원인은 아직 알 수 없다. 인증 초기화 타이밍 문제는 가설일 뿐이다.
- 저장된 최종 후보의 출처·좌표·PNU·쿼터 및 기존 행 보존은 별도 **READ ONLY DB 대조**로 통과했다. 전체 E2E 통과로 표현하지 않는다. 실패 후 추가 등록·데이터 교체·강제 쿼터 수정·계정 삭제를 하지 않았다.
- 테스트용 익명 계정과 성공한 비교는 실증 이력으로 남아 있다. 기존 사용자 데이터의 삭제·대리 열기는 없었다.

## VWORLD_API_KEY 사용처와 삭제 조건

배포된 `app/`·`lib/`에서 키를 읽는 코드는 **0곳**이다. 그러나 저장소 전체는0이 아니다.

| 파일 | 실제 읽기 용도 |
| --- | --- |
| ingest/building_footprints.py:170 | 누락 건물 WFS 보조 도형 |
| ingest/legal_boundaries.py:136 | 법정동 WFS 경계 |
| ingest/verify_juso_transition.py:29,47 | 기존 Vworld 전환 검증 경로 |
| ingest/address_provider_diagnostic.py:22 | 기존 공급자 진단 경로 |

3개 Actions workflow의 env 전달 및 `.env.example` 선언도 남아 있다. `ingest/juso.py`·`building_on_demand.py`의 해당 문자열은 오류 문구/매핑이며 추가 키 읽기 지점으로 세지 않았다. **전체 읽기0곳 조건이 충족되지 않아 전역 삭제 대상 목록을 확정하지 않았다.** 특히 `.env`/Actions 키를 지우면 WFS 경로에 영향이 있다. Vercel 신규 등록은 해당 키를 쓰지 않지만 삭제는 한별의 작업이며 이번에 실행하지 않았다.

[실측 JSON](juso-registration-production-20261026.json). 전체 E2E의 activity401 진단은 미완료로 보고하고 정지한다. ④는 별도 사용자 승인 전 실행하지 않는다.
