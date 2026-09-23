# 길목(GILMOK) 채점 명세 — scoring-spec.md

> 작성일: 2026-09-22 · 버전: **v0.2 (2026-09-23 사용자 승인, 건물 배치상 노출 조건)**
> 입력 계약: `docs/planning/data-sources.md` §3 `score_inputs` **v1.3** (all_floors 포함) + `buildings_in_radius`
> 기준 문서: `docs/planning/location-simulator.md` — "S2 인계 — S1 마감" 절
> 상태: **전부 가설.** 가중치·부호·계수·임계값은 §8 검증을 통과하기 전까지 가설이며, 검증 결과에 따라 v0.2로 갱신한다. S2-1은 medium, S2-2는 high로 구현한다. S2-1 PR을 먼저 올리고 머지 후 main에서 S2-2를 시작한다. S2-3·S2-4는 별도 세션이다.

> 입력 보완: S1 v1.2 실제 JSON 대조와 사용자 결정을 [대조표와 계획](s2-1-2-plan.md)에 반영했다. S2-2에서 `building.gross_area`를 RPC v1.3에 추가했고, 코드와 기준 분포도 같은 계약으로 갱신했다.

---

## 0. 원칙

1. **채점은 순수 함수다.** `score(inputs_primary, inputs_school, buildings, visibility, candidate, preset, reference, context) → ScoreResult`. 서버(Edge Function)와 클라이언트(가중치 슬라이더 재계산)가 `/lib/scoring`의 같은 코드를 쓴다. 외부 호출·DB 조회·Date.now 없음. reference는 반경·preset/schema/source 버전이 일치하는 기준 분포다. context의 검증된 서울 경계 거리·법정동 코드표·computed_at(또는 inputs_primary.meta.computed_at)을 주입한다. 없는 보조 입력은 미확인으로 남긴다.
2. **결측은 0점이 아니다.** 입력의 NULL은 해당 축을 "평가 불가"로 두고 가중치를 나머지 축에 재배분한다(§6). 결측을 평균값·0·이웃값으로 채우지 않는다.
3. **모든 축에 근거를 동봉한다.** 원시값, 기준 분포 대비 백분위, 적용 규칙, 결측·추정 사유. 사용자는 점수가 아니라 근거를 보고 판단한다.
4. **업종 프리셋 = 가중치·반경·시간창·규칙·층 선호의 집합.** 첫 프리셋은 `academy_v0`. 엔진 코드는 프리셋에 의존하지 않는다.
5. **S1 인계의 결측·편향을 채점 단계에서 보정하지 않는다.** 임대동향 NULL, 교통 요일 미분리, 경기 정류장 누락, 대장 미연결, unknown 높이, 생활인구 커버리지, 주민등록 15~18 vs 생활인구 15~19. 각각을 §7 신뢰도에 드러낼 뿐이다.

---

## 1. 입력

### 1.1 RPC 호출 (후보지 1곳당)

| 호출                                           | 용도                                                                |
| ---------------------------------------------- | ------------------------------------------------------------------- |
| `score_inputs(lat, lng, 800, floor, address)`  | 주 반경. demand(인구)·flow·transit·market·compete·building·rent     |
| `score_inputs(lat, lng, 1000, floor, address)` | `demand.schools`와 최근접 역 보조 확인에만 사용. 나머지 묶음은 무시 |
| `buildings_in_radius(lat, lng, 1000)`          | 가시성 레이캐스트·3D 표시                                           |

반경은 프리셋 값. academy_v0은 **초·중등 대상, 도보 12~13분·자전거·라이딩(차량 픽업)을 포함한 통원권 800m**를 주 반경으로 둔다(사용자 결정). 라이딩 원생은 800m 밖에서도 오므로 이 반경은 보수적 추정이며, 라이딩 비중이 높은 학원 유형은 v0.2에서 1km 프리셋을 따로 검토한다. 학교는 1km.

### 1.2 사용자 입력 (candidate)

| 필드                                           | 필수 | 용도                                     |
| ---------------------------------------------- | ---- | ---------------------------------------- |
| lat, lng                                       | 필수 | 후보 좌표                                |
| address                                        | 권장 | 대장 온디맨드 경로. 없으면 도형 기반     |
| floor                                          | 필수 | 요청 층. 건물 적합성·가시성 목표 높이    |
| exclusive_area_m2                              | 선택 | 전용면적. 임대료 효율·등록 면적 규칙(R2) |
| deposit_krw, monthly_rent_krw, maintenance_krw | 선택 | 임대료 효율 축. 없으면 축 NULL           |

사용자 임대료는 이 후보지 채점에만 쓰고 `candidates` RLS 밖으로 나가지 않는다.

### 1.3 프리셋 (preset)

```
{
  id: "academy_v0", version: "0.2", reference_version: "0.1.2",
  radius_primary_m: 800, radius_school_m: 1000,
  golden_hours: [15, 22),                 // 반개구간, S1과 동일
  weights: { … §3 },
  floor_curve: { … §5.7 },
  demand_coef: { pop_5_9: 0.8, pop_10_14: 1.0, pop_15_18: 0.8, school_elem: 300, school_mid: 300, school_high: 150 },
  saturation: { field: "입시.검정 및 보습", per_1000_students_high: 60, per_1000_students_mid: 25 },   // §4.4 포화 지표
  rules: { … §5 }
}
```

---

## 2. 정규화 — 기준 분포 테이블

"서울에서 이 값이 상위 몇 %인가"를 답하려면 서울 전체 후보 지점의 분포가 필요하다.

