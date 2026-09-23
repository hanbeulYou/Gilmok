# S2-1·S2-2 구현 계획 — 2026-09-23 승인

2026-09-22. 기준: 사용자 제공 scoring-spec.md v0.1, data-sources.md §3 v1.2, S1 PR 8(#11) 머지. 이번에는 문서 대조·법령 조회·읽기 전용 표본 측정만 했다. 채점 코드·migration·실제 기준 분포 적재는 승인 후 구현한다. 2026-09-23 사용자 승인으로 scoring-spec.md v0.1.1에 보완을 반영한다. S2-1 PR 머지 후 S2-2를 main에서 시작한다.

## 1. 불일치·보완 목록 — 구현 전에 명세에 반영할 제안

| 항목 | 명세와 실제 계약의 차이 | 제안 |
|---|---|---|
| R1 용도 판정 | 역삼로 460의 floor_use는 객체가 아닌 배열. use_name=`학원`, other_use=`제2종근린생활시설(학원)`. use_name만 검사하면 +25가 빠짐 | 요청 층의 각 행에서 use_name·other_use를 함께 검사. all_floors에는 other_use/use_code가 없으므로 그 배열만으로 법정 용도 등급을 확정하지 않음 |
| R5 층 수 | all_floors는 층당 한 행이 아니라 용도별 행. floor_no는 NULL 가능하며 floor_kind=30은 옥탑 | (floor_kind,floor_no)로 중복 층을 제거하고 요청 지상/지하 층을 제외. 번호 미상/옥탑은 일반 층으로 세지 않고 근거에 기록 |
| 대장 미연결 표현 | §7의 register NULL·location_basis 도형은 실제 키/값이 아님 | building.register_pk, building.location_basis='footprint'로 명시 |
| rent.survey_* | wildcard는 JSON 키가 아님. 공간 미연결 때 survey_by_building_class는 NULL이 아닌 {} | scalar NULL과 map {} 구분. trade_median_per_m2는 원/㎡이므로 만원/㎡ 표시에만 ÷10,000 |
| 가시성 좌표 | score_inputs의 역 정보는 거리만, schools는 학교급별 개수만 반환. 역·학교 좌표 없음 | S2-3에서 별도 공간 조회 입력을 설계. 이번에는 visibility 외부 결과 입력/미계산 상태만 정의 |
| 서울 경계 1km 경고 | 관련 거리/boolean이 v1.2에 없음 | pure 함수의 별도 context에 검증된 seoul_boundary_distance_m 주입. 실제 입력 검증 스크립트에서 admin_dongs 외곽과 PostGIS 거리로 계산. context 없으면 미확인 표시, 임의 추정 금지. 공개 RPC v1.2 변경 없음 |
| R6 면적·거리 예외 | 건물 전체 연면적, 실별 수평거리, 실제 영업종류/예외 여부가 v1.2에 없음 | 키워드는 위험 신호로만 사용. 예외 불명 시 academy_eligible=false를 확정하지 않고 NULL·확인 필요. 아래 법령 절의 제안 승인이 필요 |
| 기준 분포 주입 | score(...) 선언에 reference 인자가 없지만 백분위는 외부 분포가 필요 | reference와 context를 명시 인자로 받는 순수 함수. computed_at은 입력/주입 시각을 사용하고 Date.now·DB·네트워크 호출 금지 |
| 6조합·학교 반경 | S1 6조합은 500/1000m, 새 reference는 800/1000m. demand 학교는 항상 1km | S2-2 기술 검증은 3좌표×800/1000m로 명시. 기존 500m 응답은 호환/건물 fixture에만 사용. 500m 백분위를 800m 분포로 대체하지 않음. §8 500m 민감도 비교는 S2-4에서 추가 분포 필요 |

R1 보완 시 실제 fixture로 3층 100·4층 90이 성립한다. 키 이름이 존재하는 것과 해당 값만으로 법적 등록 여부를 판단할 수 있는 것은 구별한다. 예컨대 exclusive_area_m2는 사용자 전용면적이며 R6의 건물 연면적이 아니다. 층 용도 면적을 합쳐 법정 연면적으로 대체하지 않는다.

### 입력 키 전수 대조

아래는 명세의 축 계산·근거·신뢰도에서 사용하는 키를 경로로 풀어 쓴 목록이다. data-sources §3 및 PR 7 실제 JSON과 대조했다. 후보 입력·파생 결과·preset 키는 RPC 필드가 아니며 별도 타입으로 둔다.

| 묶음 | 실제 경로(묶음 접두사 생략) | 결과 |
|---|---|---|
| demand | pop_5_9, pop_10_14, pop_15_18, schools.elem, schools.mid, schools.high, estimated | 전부 일치. 인구 number/null, 학교 integer/null |
| flow | weekday.golden_avg_pop, weekend.golden_avg_pop, low_coverage, estimated | 전부 일치. low_coverage는 boolean, NULL 아님 |
| transit | nearest_subway_m, subway_boardings_golden, bus_stops, subway_units_missing_golden | 전부 일치. 역 좌표는 없음 |
| compete | academies_total, academies_by_field["입시.검정 및 보습"] | map 자체 NULL과 관측 map에 해당 분야 키가 없는 0건을 구별 |
| market | stores_total, stores_by_lcls["I1"] | 일치. map 자체 NULL과 I1 키 없음 구별; total=0일 때 비율 분모 처리 명시 |
| building | floor_use[].use_name, all_floors[].use_name, all_floors[].floor_no, elevators.passenger | 키 존재. floor_use는 array/null, all_floors는 비NULL array. 배열/층 구분 보완 필요 |
| building 보완 | floor_use[].other_use/use_code, all_floors[].floor_kind, register_pk, location_basis | 모두 v1.2에 이미 존재. RPC 추가 필드 아님 |
| rent | trade_median_per_m2, survey_rent_per_m2, survey_vacancy, survey_building_class, survey_by_building_class, rent_level | 존재. wildcard·빈 map·단위 표현 수정 필요. 실거래 유형/표본은 trade_building_type/trade_sample_count를 근거에 활용 |
| meta | schema_version, height_quality.unknown_ratio, building_lookup.status | 일치. unknown_ratio는 부속 제외 후 값. pending/processing은 실제 enum |
| meta 근거 | flow_coverage.{weekday,weekend}.coverage_ratio, sources.*.limitations, estimated_fields, missing_fields | 최소 커버리지와 소스 제한의 실제 근거. coverage_ratio는 시간대별 24칸 배열이며 NULL 원소 가능 |
| 사용자 입력 | lat, lng, address, floor, exclusive_area_m2, deposit_krw, monthly_rent_krw, maintenance_krw | candidate 타입. 원천 층 면적을 전용면적으로 자동 대입하지 않음 |
| 파생 입력/결과 | visible_ratio, academy_eligible, students, saturation, level, raw, normalized 등 | RPC에 존재한다고 가정하지 않음 |

임대 근거의 동 이름 역시 v1.2에는 없고 meta.legal_dong_code만 있다. 기존 검증된 법정동 코드표가 주입되면 이름으로 표시하고 그렇지 않으면 코드로 남긴다. 최신 자료 조회에 실패했다고 다른 반경·인접 상권·평균값으로 채우지 않는다.

## 2. R6 법령 확인

2026-09-22 조회 기준: 학원법 현행 본문 시행 2023-10-19(lsiSeq=249991), 시행령 시행 2026-03-24(lsiSeq=284907)를 확인했다.

- **학원법 제5조제2항**: 학교교과교습학원·교습소와 유해업소의 동일 건축물 내 공존 제한.
- **제5조제4항**: 유해업소는 교육환경 보호법 제9조와 연결되며 PC방 및 법정 조건을 충족한 복합영업 등에 제외 규정이 있다. 명세의 다섯 용도 키워드는 법정 목록 전체가 아니다.
- **제5조제5항**은 “연면적 1천650제곱미터 이상의 건축물”에 예외를 둔다. 다만 같은 층 수평거리 20m 이내, 바로 위·아래 층 수평거리 6m 이내이면 그 예외를 적용하지 않는다. 면적은 후보 점포 전용면적이 아니다.
- **시행령 제4조**는 교육감 협의 전 지역교육환경보호위원회 심의 절차를 규정한다. 1,650㎡ 기준의 현행 출처가 아니다.
- **시행령 제4조의2**는 법 제5조제4항의 제외 영업 범위인 휴게음식점영업을 구체화한다. 휴게음식점이라는 용도명만 보고 모든 복합영업이 예외라고 판단하지 않는다.

출처: [학원법 제5조](https://www.law.go.kr/LSW/LsiJoLinkP.do?docType=JO&joNo=000500000&languageType=KO&lsNm=학원의%20설립ㆍ운영%20및%20과외교습에%20관한%20법률&paras=1), [시행령 제4조·제4조의2 현행 본문](https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=284907), [법제처 입지·시설기준 설명](https://easylaw.go.kr/CSP/CnpClsMain.laf?ccfNo=2&cciNo=1&cnpClsNo=2&csmSeq=1140&popMenu=ov).

**2026-09-23 사용자 확정:** R6 키워드 관측 시 -40 위험 가설 유지. 표제부 building.gross_area<1650㎡이면 예외 없음으로 academy_eligible=false, ≥1650㎡ 또는 면적 결측이면 수평·상하 거리 미확인으로 NULL. v0에서 실간 거리는 계산하지 않는다. gross_area는 DB 표제부에 존재하나 RPC v1.2에는 없어 S2-2에서 노출한다. 다른 R1/R2 규칙으로 false가 결정된 경우 R6의 NULL이 그 false를 덮지 않는다. 키워드가 없다는 이유만으로 실제 유해업소 부재/등록 가능을 보증하지 않는다. 법정 등록 가능성 확정 서비스는 이번 범위가 아니다.

## 3. 실제 예상 시간

로컬 DB의 250m population_cells **10,127행** 확인. cell_id 정렬 후 매 40번째인 254셀을 골라 EPSG:5179 중심점→4326, 층 2·주소 없음·800/1000m로 두 차례 조회했다. **총 1,016회**, 지속 연결·직렬·read only. 강남 3곳의 p95만 서울 전체에 곱하지 않았다. 콜드 캐시 실험이나 원격/HTTP 측정은 아니다.

| 1차 측정 | RPC 내부 평균 | RPC 내부 p95 | DB 클라이언트 왕복 평균 |
|---|---:|---:|---:|
| 800m, 254회 | 20.43ms | 32.95ms | 21.45ms |
| 1000m, 254회 | 26.41ms | 42.29ms | 27.43ms |

2차 왕복 평균은 20.65/26.97ms. 10,127×(두 반경 평균)의 조회 예상은 **8.04~8.25분**, RPC 내부 시간만은 7.69~7.91분. meta.total_ms는 진단 경과시간이며 EXPLAIN Execution Time과 같다고 하지 않는다.

배치 전체는 추출·백분위용 원시값 생성·R2 게시·COPY·검증·VACUUM을 포함해 **로컬 10~15분 계획치**, 운영 timeout은 우선 30분을 제안한다. 뒤쪽 단계는 아직 미구현/미측정이다. 원격에서 호출당 네트워크 시간이 추가 10ms이면 직렬 20,254회에 약 3.38분이 추가된다. 원격 전체 시간을 보장하지 않는다. 표본 기록은 `.local/validation/s2-plan/reference-benchmark*.json`에 있다. 승인 후 전수 배치의 실제 시간·크기·결측 비율을 정식 검증 문서로 남긴다.

## 4. S2-1 — 기준 분포 배치

### 파일과 migration

- `supabase migration new score_reference`: public.score_reference와 private 실행 메타데이터/현재 스냅샷 관리. 기존 migration 수정 없음. 명세 7개 컬럼을 유지하고 preset_version·snapshot 식별자를 추가해 같은 preset_id의 규칙 변경을 섞지 않는다. anon/authenticated 읽기만 허용, 쓰기는 배치 전용.
- `ingest/score_reference.py`: PR 8의 DB 연결 가드·R2 게시/재읽기·실패 보존·VACUUM 경로 재사용. 로컬 기본, 원격 미활성 유지.
- `lib/scoring/types.ts`, `raw.ts`, `presets.ts`: 입력 타입·가중 원시값 추출을 먼저 만든다. S2-2도 같은 함수를 써 Python/TypeScript 식이 갈라지지 않도록 한다.
- `ingest/score_reference_raw.ts`, `tsconfig.scoring-batch.json`, package script: Python이 수집한 입력을 TS 공통 extractor로 계산하는 배치 진입점. 기존 tsc/Node 22로 실행, 새 런타임 라이브러리 없음. 외부 데이터 API 호출은 추가하지 않는다.
- `.github/workflows/refresh-monthly.yml` 및 reference job/workflow: 기존 matrix job 안의 step이 아니라 **needs: refresh** 후속 job으로 6개 갱신이 모두 성공한 뒤 한 번 실행. 단일 소스 재시도 뒤에도 현재 전체 소스 기준일을 기록. 별도 수동 reference 재시도 가능.
- `tests/ingest/test_score_reference.py`, `tests/integration/test_score_reference.py`, TS raw 추출 테스트; planning/validation/운영 문서.

### 데이터와 실패 정책

1. 10,127셀×2반경을 직접 DB 연결로 조회한다. 800m demand는 인구 800m+학교 1000m, 1000m demand는 인구 1000m+학교 1000m. 동일 셀의 두 응답을 재사용한다.
2. 참조 키는 점수용 7개 + 근거용 1개: demand, flow, transit.nearest_subway_m, transit.subway_boardings_golden, transit.bus_stops, cluster(log1p), environment.stores_total 및 근거 전용 cluster.saturation. 예상 **8개 지표·162,032행**. 포화는 동일 셀·반경의 n_field 또는 students가 NULL이거나 students=0이면 NULL이며 점수 계산에는 사용하지 않는다. NULL 행도 보관해 모집단/결측 분모를 보존한다. 실제 백분위 모집단은 키별 비NULL 행만이다.
3. 건물·실거래·임대·visibility·사용자 임대료는 기준 분포에 넣지 않는다. 기준 셀 층 2의 건물 점수를 서울 분포에 섞지 않는다.
4. 일관된 읽기 스냅샷으로 수집하고 소스 버전·그리드 버전·preset 버전·Git SHA·입력 계약을 manifest에 기록한다. 활성화 직전 소스가 바뀌었다면 성공으로 교체하지 않는다.
5. R2에는 재현 가능한 배치 입력/원시 분포/manifest를 실행별 보존한다. 일부 셀의 관측 결측은 허용하되 RPC 예외·누락 호출·중복 키·잘못된 계약 버전은 전체 배치 실패다. 이전 reference를 유지하고 staging은 노출하지 않는다. 전수 완료 후 원자 교체, 커밋 후 별도 VACUUM ANALYZE.
6. 축·반경별 모집단 크기, 결측률, 소스 기준일, 실행 시간, DB/인덱스/R2 byte 수 기록. 원격 용량을 이유로 셀 수/반경/해상도 축소 금지.

### 백분위 경계 규칙 제안

동률은 1-based 평균 순위/N×100. 기준값 사이의 새 값은 `count(reference < x)/N×100`, 기준 범위 밖은 0/100, 빈 모집단은 NULL로 명시할 것을 제안한다. 하향 지표는 100-pct, 음수 부호 preset도 최종 방향을 일관되게 적용한다. 이 정의와 무관하게 log1p는 순서를 보존하므로 그 자체로 백분위 순위를 바꾸지는 않는다.

## 5. S2-2 — 채점 순수 함수

- `lib/scoring/percentile.ts`, `axes.ts`, `building.ts`, `score.ts`, `types.ts`, preset 로더 및 tests/scoring/*.test.ts. tsconfig.json에서 lib도 strict typecheck 대상으로 명시한다.
- reference/context를 주입해 8축 및 ScoreResult v0.1 생성. DB·네트워크·현재시각·전역 캐시에 의존하지 않고 같은 입력은 같은 결과다.
- reference radius·preset/schema/source 버전 불일치는 근거와 결측으로 반환한다. 가까운 반경 분포로 대체하지 않는다.
- demand 학교 NULL은 학교 항만 제외, 인구 3항 중 NULL은 축 NULL. flow 한쪽 결측은 유효 요일 가중치 100%, 두 쪽 결측은 NULL. coverage 배율 보정 없음.
- NULL 역 거리를 2000m로 취급하는 규칙은 소스가 정상인데 2km 내 역이 없는 경우에만 적용하도록 제안한다. 원천 결측/범위 밖까지 '역 없음'으로 바꾸지 않는다.
- 관측 map에서 해당 분류 키가 없으면 0건, map 자체 NULL이면 결측. stores_total=0의 숙박 비율은 0으로, 학령인구 0/결측의 saturation은 NULL/평가 불가로 명시한다.
- building R3은 6층 이상 -30과 4층 이상 -15를 중복 적용하지 않는다. pending/processing은 명세대로 60 및 대기 근거. 알려지지 않은 승강기 수를 0으로 바꾸지 않는다.
- visibility 미계산은 pending/NULL. S2-3 워커·레이캐스트 구현 없음. rent_efficiency 범위 미보정은 명세대로 NULL/근거만; 임의 lo/hi 없음.
- 결측 3축 이상 total=NULL, 유효 가중치 합 0도 NULL. 재가중 함수는 normalized/raw/reference를 그대로 유지하고 effective_weight·contribution·total만 재계산한다. confidence는 preset 기본 가중치 기준으로 계산하여 슬라이더가 데이터 품질을 바꾸지 않게 할 것을 제안한다.

### 필수 테스트

| 범주 | 확인 |
|---|---|
| 실제 건물 fixture | PR 7 역삼로 460 footprint/address_cache 두 경로의 3층·4층 응답 재사용. 3층: clamp(60+25+10+15)=100. 4층: 60+25-15+5+15=90. 173.68㎡는 원천 층 용도 면적으로만 보존 |
| 배열/규칙 | 같은 층 복수 용도 중복 가점 방지, 옥탑/미상 층 제외, elevator NULL/0 구분, 6층 R3 비중복, 지하 R7, pending 60 |
| R6 | 1,649/1,650㎡ 및 면적 NULL. 미만 false, 이상/결측 NULL. 실간 거리 계산은 구현/테스트 범위에서 제외하며 v1.2 미노출과 S2-2 추가 입력을 구분 |
| 원시값 일치 | TS 공통 extractor와 batch 저장값 전수 대조; 800m 인구+1000m 학교 조합, NULL 전파, 관측 0 보존 |
| 정규화 | 동률·빈 분포·최소/최대/범위 밖·삽입값·단조성·역방향·log1p·반경/version 불일치 |
| 종합/신뢰도 | 1/2축 결측 재배분, 3축 total NULL, 가중치 0, coverage<80%, unknown>0.3, estimated 감점 한 번, 입력 불변성, 동일 입력 결정성, 슬라이더 normalized 불변 |
| 실제 응답 연결 | 대치·학여울·한티×800/1000m×2층 6조합에서 paired school 입력으로 ScoreResult 생성. 이는 계약 연결 검사이며 S2-4의 실제 학원 순위 검증을 앞당기지 않음 |

각 PR에서 pnpm lint/typecheck/test 및 관련 DB 통합 테스트를 통과시킨다. S2-1 전수 배치 이후 S2-2를 진행하며 각각 독립 PR로 낸다. 구현은 main에서 분기하고 기획 문서 수정은 코드와 별도 커밋한다. PR 첫 줄 base: main, 말미 (a)(b)(c) 유지.

## 6. 승인 범위

이 계획 승인에는 R1 입력 보완, R6 불명 시 NULL 판정, reference/context 주입과 백분위 경계·6조합 반경 명확화가 포함된다. 기존 사용자 결정(800m·초중등 계수·cluster 양의 방향·포화 별도·임대 보정 유보)은 유지한다. S2-3, S2-4, 서울 전체 건물, 원격 전환, UI·공개 채점 API 배포는 포함하지 않는다.

## S2-2 구현·검증 완료 — 2026-09-23

S2-1(#12) 머지 후 main에서 `s2/scoring`으로 분기했다. 명세 v0.1.2의 순수 채점·프리셋·ScoreResult v0.1 및 입력 v1.3 gross_area를 구현했다. 정밀도 손실을 막기 위한 SELECT-only reference RPC를 추가했고, 실제 두 반경 155,815개 비NULL 값의 HTTP/binary 대조가 일치했다. 기준 분포도 preset v0.1.2 / schema v1.3으로 재생성했다. [S2-2 검증](../validation/s2-2-scoring-20260923.md)에 6개 고정 좌표·반경과 4개 실제 건물 경로 결과를 기록했다. 학여울은 건물 없음으로 3축 결측·총점 NULL이며 60점 도형 보류와 구분한다. 원격 전환·S2-3·S2-4는 이번 범위에서 수행하지 않았다.
