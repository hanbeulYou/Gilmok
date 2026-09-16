# 길목(GILMOK) 데이터 소스 명세

> 작성일: 2026-09-16 · 버전: v1
> 기준 문서: docs/planning/location-simulator.md
> 목적: S1(데이터 기반) 구현에 필요한 소스별 접근 방법·컬럼·좌표계·적재 방식을 한 곳에 모은다. "확인 필요" 표시는 실제 키 발급 후 응답 스키마로 검증할 것.

## 0. 공통 원칙

- 외부 API는 **배치 적재 스크립트에서만** 호출한다. 프론트와 Edge Function은 Supabase DB만 조회한다.
- 저장 좌표계는 **EPSG:4326**(WGS84)으로 통일한다. 거리 계산은 PostGIS `geography` 타입 또는 `ST_Transform(…, 5186)` 후 `ST_DWithin`을 쓴다. 원천이 EPSG:5186/5174/2097인 파일은 적재 시 변환한다.
- 모든 적재 테이블에 `source`, `source_version`(데이터 기준일), `ingested_at` 컬럼을 둔다.
- 결측·추정값은 `estimated boolean` 플래그로 남긴다. 추정 로직은 이 문서에 적는다.
- 인증키는 `.env`에만 둔다. 리포지토리에 커밋하지 않는다.
- **두 층 저장 구조.** 원본은 오브젝트 스토리지(Cloudflare R2, S3 호환, egress 무료)에 `raw/{source}/{YYYY-MM}.parquet`로 쌓고, Supabase에는 채점에 쓰는 집계 테이블만 둔다. 집계는 배치에서 DuckDB로 R2의 parquet를 직접 읽어 계산한다. 집계 방식이 바뀌면 재다운로드 없이 재집계한다. Supabase는 무료 플랜(500MB) 안에서 운영하는 것을 목표로 한다.
- Python 배치는 [PublicDataReader](https://github.com/WooilJeong/PublicDataReader) 사용을 우선 검토한다. 실거래가·건축물대장·상가업소·지하철/버스 승하차를 DataFrame으로 바로 받을 수 있어 파서 작성 시간을 줄인다. 단, 키 신청은 기관별로 따로 해야 한다.

## 1. 키 발급 체크리스트 (사람이 해야 하는 일)

| 포털                                     | 계정                 | 신청할 서비스                                                                        | 상태 |
| ---------------------------------------- | -------------------- | ------------------------------------------------------------------------------------ | ---- |
| 공공데이터포털 data.go.kr                | 회원가입 후 활용신청 | 건축HUB 건축물대장정보, 소상공인 상가(상권)정보 API, 상업업무용 부동산 매매 실거래가 | ☐    |
| 서울 열린데이터광장 data.seoul.go.kr     | 인증키 발급          | 생활인구, 지하철·버스 승하차, 학원 교습소정보, 학교 기본정보                         | ☐    |
| 나이스 교육정보 개방포털 open.neis.go.kr | 인증키 발급          | 학교기본정보, 학원·교습소 (서울 외 확장 대비)                                        | ☐    |
| Kakao Developers                         | 앱 생성              | Local API(주소→좌표, 좌표→주소)                                                      | ☐    |
| Vworld vworld.gov.kr                     | 인증키 발급          | 지오코더, 건물 데이터 (확인 필요)                                                    | ☐    |

공공데이터포털 API는 대부분 "개발계정 자동승인, 일 10,000 트래픽"이라 배치 적재에는 충분하다. 운영계정 전환은 활용사례 등록이 필요하다.

## 2. 소스별 명세

### 2.1 생활인구 (유동 축)

- 소스: 서울 열린데이터광장 "집계구 단위 서울 생활인구(내국인)" OA-14979 / "행정동 단위" OA-14991
- 형태: **파일 다운로드가 기본.** OpenAPI·Sheet는 집계구는 5일 전 당일자료만, 행정동은 최근 2개월만 제공한다. 과거 이력은 월별 zip(예: `LOCAL_PEOPLE_20260509.zip`)을 받아 적재한다.
- 단위: 집계구(통계청 2016년 기준 코드), 시간대(0~23), 연령대·성별 컬럼
- 주의: 3명 이하는 `*` 처리 → NULL로 적재. 집계구 경계 shapefile은 열린데이터광장 "서울 생활인구 > 행정구역 코드정보"에서 별도 수령(EPSG 확인 필요).
- 적재 범위: 최근 3개월 평일·주말 구분 평균. 시간대별 24행 × 집계구.
- 테이블: `living_pop(tot_reg_cd, dow_type, hour, age_band, avg_pop)` + `census_blocks(tot_reg_cd, geom)`

### 2.2 대중교통 (교통 축)

- 지하철: "서울시 지하철 호선별 역별 시간대별 승하차 인원 정보" OA-12252. 매월 5일 전월 갱신. 1~9호선 서울 관할만 포함. **신분당선은 열린데이터광장이 제공하지 않음(FAQ 명시).** 서울 내 신분당선 역(강남·신논현·논현·신사)은 모두 환승역이라 타 노선 데이터로 커버된다. 경기권 확장 시 대안: (1) 교통카드 빅데이터 통합정보시스템(STCIS, 한국교통안전공단) 신청 — 확인 필요, (2) 역세권 집계구 생활인구로 대체 추정 `estimated=true`, (3) 철도통계연보 연간 승하차(보조).
- 버스: "서울시 버스노선별 정류장별 시간대별 승하차 인원 정보"(OA-12912 계열, 정확한 OA 번호 확인 필요). 정류장 좌표는 "서울시 버스정류소 위치정보"와 조인.
- 역 좌표: "서울시 지하철역 좌표" 또는 역명 매칭. 역명 표기 불일치(괄호 부기 등) 정규화 필요.
- 테이블: `transit_stops(id, type, name, geom)`, `transit_boardings(stop_id, hour, boarding, alighting)`

### 2.3 상가·상권 (상권 축, 경쟁 축 일부)

- 소스: 소상공인시장진흥공단 상가(상권)정보. 엔드포인트 예: `http://apis.data.go.kr/B553077/api/open/sdsc/storeListInRadius`(반경), `storeListInBuilding`(건물 단위), `storeListInPnu`(지번). 페이지당 최대 1,000건.
- 대안: 분기별 전체 CSV(공공데이터포털 15083033)를 받아 서울만 적재. **배치 적재에는 CSV가 낫다.** API는 검증·보정용.
- 컬럼: 상가업소번호, 상호명, 업종 대/중/소분류 코드·명, 지번·도로명주소, 경도, 위도, 층정보
- 주의: 2024년 업종분류 개편(837→247)으로 과거 데이터와 상가업소번호 연계 불가. 최신 분기만 쓴다.
- 테이블: `stores(store_id, name, inds_lcls, inds_mcls, inds_scls, floor, geom)`

### 2.4 학원·교습소 (경쟁·클러스터 축)

- 소스: 서울 열린데이터광장 "서울시 학원 교습소정보" OA-20528 (원본: 한국교육학술정보원 NEIS)
- 컬럼: 학원명, 학원/교습소 구분, 등록상태, 정원, 분야명(보습·외국어·예체능·입시 등), 계열, 과정, 도로명주소, 휴원일자, 수강료(공개 시)
- 좌표 없음 → 도로명주소를 지오코딩(2.8)해서 저장. 실패 건은 `geocode_failed` 플래그.
- 필터: 등록상태 = 개원 중. 분야명으로 과목 클러스터 계산(국어·논술은 보습/입시 계열 안에서 과정명으로 식별, 확인 필요).
- 테이블: `academies(id, name, kind, field, course, capacity, status, geom)`

### 2.5 학교 (수요 축)

- 소스: 서울 열린데이터광장 "서울시 학교 기본정보"(초·중·고 분리 데이터셋 OA-20561 계열) 또는 나이스 학교기본정보 API(`schoolInfo`, 컬럼 `SCHUL_NM`, `ORG_RDNMA` 등)
- 학생 수: 학교알리미 공시자료(연 1회, 파일) — v1은 학교 위치와 급(초/중/고)만 쓰고 학생 수는 v2.
- 좌표 없음 → 지오코딩.
- 테이블: `schools(id, name, level, geom, students nullable)`

### 2.6 주민등록 연령별 인구 (수요 축)

- 소스: 행정안전부 주민등록 인구통계(jumin.mois.go.kr) 행정동·연령별 월간 파일, 또는 서울 열린데이터광장 "서울시 주민등록인구(연령별/동별)" — 어느 쪽이 API로 편한지 확인 필요.
- 단위: 행정동. 반경 집계 시 행정동 폴리곤과 반경 원의 **면적 비례 배분**으로 추정하고 `estimated=true`.
- 학원 프리셋용 연령 밴드: 5~9, 10~14, 15~18.
- 행정동 경계: 통계청 SGIS 또는 서울 열린데이터광장 행정동 경계(EPSG 확인 필요).
- 테이블: `admin_dongs(adm_cd, name, geom)`, `population_age(adm_cd, age_band, population, ref_month)`

### 2.7 건축물 (가시성 축, 건물 적합성 축)

- 소스: 국토교통부 건축HUB 건축물대장정보 서비스(공공데이터포털 15134735). 오퍼레이션: 표제부(`getBrTitleInfo`), 층별개요(`getBrFlrOulnInfo`), 총괄표제부. 요청 파라미터는 시군구코드+법정동코드+번·지 (지번 기반). `_type=json` 지원.
- 필요 컬럼: 표제부 — 건물명, 지상층수, 지하층수, 높이(`heit`, 결측 잦음), 주용도, 연면적, 승강기수(승용·비상용), 사용승인일. 층별개요 — 층번호, 층 용도(`mainPurpsCdNm`), 층 면적.
- 주의: 2024년 건축HUB 전환으로 PK(관리번호) 체계가 바뀌었다. 첨부된 PK 전환 규칙 문서를 참고. 지번 단위 호출이라 반경 조회는 불가 → **건물 footprint를 먼저 확보하고, footprint의 지번(PNU)으로 대장을 조회하는 순서**로 간다.
- 건물 footprint 후보(확인 필요, 하나 선택): (a) 도로명주소 건물DB(juso.go.kr, 건물 폴리곤 + 층수), (b) Vworld 2D 건물 레이어, (c) 국토지리정보원 연속수치지형도 건물, (d) OSM 건물(서울 도심은 커버리지 양호, 높이는 대부분 없음). S1에서 강남구 한 곳으로 (a)와 (d)를 비교해 결정한다.
- 높이 추정: `heit` 결측 시 `지상층수 × 3.3m`, 1층 상업건물은 `× 4.0m`. `estimated=true`.
- 테이블: `buildings(id, pnu, name, geom, floors_above, floors_below, height_m, height_estimated, main_use, elevators, gross_area)`, `building_floors(building_id, floor_no, use_code, use_name, area)`

### 2.8 지오코딩

- 1순위 Kakao Local API `v2/local/search/address.json` (도로명·지번 모두, 일 쿼터 확인). 2순위 Vworld 지오코더.
- 결과는 `geocode_cache(address, lat, lng, provider, fetched_at)`에 캐시. 같은 주소 재호출 금지.
- 후보지 등록 화면의 주소 검색도 이 캐시를 거친다.

### 2.9 상업용 부동산 매매 실거래 (임대료 효율 축)

- 소스: 국토교통부 상업업무용 부동산 매매 실거래가 자료(공공데이터포털 15126463). 파라미터 `LAWD_CD`(법정동 5자리, 예 강남구 11680), `DEAL_YMD`(계약년월). XML.
- 컬럼: 시군구, 법정동, 건물명, 층, 전용면적(또는 건물면적), 거래금액, 건축년도, 용도지역, 계약일. 좌표 없음 → 법정동+건물명+지번으로 지오코딩(정확도 낮음, 동 단위 집계로만 사용).
- 적재 범위: 최근 24개월, 서울 25개 구.
- 파생: 동 단위 ㎡당 매매 단가 중앙값, 층별 중앙값.
- 테이블: `commercial_trades(id, lawd_cd, dong, building_name, floor, area_m2, price_krw, deal_date, geom nullable)`

### 2.10 상업용 임대 동향 (임대료 효율 축)

- 소스: 한국부동산원 부동산통계정보 R-ONE(r-one.co.kr) 상업용부동산 임대동향조사 — 분기별, 상권 단위 임대료(㎡당)·공실률·투자수익률. OpenAPI 제공 여부와 상권 단위 코드 체계 확인 필요. 없으면 분기별 엑셀 수동 적재.
- 용도: 사용자가 임대료를 입력하지 않았을 때 대체값, 그리고 "상권 평균 대비" 비교.
- 테이블: `rent_survey(district_code, district_name, quarter, building_class, rent_per_m2, vacancy_rate)`

### 2.11 사용자 입력 (임대료 효율 축)

- 후보지 등록 시 선택 입력: 보증금, 월세, 관리비, 전용면적. 저장은 `candidates` 테이블 컬럼으로.
- 이 값은 사용자 소유 데이터이므로 다른 사용자 집계에 쓰지 않는다.

## 3. 반경 집계 RPC 입출력 (S1 완료 기준)

`score_inputs(lat float, lng float, radius_m int, floor int)` → JSON

```json
{
  "demand":   {"pop_5_9": 1234, "pop_10_14": 1500, "pop_15_18": 1100, "schools": {"elem": 3, "mid": 2, "high": 1}, "estimated": true},
  "flow":     {"golden_avg_pop": 8200, "hourly": [/* 24 */], "weekday_weekend_ratio": 1.4},
  "transit":  {"nearest_subway_m": 210, "subway_boardings_golden": 5400, "bus_stops_300m": 6},
  "market":   {"stores_total": 820, "stores_by_lcls": {...}},
  "compete":  {"academies_500m": 41, "same_field_500m": 9},
  "building": {"floors_above": 6, "height_m": 21.0, "height_estimated": false, "floor_use": "제2종근린생활시설", "elevators": 1, "academy_eligible": true},
  "rent":     {"trade_median_per_m2": 18500000, "survey_rent_per_m2": 52000, "survey_vacancy": 0.041},
  "meta":     {"radius_m": 500, "sources": {...}, "computed_at": "…"}
}
```

가시성 축은 클라이언트(Web Worker)에서 계산하므로 이 RPC에 포함하지 않는다. RPC는 반경 1km 내 `buildings` geom+height를 별도 엔드포인트 `buildings_in_radius`로 내려준다.

## 4. 갱신 주기

| 데이터             | 주기                                       | 방식                              |
| ------------------ | ------------------------------------------ | --------------------------------- |
| 생활인구           | 월 1회                                     | 파일 다운로드 → 적재 스크립트     |
| 지하철·버스 승하차 | 월 1회(매월 5일 이후)                      | API 또는 파일                     |
| 상가정보           | 분기 1회                                   | CSV 전체 교체                     |
| 학원·교습소, 학교  | 월 1회                                     | API → upsert + 신규 주소 지오코딩 |
| 주민등록 인구      | 월 1회                                     | 파일                              |
| 건축물대장         | 후보지 등록 시 온디맨드 + 월 1회 캐시 만료 | API                               |
| 실거래가           | 월 1회                                     | API                               |
| 임대동향           | 분기 1회                                   | 파일 또는 API                     |

pg_cron이 아니라 GitHub Actions 스케줄로 돌리는 편이 로그 확인이 쉽다. S1에서 결정.

## 5. 라이선스

열린데이터광장·공공데이터포털 데이터는 대부분 공공누리 1유형(출처표시, 상업적 이용 가능). 화면 하단에 출처 표기 영역을 둔다. Kakao Local API는 약관상 결과 캐싱 기간 제한이 있을 수 있으니 확인 필요.

## 변경 이력

| 날짜       | 버전 | 내용                                                                                  |
| ---------- | ---- | ------------------------------------------------------------------------------------- |
| 2026-09-16 | v1   | 최초 작성. 건물 footprint 소스, 임대동향 API, 주민등록 인구 API 경로는 확인 필요 상태 |