### 2.1 `score_reference` 배치 (S2-1)

- 서울 250m 격자 **10,127개 셀의 중심점**을 후보로 삼아 `score_inputs(중심, 800, floor=2)`와 `(중심, 1000, 2)`를 배치 실행하고 축별 원시값을 저장한다. 254셀×2반경×2회 로컬 읽기 전용 실측에서 조회 전체 예상 8.04~8.25분, 게시·저장·검증 포함 10~15분 계획치다. 2026-09-23 전체 로컬 실측은 수집 463.912초, 게시·검증·저장 포함 483.816초다([전수 검증](../validation/s2-1-score-reference-20260923.md)). 원격 시간은 아직 미검증이다.
- 저장: `score_reference(preset_id, radius_m, cell_id, axis_key, raw_value, computed_at, inputs_schema_version)`. preset_version·snapshot도 저장한다. 월간 갱신 matrix 전체 성공 **뒤에** `needs: refresh` 후속 job으로 한 번 실행한다. 단일 소스 재시도 뒤에는 현재 전체 소스 버전으로 재생성한다.
- 백분위: 축별로 `raw_value IS NOT NULL`인 셀만 모집단. 후보 원시값의 1-based 평균 순위/모집단 크기 × 100. 동률은 평균 순위. 새 값은 count(reference < x)/N×100, 범위 밖 0/100, 빈 모집단 NULL. 반경·버전이 다른 분포를 대체 사용하지 않는다.
- **강남구 한정 소스(건물·실거래)는 넣지 않는다.** 서울 전체가 아닌 분포로 "서울 백분위"를 만들지 않는다. 건물 적합성·가시성·임대료 효율은 §5 규칙 기반 절대 점수다.
- 동일 셀의 800m demand는 인구 800m+학교 1000m, 1000m demand는 인구/학교 1000m를 결합한다. raw 추출은 배치와 순수 함수가 공유하는 TypeScript 한 구현을 사용한다. Python은 DB 조회·Parquet/R2·COPY를 담당한다.
- 데이터·manifest는 원자 교체한다. 실패하면 이전 기준 분포를 유지한다. 월별 실행 원본·분포·manifest는 R2에 불변 revision으로 보존한다.
- 셀 중심이 한강·산·비거주지면 여러 축이 NULL이다. 모집단에서 제외하되 제외 비율을 `reference_coverage`로 축별 기록하고 근거에 표시한다.

- 저장 지표는 점수용 7개와 근거 전용 `cluster.saturation` 1개, 총 8개·**162,032행**이다. `cluster.saturation`은 동일 셀·반경의 `n_field / (students / 1000)`이며 분자 또는 분모가 NULL이거나 students=0이면 NULL이다. 관측 n_field=0이고 students>0일 때만 0이다. 포화 서울 백분위 표시용으로만 사용하며 점수 계산에는 쓰지 않는다. 테이블 주석에도 이 구분을 명시한다.

### 2.2 정규화 함수

```
pct(axis, raw) = percentile_rank(score_reference[axis], raw)   // 0~100
```

축마다 단조 방향(↑ 높을수록 좋음 / ↓ 낮을수록 좋음)을 정한다. cluster(§4.4)는 raw를 log 변환한 뒤 백분위를 구한다.

---

## 3. 축과 가중치 — academy_v0 (가설)

원 기획서의 9축을 S1 실데이터에 맞춰 **8축**으로 조정한다. 임대동향 상권 밴드는 학원가에서 사실상 결측이라 임대료 효율 축은 사용자 입력이 주 데이터가 된다.

| #   | 축 key          | 가중치 | 방향    | 주 입력 (v1.2)                                                          | 정규화       |
| --- | --------------- | ------ | ------- | ----------------------------------------------------------------------- | ------------ |
| 1   | demand          | 30     | ↑       | demand.pop_5_9·pop_10_14·pop_15_18, demand.schools(1km)                 | 백분위       |
| 2   | flow            | 15     | ↑       | flow.weekday.golden_avg_pop, flow.weekend.golden_avg_pop                | 백분위       |
| 3   | transit         | 15     | ↑       | transit.nearest_subway_m, subway_boardings_golden, bus_stops            | 백분위(합성) |
| 4   | cluster         | 15     | ↑ (log) | compete.academies_by_field["입시.검정 및 보습"], academies_total        | 백분위(log)  |
| 5   | exposure      | 5     | ↑       | 레이캐스트 visible_ratio (클라이언트)                                   | 절대         |
| 6   | building        | 10     | 규칙    | building.floor_use, all_floors, elevators, floors_above, location_basis | 절대         |
| 7   | environment     | 5      | 규칙    | market.stores_total, stores_by_lcls                                     | 백분위+감점  |
| 8   | rent_efficiency | 5      | ↑       | 사용자 임대료, demand·flow 점수, rent.trade_median_per_m2(근거만)       | 절대         |

합 100. 슬라이더는 가중치를 바꾸고 합이 100이 아니어도 된다(비율만 쓴다). 프리셋 저장 시 정규화.

**가중치 근거(가설):** 학원은 목적지형 업종이라 지나가다 들어오는 유동보다 통원권 안의 학령인구가 결정적이다(demand 25). 대치동처럼 밀집이 곧 목인 업종 특성을 cluster 15로 둔다. 과밀은 점수가 아니라 포화 지표(§4.4)로 따로 보여준다. 간판보다 검색·소개로 오는 업종이라 가시성 10. **이 순서 자체가 §8 검증 대상이다.**

---

## 4. 축별 계산 — 백분위 축

### 4.1 demand (수요)

```
raw = c.pop_10_14×pop_10_14 + c.pop_15_18×pop_15_18 + c.pop_5_9×pop_5_9
    + c.school_mid×schools_1km.mid + c.school_high×schools_1km.high + c.school_elem×schools_1km.elem
```

- academy_v0은 **초·중등** 대상(사용자 결정). 10~14세 1.0, 5~9세·15~18세 0.8. 학교 1개를 학령인구 300명(초·중), 고등은 150명과 등가로 둔다. 고등 입시 프리셋에서는 계수가 뒤집힌다.
- pop은 행정동 면적 비례 `estimated=true` → §7 감점.
- pop 세 값 중 하나라도 NULL이면 축 NULL(`missing_population_coverage`). schools NULL이면 0으로 두지 않고 학교 항만 제외하고 근거에 표시.
- **15~18세는 주민등록 1세 원본 합계**다. 생활인구 15~19세와 같은 값으로 취급하지 않는다(S1 인계).

### 4.2 flow (유동)

```
raw = 0.7×weekday.golden_avg_pop + 0.3×weekend.golden_avg_pop
```

- 평일 골든타임(등하원)이 주, 주말은 보조. 둘 중 하나 NULL이면 있는 쪽만 100%로 쓰고 근거에 표시.
- `flow.low_coverage=true`면 점수는 그대로 계산하고 §7에서 감점. 커버리지 보정 배율은 적용하지 않는다(S1과 동일).
- 연령별 유동은 v1.2가 노출하지 않으므로 v0에서 쓰지 않는다. 필요해지면 입력 계약 v1.3 요청.

### 4.3 transit (교통)

세 지표를 각각 백분위로 만든 뒤 합성한다.

```
d            = nearest_subway_m  (정상 소스에서 2km 내 역 없음이 확인된 NULL만 2000; 그 외 결측 유지)
subway_score = pct(nearest_subway_m, d, 방향=↓)
board_score  = pct(subway_boardings_golden)         // NULL이면 제외
bus_score    = pct(bus_stops)
score        = 0.5×subway + 0.3×board + 0.2×bus    (NULL 지표 제외 후 재정규화)
```

- 교통 값은 **요일 구분 없는 일평균**(3개월 합계÷달력 일수)이다. flow는 평일/주말 분리라 시간 기준이 다르므로 두 축을 서로 합성하지 않는다. 각각 백분위로만 쓴다(S1 인계 반영).
- v1.2의 역 거리 결측 사유는 여러 원인을 합친 표현이므로 그것만으로 부재를 단정하지 않는다. `context.inside_seoul=true`와 `meta.sources.subway_positions.available=true`를 함께 확인한 NULL만 2000으로 바꾼다. 원천 미적재/서울 범위 밖·판정 불명 NULL은 유지한다.
- `context.seoul_boundary_distance_m`은 검증된 admin_dongs 서울 외곽까지의 PostGIS 거리다. v1.2에는 이 필드가 없으며 caller가 별도 조회해 주입한다. context가 없으면 경계 여부 미확인으로 기록한다.
- 경기 정류장 누락(서울광역 49.96%)은 서울 경계 후보에서 bus_stops를 과소평가할 수 있다. 후보가 서울 경계 1km 이내면 근거에 `possible_undercount_near_boundary` 표시. **값은 보정하지 않는다.**
- 신분당선 승하차 없음: 근거에 표시만. 대체 추정 없음.

### 4.4 cluster (클러스터/경쟁)

**사용자 결정: 많을수록 좋다(검증된 목). 단, 포화 여부는 별도 지표로 보여준다.**

```
n_field = compete.academies_by_field["입시.검정 및 보습"]   // 원문 키 그대로
raw     = ln(1 + n_field)
score   = pct(cluster, raw)                                 // 점수는 단조 증가

// 포화 지표 (점수에 넣지 않고 근거·경고로만)
students   = pop_5_9 + pop_10_14 + pop_15_18                // 반경 내 학령인구
saturation = n_field / (students / 1000)                    // 학생 1,000명당 입시·보습 학원 수
level      = saturation ≥ 60 ? "high" : saturation ≥ 25 ? "mid" : "low"
```

- 포화 지표는 서울 백분위도 함께 표시한다("서울 상위 5% 밀도"). v0.1.2의 사용자 승인 임계값은 **high ≥ 60, mid ≥ 25**다. 근거는 실제 800m 분포의 **p90=26.1, p99=65.2**이며, high는 서울 상위 약 1%, mid는 상위 약 10% 구간을 표시하려는 기준이다. 본 절의 60/25가 문서의 이전 40/20 예시보다 우선한다. 실제 공급 과잉 여부는 §8에서 검증한다.
- level=high면 근거에 "경쟁 포화 구간: 이 자리는 검증된 목이지만 신규 진입 시 차별화가 필요"를 표시한다. 점수는 깎지 않는다. 포화 지표의 근거에는 다음 문구를 함께 표시한다: **"이 지표는 반경 내 거주 학령인구 대비이며, 대치동처럼 외부 통학 수요가 큰 곳은 실제 공급 과잉과 다를 수 있다"**.
- 과목(국어·논술) 식별은 v0에서 하지 않는다. `TRNG_CRS_NM`의 "보습·논술" 세분화는 §8 결과를 보고 v0.2에서 결정.
- 부호를 반대(경쟁 감점)로 뒤집는 프리셋은 `sign: -1`로 지원. 카페·편의점 프리셋용.
- `academies_total`은 근거 표시용. academies_by_field가 NULL이면 결측, 관측 map에 분야 키가 없으면 0건이다. students=0 또는 일부 인구 NULL이면 saturation/level은 NULL이며 무한대/0으로 보정하지 않는다.

---

## 5. 축별 계산 — 규칙 축 (절대 점수)

### 5.5 exposure (건물 배치상 노출 조건) — v0.2

**입력:** 기존 buildings_in_radius(1km)의 footprint와 차폐 높이(unknown=4m), 후보 좌표·층, **1km 내 모든 역** 좌표, 1km 내 학교 좌표. exposure_inputs v0.2가 전부 EPSG:5186 미터 좌표로 제공한다. 역은 transit_stops의 역 ID 기준이며 노선별 환승역 대표점을 임의로 합치지 않는다. 역이 없으면 역 동선 집합은 빈 배열이다.

**목표점:** 후보 건물 도형이 있으면 이동 완료한 샘플에서 가장 가까운 도형 경계점, 없으면 후보 좌표. target_z=(floor−1)×3.3+2.0m, 눈높이는 1.5m다. 후보 좌표 fallback에는 `candidate_footprint_missing_self_occlusion_unaccounted`를 남기고 §7 신뢰도 −5를 한 번 적용한다.

**샘플과 가중치:**

- 링: 5186 격자 북쪽 0°에서 시계방향 10° 간격, **{30,60,100}m × 36방향 = 108점**, 가중치 100/d. 도심 3층 간판의 유효 노출 범위를 앞 도로 건너편까지로 본다는 사용자 결정이다. 150·200·300m 링은 사용하지 않는다.
- 역 동선: 1km 내 각 역마다 후보→역 대표점 직선 20등분의 i/20(i=1…20) 점, 가중치 3.
- 학교 동선: 1km 내 학교마다 후보→학교 대표점 직선 10등분의 i/10(i=1…10) 점, 가중치 2.
- 서로 다른 집합의 중복 좌표는 각 집합의 가중치를 유지한다.

**footprint 내부·경계 샘플 처리:** 후보에서 원래 샘플을 향하는 방향을 유지해 그 샘플 위치부터 바깥쪽으로 최대 30m 밀어낸다. 모든 도형의 합집합을 벗어난 첫 지점을 사용한다. 중간에 붙어 있거나 겹친 건물이 있으면 함께 통과해야 한다. 구멍 내부도 건물 밖으로 취급한다. 경계 바로 밖 1mm를 사용하고 이동 총량은 30m를 넘기지 않는다. 30m 안에 못 나오거나 원점과 같아 방향을 정할 수 없으면 제외한다. 이미 밖이면 이동하지 않는다. 가중치는 **원래 샘플 반경·집합 기준**을 유지하며 도로에 스냅하지 않는다.

원래/최종 좌표·이동거리·이동 여부를 보존한다. 근거에 전체·집합별 제외 비율(제외 점 수/생성 점 수), 이동 점 수, 제외 전/후 가중치와 제외 가중치 비율을 남긴다. 제외된 점은 점수 분자·분모에서 뺀다. 유효 가중치가 0이면 점수 NULL이다.

차폐 판정은 기존 3D 시선-건물 프리즘 교차를 유지한다. 후보 건물만 제외하며 WFS·작은 부속건물도 포함하고 unknown은 4m다. 가시 가중치/유효 가중치가 visible_ratio, exposure 점수는 100×visible_ratio다. 실제 간판이 보인다는 단정 대신 건물 배치상 노출 조건을 뜻한다.

근거에는 상태와 관계없이 항상 **"가로수·가로시설물·간판 크기 미반영, 현장 확인 필요"**를 표시한다. 지형·실제 보도·출입구 경로를 모델링하지 않는다. 신뢰도는 §7을 유지한다.

### 5.6 building (건물 적합성)

시작 60, 규칙 합산, 하한 0 상한 100.

| 규칙              | 판정                                                                                                 | 점수                                          |
| ----------------- | ---------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| R1 등록 가능 용도 | 요청 층 `floor_use[]`의 `use_name`·`other_use` 중 하나에 "제2종근린생활시설" 또는 "교육연구시설" 포함 | +25                                           |
|                   | "제1종근린생활시설"만 있거나 주거·공업·창고                                                          | −40, `academy_eligible=false`                 |
|                   | floor_use NULL(대장 미연결·pending)                                                                  | 보류(60 유지), §7 감점                        |
| R2 면적           | exclusive_area_m2 ≥ 500 이고 교육연구시설 아님                                                       | −30, `academy_eligible=false`                 |
| R3 승강기         | floor ≥ 4 이고 elevators.passenger = 0                                                               | −15                                           |
|                   | floor ≥ 6 이고 passenger = 0                                                                         | −30                                           |
| R4 층 선호 | §5.7 floor_curve (지상층만) | −10 ~ +10 |
| R5 같은 건물 학원 | all_floors 중 "학원" 용도인 서로 다른 (floor_kind,floor_no) 수 n (요청 층·옥탑·미상 제외)                                            | +5×min(n, 3)                                  |
| R6 유해업소 동거  | all_floors 용도명에 유흥주점·단란주점·숙박·노래연습장·무도 포함                                      | −40. gross_area<1650이면 false, ≥1650 또는 면적 결측이면 NULL (§5.6 상세) |
| R7 지하           | floor < 0                                                                                            | −25                                           |

- R1은 `floor_use`가 배열임을 따른다. 실제 역삼로 460은 use_name="학원", other_use="제2종근린생활시설(학원)"이다. all_floors에는 other_use/use_code가 없어 그 배열만으로 법정 용도 등급을 확정하지 않는다. 같은 층 복수 용도를 중복 가점하지 않는다.
- R3은 floor≥6의 -30을 적용할 때 ≥4의 -15를 중복 적용하지 않는다. 승강기 NULL은 0대가 아니다.
- R6 키워드가 관측되면 -40 위험 가설을 적용한다. **2026-09-23 사용자 결정:** 표제부 `building.gross_area`(㎡, 원천 totArea)가 **1,650㎡ 미만이면 면적 예외 없음으로 academy_eligible=false**, **1,650㎡ 이상이면 수평·상하 거리 미확인으로 NULL**이다. 면적 NULL도 NULL이다. **v0에서는 실간 거리를 계산하지 않는다.** 다른 R1/R2에서 false가 확정된 경우 R6의 NULL이 false를 덮지 않는다. 후보 전용면적이나 all_floors 면적 합으로 gross_area를 대신하지 않는다.
- 법령 정정: 동일 건축물 공존 제한은 **학원법 제5조제2항**, 유해업소 범위·제외는 **제4항**, “연면적 1천650제곱미터 이상의 건축물” 예외는 **제5항**이다. 예외에도 같은 층 수평거리 20m 이내, 바로 위·아래층 수평거리 6m 이내는 제한된다. 현행 **시행령 제4조**는 교육감 협의 전 위원회 심의 절차이며 면적 예외의 출처가 아니다. **제4조의2**는 법 제5조제4항의 제외 영업(휴게음식점영업)을 구체화한다. 용도 키워드는 법정 유해업소 목록 전체나 실제 영업 상태를 증명하지 않으므로 결과는 규칙 기반 등록 위험 신호다.
- 법령 확인: 2026-09-22 조회, [학원법(시행 2023-10-19) 제5조](https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=249991), [시행령(시행 2026-03-24) 제4조·제4조의2](https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=284907), [법제처 입지·시설기준](https://easylaw.go.kr/CSP/CnpClsMain.laf?ccfNo=2&cciNo=1&cnpClsNo=2&csmSeq=1140&popMenu=ov).
- `academy_eligible`은 이 축의 부산물(`derived`)로 반환한다. RPC에는 없다(S1 결정).
- `meta.building_lookup.status ∈ {pending, processing}`이면 60 유지, 근거 "대장 조회 대기 중", §7 −15. 앱은 ready 후 재채점.
- 역삼로 460 예시: 2종근생 +25, 4층·승강기 0 −15, 4층 곡선 +5, 다른 층 학원 3개 +15, 유해업소 없음 → 60+25−15+5+15 = **90**. 3층이면 승강기 감점이 없어 100 상한. (검증 §8.3에서 이 값이 직관과 맞는지 본다.)

### 5.7 floor_curve (academy_v0)

| 층   | 점수    | 비고                              |
| ---- | ------- | --------------------------------- |
| 1    | 0       | 임대료 높고 학원 관행상 이점 적음 |
| 2~3  | +10     | 최적                              |
| 4~5  | +5      | 승강기 없으면 R3가 따로 감점      |
| 6+   | −10     |                                   |
| 지하 | R7 −25만 적용 | R4 곡선은 적용하지 않음         |

### 5.8 environment (상권 환경)

```
vitality = pct(stores_total)                          // 상권 활력
share_I1 = stores_by_lcls["I1"] / stores_total        // 숙박 대분류 비율
penalty  = min(25, 500 × share_I1)
score    = clamp(0.8×vitality − penalty + 20, 0, 100)
```

- stores_by_lcls=NULL은 결측, 관측 map에 I1 키가 없으면 숙박 0건이다. stores_total=0이면 share_I1=0으로 정의한다.
- 대분류 코드는 원문(G2 소매, I1 숙박, I2 음식, P1 교육 …). 코드→라벨은 상가 분류표를 확인해 프리셋에 둔다.
- "유흥·숙박 밀집은 학부모 기피"라는 가설. §8에서 차이가 안 나면 v0.2에서 축 제거 검토.

### 5.9 rent_efficiency (임대료 효율)

사용자 임대료 입력이 없으면 축 NULL(재배분). 있으면:

```
monthly_total = monthly_rent_krw + maintenance_krw + deposit_krw × 0.05 / 12   // 보증금 연 5% 기회비용
rent_per_m2   = monthly_total / exclusive_area_m2
value         = (demand_score + flow_score) / 2 / rent_per_m2
score         = value를 프리셋 [lo, hi]로 0~100 선형 매핑
```

- `rent.trade_median_per_m2`(동·층·유형별 매매 중앙값, 5건 미만 NULL)는 점수에 넣지 않고 **근거에만**: "대치동 2층 집합상가 매매 중앙값 ○○만원/㎡". 매매→임대 환산은 하지 않는다.
- 임대 공간 미연결 시 `rent.survey_rent_per_m2`, `survey_vacancy`, `survey_building_class`, `rent_level`은 NULL, `survey_by_building_class`는 {}다. 실제 연결 값이 생기면 근거로만 쓰며 점수에는 넣지 않는다. `trade_median_per_m2` 원/㎡를 만원/㎡로 표시할 때만 10,000으로 나눈다. 법정동명은 코드표를 주입받고 없으면 meta.legal_dong_code로 표시한다.
- **[lo, hi]는 §8 검증 3곳의 실제 임대료로 잡는다.** 그 전까지 이 축은 근거만 표시하고 점수는 NULL(§11-6).

---

## 6. 종합점수와 재배분

```
available = { axis | score[axis] != NULL }
W         = Σ weights[available]
total     = Σ_{axis ∈ available} score[axis] × weights[axis] / W
```

- 결측 축의 가중치를 나머지에 비례 배분한 것과 같다. `axes[].status ∈ {scored, missing, pending}`으로 드러낸다.
- **백분위 축 5개(demand·flow·transit·cluster·environment) 중 2개 이상 normalized=NULL이면 total=NULL**, "평가 불가"로 표시. 가중치가 0인 축도 결측 개수에 포함하며 3D·근거는 그대로 보여준다.
- 규칙 축(exposure·building·rent_efficiency)은 결측이어도 total을 계산하고, 결측 축의 `evidence.notes`에 유효 축으로 가중치를 비례 재배분한다는 사실을 남긴다. 결측 점수 자체는 NULL로 유지한다. 워커 미주입·좌표가 건물 도형 밖·사용자 임대료 미입력은 자주 발생하므로 이 사유만으로 평가를 막지 않는다.
- 유효 가중치 합 W=0도 total=NULL이다. 음수/비유한 가중치는 입력 오류다.
- 슬라이더 재계산은 `normalized`를 유지한 채 weight만 바꿔 total·contribution·effective_weight를 다시 구한다. RPC 재호출 없음.

---

## 7. 신뢰도 (confidence)

confidence의 결측 감점은 preset 기본 가중치를 사용하며 슬라이더 조정으로 바꾸지 않는다. 점수와 별개의 0~100. 시작 100, 감점 누적, 하한 0. `confidence.reasons[]`에 적용 항목을 전부 나열한다.

| 조건 (v1.2 필드)                                                        | 감점                    | 근거 문구                                     |
| ----------------------------------------------------------------------- | ----------------------- | --------------------------------------------- |
| 후보 도형 없이 후보 좌표를 가시성 목표점으로 사용 | −5 (한 번) | `candidate_footprint_missing_self_occlusion_unaccounted` — 자기 건물 차폐 미반영, 가시성 과대평가 가능 |
| 결측 축                                                                 | 해당 축 가중치만큼      | "○○ 축 평가 불가: {missing_reason}"           |
| `flow.low_coverage = true`                                              | −10                     | "생활인구 격자 일부 비공개(최소 커버리지 ○%)" |
| demand·flow `estimated = true`                                          | −5 (한 번)              | "인구는 행정동·격자 면적 비례 추정"           |
| `meta.height_quality` 부속 제외 후 unknown_ratio > 0.3                  | −10                     | "주변 건물 ○%가 높이 미상, 가시성 신뢰 낮음"  |
| `meta.building_lookup.status ∈ {pending, processing}`                   | −15                     | "건축물대장 조회 대기 중"                     |
| building 대장 미연결(`building.location_basis='footprint'`·`building.register_pk=NULL`, pending 아님) | −10                     | "이 건물 대장 미연결, 용도·승강기 미확인"     |
| `transit.subway_units_missing_golden > 0`                               | −5                      |                                               |
| 후보가 서울 경계 1km 이내                                               | −5                      | "경기 정류장 데이터 없음"                     |
| rent 사용자 입력 없음                                                   | (결측 축 감점으로 처리) |                                               |

---

## 8. 검증 절차 — 대치동 실제 학원 3곳

가중치·부호·규칙이 현실과 맞는지 보는 첫 관문. 통과 전 프리셋은 `academy_v0 (가설)`로 표시한다.

### 8.1 대상

1. **역삼로 460, 3층** (포도밭) — 정답을 아는 건물
2. **도곡로 409, 2층** — 사용자가 "자리가 진짜 좋다"고 판단한 국어·논술 학원 (사전 순위 1위 예상)
3. **역삼로 546 덕일빌딩, 3층** — 사용자가 "자리가 아쉽다"고 판단한 곳 (사전 순위 3위 예상, 확신도 낮음)

사용자 사전 순위(채점 전 기록): **2 > 1 > 3**. 3번은 사용자도 확신이 낮으므로 결과가 다르게 나오면 그 이유를 근거에서 찾아보는 것 자체가 검증이다.

### 8.2 절차

1. 채점 전에 사용자가 세 곳의 **사전 순위**와 각 축에 대한 직관(높음/중간/낮음)을 적어둔다.
2. 같은 프리셋으로 채점하고 축별 점수·백분위·근거를 표로 놓는다.
3. 사용자가 각 축을 "맞음 / 안 맞음 / 모르겠음"으로 표시하고 안 맞는 축은 이유를 적는다.
4. 총점 순위가 사전 순위와 맞는지 본다.
5. 안 맞는 축의 가중치·계수·부호를 **한 번에 하나씩** 조정하고 세 곳을 다시 채점한다.
6. 조정 결과·이유를 변경 이력에 남긴다. 3곳 과적합을 막기 위해 조정 후 **무작위 격자 셀 5곳**도 함께 채점해 이상값이 없는지 본다.

### 8.3 특히 볼 것

- **cluster:** 2번(도곡로 409)이 3번보다 cluster 점수가 높게 나오는가. 포화 지표가 세 곳에서 어떻게 갈리는지, 임계값 60/25가 대치동에서 의미 있는 구분을 만드는지.
- **반경 800m:** 500m로 바꿔 채점했을 때 순위가 뒤집히는지. 뒤집히면 반경이 결과를 지배하는 것이니 두 반경을 모두 보여주는 UI를 S3에서 검토.
- **demand 계수:** 학교 1개 = 300명 등가가 과한지.
- **environment 가설(숙박 감점)**이 대치동 안에서 의미 있는 차이를 만드는지. 없으면 v0.2에서 축 제거.
- **exposure:** 포도밭 3층 간판이 대치역 방향에서 실제로 보이는지와 visible_ratio가 맞는지 — 사용자가 직접 아는 유일한 축.
- **building 90점(§5.6 예시)**이 "4층·승강기 없음"에 대한 실제 체감과 맞는지.

---

## 9. 출력 계약 — ScoreResult v0.1

```
{
  preset: { id, version },
  inputs_schema_version: "1.3",
  total: number | null,
  confidence: { value: number, reasons: [string] },
  axes: [
    {
      key, label, weight, effective_weight,
      status: "scored" | "missing" | "pending",
      raw: number | null, normalized: number | null,     // 0~100
      contribution: number | null,
      evidence: {
        values: {...}, percentile: number | null, rules_applied: [string],
        reference: { population_size, coverage } | null, notes: [string]
      },
      missing_reason: string | null
    }
  ],
  derived: { academy_eligible: boolean | null, academy_eligible_reasons: [string] },
  computed_at
}
```

---

## 10. 구현 순서 (S2 스프린트 초안)

| 태스크              | 내용                                                                                                                                   | 완료 기준                                    |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| S2-1 기준 분포      | `score_reference` 배치(10,127셀×2반경), refresh-monthly 성공 후속 job 추가                                                                    | 축별 모집단 크기·결측 비율·실행 시간 기록    |
| S2-2 채점 함수      | `/lib/scoring` 순수 함수, 프리셋 로더, ScoreResult v0.1, 단위 테스트(결측 재배분·백분위 2축 결측 NULL·규칙 3축 결측 계산·슬라이더 불변성·역삼로 460 3층=100·4층=90, R6 gross_area 1650 경계·지하층 R7 단독) | 대치·학여울·한티×800/1000m×2층 실제 입력으로 ScoreResult 생성    |
| S2-3 가시성 워커    | 레이캐스트 Web Worker, 샘플점 생성, 자기 건물 제외                                                                                     | 역삼로 460 3층 visible_ratio 산출, 계산 시간 |
| S2-4 검증           | §8 3곳 + 무작위 5셀, 조정, v0.2 문서                                                                                                   | 사용자 서명                                  |
| S2-5 서울 전체 건물 | 별도 태스크(원격 용량 실측 → Pro 검토)                                                                                                 | —                                            |

채점 Edge Function 배포·화면·큐 대기 사용자 흐름은 S3.

---

## 11. 확정된 사용자 결정

2026-09-22 사용자 결정으로 모두 확정됨.

1. cluster — 많을수록 좋다(log). 포화 지표는 점수와 별도로 표시. ✅
2. §8 대상 — 도곡로 409 2층, 역삼로 546 덕일빌딩 3층. ✅
3. 반경 — 800m(초·중등, 라이딩 포함). ✅
4. demand 계수 — 초·중등 기준으로 조정(§4.1). ✅
5. R6 — 법 제5조제5항과 시행령 제4조·제4조의2 확인. 유해 용도 관측 시 gross_area<1650은 false, ≥1650/결측은 NULL. 실간 거리 계산은 v0에서 제외. ✅
6. rent_efficiency [lo, hi] — §8 이후. ✅

## 변경 이력

| 날짜       | 버전 | 내용                                                                           |
| ---------- | ---- | ------------------------------------------------------------------------------ |
| 2026-09-22 | v0.1 | 초안. 입력 계약 v1.2 기준 8축·가중치·규칙·신뢰도·검증 절차. 전부 가설          |
| 2026-09-22 | v0.1 | 사용자 결정 반영: 반경 800m, 초·중등 계수, cluster log+포화 지표, §8 대상 확정 |

| 2026-09-23 | v0.1.1 | 입력 보완 7건·R6 법령 정정 및 gross_area 사용자 결정 반영. reference/context 주입, raw 식 공유, 반경·NULL·백분위·슬라이더 규칙 확정. S2-1 PR 머지 후 S2-2 진행 승인 |


### v0.1.1 입력 보완 7건 요약

1. R1 use_name·other_use 동시 검사, floor_use 배열 처리.
2. R5 all_floors 용도별 행을 층으로 중복 계산하지 않고 층 종류 구분.
3. register_pk·location_basis='footprint' 실제 키/값 사용.
4. rent survey scalar NULL·map {} 및 원/㎡ 단위 구분.
5. 가시성 역/학교 좌표·서울 경계 거리·gross_area를 v1.2에 있다고 가정하지 않음. 역/학교는 S2-3, 경계는 context, gross_area는 S2-2 입력 추가.
6. reference/context 주입으로 순수성 유지.
7. S2 기술 검증 800/1000m 6조합, 학교 1000m 고정. S2-4의 500m 민감도 비교는 별도 500m 분포 준비 후 수행.


### S2-2 구현 계약 보충 — 2026-09-23

명세 v0.1.2의 식을 구현했으며 입력은 v1.3이다. gross_area가 포함된 실제 계약과 전체 JSON은 [data-sources §3](data-sources.md)을 따른다. v1.2 언급은 S1 확인 당시 입력의 출처 기록이며 현재 채점에는 v1.3만 사용한다.

- `loadPreset(id,radius)`는 800/1000m만 허용한다. score는 reference/context를 인자로 받고 DB·네트워크·시계를 읽지 않는다. primary schema/radius/floor 불일치는 모든 축 결측, school 계약 불일치는 demand만 결측, reference의 소스 불일치는 관련 축만 결측이다. 정규화 식의 원시값 추출은 배치와 동일 함수다.
- effective_weight는 유효 축에 재배분된 **0~100%**, contribution은 normalized×effective_weight/100이다. v0.1.3에서는 백분위 5축 중 2축 이상 normalized=NULL 또는 유효 가중치 합 0이면 total=NULL이다. 규칙 축 결측은 이 개수에서 제외한다. `reweight`는 이미 계산된 normalized/raw/confidence를 보존하고, 결측 축 evidence에는 재배분 안내를 중복 없이 남긴다. confidence의 결측 감점은 기본 가중치다.
- 대장 조회 pending/processing은 60점 보류한다. 요청 층 용도 NULL/[]도 60점 보류하며 R4 등 추가 가점은 적용하지 않는다. 다만 이미 관측된 R6 유해업소는 −40과 연면적 판정을 유지한다. 보류 점수는 status=pending, normalized=60(유해업소 관측 시 20)으로 총점에 포함되며, NULL인 결측 축과 구분한다. building 자체 NULL 또는 id/register_pk/location_basis가 모두 NULL인 RPC의 미연결 객체이고 조회 대기도 아니면 축 NULL이다.
- `academy_eligible`은 false 사유가 있으면 false가 우선한다. 용도/면적/유해업소 예외 확인이 부족하면 NULL이다. 전용면적 미입력은 R2 면적을 표제부/층 면적으로 추정하지 않는다. 교육연구시설처럼 면적 조건을 이미 만족하는 용도는 R2 미확인 사유를 붙이지 않는다.
- 일반 테이블 HTTP 숫자를 반올림해 동률을 판정하지 않는다. 정밀도 보존 reference RPC와 binary DB 값의 전수 일치 및 동률 회귀 테스트를 [검증](../validation/s2-2-scoring-20260923.md)에 기록했다. 기준 분포 NULL은 제외하고 관측 0은 보존한다.
- 가시성은 worker 결과가 주입되기 전 pending/NULL, 임대료 효율은 입력과 검증된 lo/hi가 모두 준비되기 전 NULL이다. 근접 상권·평균 임대료·층 면적 대체는 없다. 세 고정 좌표는 계약 연결 검증용이며 실제 학원 순위 검증은 S2-4에 남긴다.

### v0.1.3 — 2026-09-23 사용자 결정

- §6: total 평가 불가 기준을 백분위 5축 중 2축 이상 결측으로 변경. 규칙 축 결측은 유효 축으로 재배분하고 근거에 표시한다. 워커 미주입·도형 밖 좌표·사용자 미입력으로 평가가 막히는 문제를 해소한다.
- §5.7: 지하층은 R4를 적용하지 않고 R7 −25만 적용한다. 다른 용도·면적 규칙은 그대로다.
- 이번 버전은 명세·계산 정책 보정이다. 백분위 원시값·가중치·분포가 바뀌지 않으므로 academy_v0 및 기준 분포 버전 0.1.2, 입력 계약 v1.3, ScoreResult v0.1을 유지한다. 외부 API 응답에 따른 변경이 아니다.

### v0.1.4 — 2026-09-23 사용자 결정

- S2-3 계획 승인. §5.5 후보 도형 부재 시 좌표 fallback 근거 코드와 §7 신뢰도 −5를 추가한다. 실제 fallback 계산에만 적용하며 워커 미주입 자체로 이 감점을 적용하지 않는다. 기본 결측/높이 품질 감점과 별개이며 슬라이더로 바뀌지 않는다.
- 링은 5186 격자 북쪽 0°에서 시계방향 10° 간격이다. 동선은 후보→목적지 직선의 i/N(i=1…N) 점이며 후보는 제외·목적지는 포함한다. footprint 내부/경계 샘플은 분자·분모에서 제외한다. 서로 다른 집합의 중복 좌표는 각 집합의 가중치를 유지한다.
- 입력은 PostGIS가 EPSG:5186으로 변환하며 Worker와 Node는 같은 순수 함수를 사용한다. 지형·실제 도로 경로·출입구는 모델에 없다. 건물 밑면 0m와 높이 사이의 닫힌 프리즘에 시선이 접촉하면 차폐다. 후보 목표점은 구멍을 포함한 도형 경계에서 가장 가까운 점을 선택한다.
- 프리셋/기준 분포 0.1.2, score_inputs v1.3, ScoreResult v0.1은 유지한다. 추가 계약은 data-sources.md의 visibility_inputs를 따른다. 정책 변경은 사용자 결정이며 외부 API 실응답 검증 결과가 아니다.

### v0.2 — 2026-09-23 사용자 결정

- §5.5 전체 개정: 1km 모든 역, 30/60/100m 링, 바깥 방향 최대30m 이동·제외 비율 근거. 축 key는 exposure, 표시는 건물 배치상 노출 조건이다.
- demand 25→30, exposure 10→5. 다른 가중치는 유지하며 합계100이다. 채점 preset.version=0.2, ScoreResult v0.2로 구별한다. 백분위 원시값은 바뀌지 않아 reference_version=0.1.2를 명시적으로 사용한다. score_inputs v1.3과 과거 기준 분포/검증 JSON은 유지한다. 구 visibility 축을 가진 결과는 재계산해야 하며 새 가중치로 조용히 재사용하지 않는다.
- 이전 버전 절의 샘플·가중치 규칙은 당시 기록이며 현재 §3·§5.5가 우선한다. 변경은 사용자 결정으로, 현장 검증 완료를 뜻하지 않는다.
