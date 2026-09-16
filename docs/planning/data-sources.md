# 길목(GILMOK) 데이터 소스 명세

> 작성일: 2026-09-16 · 버전: v1.2 (PR 1 로컬 폴백 반영)
> 기준 문서: docs/planning/location-simulator.md
> 목적: S1(데이터 기반) 구현에 필요한 소스별 접근 방법·컬럼·좌표계·적재 방식을 한 곳에 모은다. "확인 필요" 표시는 실제 키 발급 후 응답 스키마로 검증할 것.

## 0. 공통 원칙

- 외부 API는 **배치 적재 스크립트에서만** 호출한다. 프론트와 Edge Function은 Supabase DB만 조회한다.
- 저장 좌표계는 **EPSG:4326**(WGS84)으로 통일한다. 거리 계산은 PostGIS `geography` 타입 또는 `ST_Transform(…, 5186)` 후 `ST_DWithin`을 쓴다. 원천이 EPSG:5186/5174/2097인 파일은 적재 시 변환한다.
- 모든 적재 테이블에 `source`, `source_version`(데이터 기준일), `ingested_at` 컬럼을 둔다.
- 결측·추정값은 `estimated boolean` 플래그로 남긴다. 추정 로직은 이 문서에 적는다.
- 로컬 인증키는 `.env`에만 둔다. GitHub Actions에서는 Secrets를 실행 환경에 주입한다. 키 값은 리포지토리·로그에 남기지 않는다. 최초 커밋부터 `.gitignore`의 `.env*`로 제외하고 `!.env.example`만 예외로 둔다.
- **두 층 저장 구조.** 원본은 오브젝트 스토리지(Cloudflare R2, S3 호환)에 `raw/{source}/{YYYY-MM}.parquet`로 쌓고, Supabase에는 조회용 집계와 공간 조회에 필요한 최소 개체 정보(경계·점포·학원·학교·정류장·건물 등)를 둔다. 개별 실거래와 대용량 원본 이력은 R2에만 저장한다. 집계는 `/ingest/aggregate.py`와 `/ingest/sql/*.sql`에서 DuckDB로 R2 Parquet를 직접 읽어 계산한다. 집계 방식이 바뀌면 재다운로드 없이 재집계한다. Supabase는 500MB 안에서 운영하는 것을 목표로 하며 실제 적재·인덱스 용량으로 검증한다.
- 배치는 **Python 3.12 + PublicDataReader + DuckDB + psycopg**, 실행 스케줄은 **GitHub Actions**로 통일한다. [PublicDataReader](https://github.com/WooilJeong/PublicDataReader)를 우선 활용하되 현재 API와의 호환성은 소스별 실제 응답으로 확인하고, 미지원 소스도 Python으로 처리한다. 키 신청은 기관별로 따로 해야 한다.
- S1 적재 범위: **인구·생활인구·교통·상가·학원·학교는 서울 전체**, **건축물·실거래·임대동향은 강남구 한정**. 서울 전체 건축물 적재는 S2 초반 별도 태스크로 이관한다. 공동주택 세대수는 **v2(S1 제외)**다.
- 미적재·비공개·매핑 실패는 결측으로 남기고 실제 관측 0과 구분한다. 조회 응답에 소스별 기준일·적재 범위·결측 사유를 남긴다. 단계적 적재 범위 밖의 건물·부동산 자료를 임의 추정값으로 채우지 않는다.
- 원격 Supabase 프로젝트와 R2 버킷은 사용자가 만들고 `.env`에 설정한다. 준비 전에는 `supabase start`로 로컬 Supabase에서 개발하며, R2 실연결 검증은 버킷 준비 후 수행한다.
- PR 1 로컬 폴백: R2 환경변수 4개가 모두 비어 있으면 `INGEST_LOCAL_ROOT`(기본 `.local/ingest`) 아래의 로컬 파일시스템을 사용한다. R2와 같은 `raw/{source}/{YYYY-MM}.parquet` 규칙을 유지하고 DuckDB가 로컬 Parquet를 읽는다. 일부 R2 변수만 설정됐거나 설정된 R2 접근에 실패하면 오류를 보고하며 로컬로 몰래 전환하지 않는다. 키 없는 로컬 검증을 R2 실연결 검증으로 표시하지 않는다.
- 이 버전의 변경은 사용자 결정 반영이다. 실제 응답으로 확인되지 않은 항목은 계속 "확인 필요"로 남긴다. 실제 확인 결과가 승인된 결정과 충돌하면 해당 구현을 진행하지 말고 먼저 보고한다.

## 1. 키 발급 체크리스트 (사람이 해야 하는 일)

| 포털                                     | 계정                 | 신청할 서비스                                                                        | 상태 |
| ---------------------------------------- | -------------------- | ------------------------------------------------------------------------------------ | ---- |
| 공공데이터포털 data.go.kr                | 회원가입 후 활용신청 | 건축HUB 건축물대장정보, 소상공인 상가(상권)정보 API, 상업업무용 부동산 매매 실거래가 | ☐    |
| 서울 열린데이터광장 data.seoul.go.kr     | 인증키 발급          | 생활인구, 지하철·버스 승하차, 학원 교습소정보, 학교 기본정보                         | ☐    |
| 나이스 교육정보 개방포털 open.neis.go.kr | 인증키 발급          | 학교기본정보, 학원·교습소 (서울 외 확장 대비)                                        | ☐    |
| Kakao Developers                         | 앱 생성              | Local API(주소→좌표, 좌표→주소)                                                      | ☐    |
| Vworld vworld.gov.kr                     | 인증키 발급          | 지오코더, 건물 데이터 (확인 필요)                                                    | ☐    |

서비스별 활용승인·일 쿼터·페이지 제한은 실제 계정과 응답으로 확인해야 한다. 일괄적인 "일 10,000 트래픽이면 충분" 가정을 구현에 사용하지 않는다.

### 1.1 환경변수 계약 (`.env.example`)

PR 1에서 `.env.example`을 추가했다. 실제 원격 키 발급 상태는 미확인이다. 다음 이름을 사용하고, 실제 비밀 값은 사용자가 `.env`에 채운다.

| 목적 | 환경변수 | 필요 조건 |
| --- | --- | --- |
| 건축HUB·상가 검증·실거래 | `DATA_GO_KR_SERVICE_KEY` | 각 서비스 활용승인 필요 |
| 서울 데이터 | `SEOUL_OPEN_DATA_API_KEY` | 인증 API 사용 시 필요 |
| 주소 지오코딩 | `KAKAO_REST_API_KEY` | 1순위 제공자 |
| Vworld 대체 경로 | `VWORLD_API_KEY` | 대체 지오코더·건물 소스를 채택할 때 |
| 나이스 직접 조회 | `NEIS_API_KEY` | 서울 제공 자료 대신 직접 조회할 때 |
| Supabase 적재·조회 | `SUPABASE_DB_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY` | 원격 준비 전 로컬 환경 값 사용 |
| R2 | `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` | 사용자가 버킷 준비 후 설정 |
| 키 없는 원본 저장 | `INGEST_LOCAL_ROOT` | 기본 `.local/ingest`; R2 변수가 모두 없을 때 사용 |
| CLI 원격 배포 | `SUPABASE_PROJECT_REF`, `SUPABASE_ACCESS_TOKEN` | 원격 배포를 수행할 때 |

소스별 URL도 환경변수로 관리하며 정확한 이름과 값은 소스 확정 시 `.env.example`에 추가한다. 임대동향 API의 인증 방식은 확인 후 필요한 변수만 추가한다. 키가 없는 소스는 실응답 검증 완료로 표시하지 않는다.

## 2. 소스별 명세

### 2.1 생활인구 (유동 축)

- 소스: 서울 열린데이터광장 "집계구 단위 서울 생활인구(내국인)" OA-14979 / "행정동 단위" OA-14991
- 형태: **파일 다운로드가 기본.** OpenAPI·Sheet는 집계구는 5일 전 당일자료만, 행정동은 최근 2개월만 제공한다. 과거 이력은 월별 zip(예: `LOCAL_PEOPLE_20260509.zip`)을 받아 적재한다.
- 단위: 집계구(통계청 2016년 기준 코드), 시간대(0~23), 연령대·성별 컬럼
- 주의: 3명 이하는 `*` 처리 → NULL로 적재. 집계구 경계 shapefile은 열린데이터광장 "서울 생활인구 > 행정구역 코드정보"에서 별도 수령(EPSG 확인 필요).
- 적재 범위: 서울 전체, 최근 3개월 평일·주말 구분 평균. 집계구 × 평일/주말 × 시간대 24개 × 연령대별로 저장한다.
- 반경 집계: 집계구 폴리곤과 요청 반경 원의 **면적 비례 배분**을 적용하고 `estimated=true`를 반환한다. 면적은 EPSG:5186에서 계산한다.
- 골든타임은 **[15:00, 22:00)**, 즉 시간대 15~21이다. RPC는 `weekday`와 `weekend`를 각각 반환한다. 평일·주말 종합값·비율은 S1 계약에 포함하지 않으며 종합 방식은 S2에서 정한다.
- 테이블: `living_pop(tot_reg_cd, dow_type, hour, age_band, avg_pop)` + `census_blocks(tot_reg_cd, geom)`

### 2.2 대중교통 (교통 축)

- 지하철: "서울시 지하철 호선별 역별 시간대별 승하차 인원 정보" OA-12252. 매월 5일 전월 갱신. 1~9호선 서울 관할만 포함. **신분당선은 열린데이터광장이 제공하지 않음(FAQ 명시).** 서울 내 신분당선 역(강남·신논현·논현·신사)은 모두 환승역이라 타 노선 데이터로 커버된다. 경기권 확장 시 대안: (1) 교통카드 빅데이터 통합정보시스템(STCIS, 한국교통안전공단) 신청 — 확인 필요, (2) 역세권 집계구 생활인구로 대체 추정 `estimated=true`, (3) 철도통계연보 연간 승하차(보조).
- 버스: "서울시 버스노선별 정류장별 시간대별 승하차 인원 정보"(OA-12912 계열, 정확한 OA 번호 확인 필요). 정류장 좌표는 "서울시 버스정류소 위치정보"와 조인.
- 역 좌표: "서울시 지하철역 좌표" 또는 역명 매칭. 역명 표기 불일치(괄호 부기 등) 정규화 필요.
- 테이블: `transit_stops(id, type, name, geom)`, `transit_boardings(stop_id, hour, boarding, alighting)`
- S1은 서울 전체를 적재한다. 정류장 개수·승하차 집계의 공간 범위는 요청 `radius_m`이며 고정 300m 범위를 사용하지 않는다. 골든타임은 [15:00, 22:00)이다.
- 최근접 지하철역만 요청 반경 밖에서도 조회하되 후보 좌표로부터 최대 2,000m로 제한하고, 없으면 `nearest_subway_m=null`을 반환한다. 승하차의 원천 단위·기간은 실제 응답으로 확인하고 출처 메타데이터에 기록한다.

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
- 필터: 등록상태 = 개원 중. S1은 서울 전체를 적재하고 요청 `radius_m` 안의 `academies_total`과 `academies_by_field`(원천 분야명별 개수 map)를 반환한다. 국어·논술 등 과목 기준과 클러스터 판정은 S2 `scoring-spec.md`에서 정하며 S1에서 과정명으로 추측하지 않는다.
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
- 공동주택 세대수·국토부 공동주택 단지정보는 **v2**로 이관하며 S1 수요 집계와 적재에 포함하지 않는다.

### 2.7 건축물 (가시성 축, 건물 적합성 축)

- 소스: 국토교통부 건축HUB 건축물대장정보 서비스(공공데이터포털 15134735). 오퍼레이션: 표제부(`getBrTitleInfo`), 층별개요(`getBrFlrOulnInfo`), 총괄표제부. 요청 파라미터는 시군구코드+법정동코드+번·지 (지번 기반). `_type=json` 지원.
- 필요 컬럼: 표제부 — 건물명, 지상층수, 지하층수, 높이(`heit`, 결측 잦음), 주용도, 연면적, 승강기수(승용·비상용), 사용승인일. 층별개요 — 층번호, 층 용도(`mainPurpsCdNm`), 층 면적.
- 주의: 2024년 건축HUB 전환으로 PK(관리번호) 체계가 바뀌었다. 첨부된 PK 전환 규칙 문서를 참고. 지번 단위 호출이라 반경 조회는 불가 → **건물 footprint를 먼저 확보하고, footprint의 지번(PNU)으로 대장을 조회하는 순서**로 간다.
- 건물 footprint 후보(확인 필요, 하나 선택): (a) 도로명주소 건물DB(juso.go.kr, 건물 폴리곤 + 층수), (b) Vworld 2D 건물 레이어, (c) 국토지리정보원 연속수치지형도 건물, (d) OSM 건물(서울 도심은 커버리지 양호, 높이는 대부분 없음). S1에서 강남구 한 곳으로 (a)와 (d)를 비교해 결정한다.
- 적재 범위: S1은 강남구의 footprint·건축물대장·층별개요. 서울 전체 건축물 적재는 S2 초반 별도 태스크다.
- 높이 추정: `heit` 결측 시 `지상층수 × 3.3m`. 단, **1층 단층 상업건물**은 건물 높이 **4.0m**로 추정한다. 다층 건물의 1층에 4.0m 규칙을 적용하지 않는다. `estimated=true`와 높이의 `height_estimated=true`를 남긴다.
- S1은 층별 용도·면적·승강기 등 사실을 제공한다. `academy_eligible`(학원 등록 가능성)은 S2 채점 명세에서 정의하며 S1 응답에 넣지 않는다.
- 테이블: `buildings(id, pnu, name, geom, floors_above, floors_below, height_m, height_estimated, main_use, elevators, gross_area)`, `building_floors(building_id, floor_no, use_code, use_name, area)`

### 2.8 지오코딩

- 1순위 Kakao Local API `v2/local/search/address.json` (도로명·지번 모두, 일 쿼터 확인). 2순위 Vworld 지오코더.
- 결과는 `geocode_cache(address, lat, lng, provider, fetched_at)`에 캐시. 같은 주소 재호출 금지.
- S1은 배치·캐시 구축까지다. 후보지 등록 화면의 주소·건물 캐시 미스 사용자 흐름은 S3 `screens.md`에서 정한다. 프론트·Edge Function이 캐시 미스를 이유로 외부 API를 직접 호출하지 않는다.

### 2.9 상업용 부동산 매매 실거래 (임대료 효율 축)

- 소스: 국토교통부 상업업무용 부동산 매매 실거래가 자료(공공데이터포털 15126463). 파라미터 `LAWD_CD`(법정동 5자리, 예 강남구 11680), `DEAL_YMD`(계약년월). XML.
- 컬럼: 시군구, 법정동, 건물명, 층, 전용면적(또는 건물면적), 거래금액, 건축년도, 용도지역, 계약일. 좌표 없음 → 법정동+건물명+지번으로 지오코딩(정확도 낮음, 동 단위 집계로만 사용).
- 적재 범위: 최근 24개월, **강남구(LAWD_CD=11680) 한정**.
- 원본: 개별 거래의 법정동·건물명·층·면적·가격·계약일 등을 `raw/commercial_trades/{YYYY-MM}.parquet`에 보존한다. Supabase에는 개별 거래 테이블을 만들지 않는다.
- 파생: DuckDB에서 법정동 단위 ㎡당 매매 단가 중앙값과 층별 중앙값을 계산한다. 기간 전체 원본으로 계산하며 월별 중앙값들의 중앙값으로 대체하지 않는다. 원천 금액·면적 단위, 취소 거래·중복 처리, 법정동 연결은 실제 응답으로 확인한다.
- Supabase 집계 테이블: `commercial_trade_stats(lawd_cd, dong, floor nullable, period_start, period_end, median_price_per_m2, sample_count)`. 층 미지정 전체 통계와 층별 통계의 식별 제약은 스키마에서 명시한다. 공통 출처·기준일·적재일·추정 여부를 포함한다.
- 좌표를 법정동에 연결해 통계를 제공하며 반경 내 개별 거래 통계로 표현하지 않는다. 정확한 연결 자료가 없으면 결측이다.

### 2.10 상업용 임대 동향 (임대료 효율 축)

- 소스: 한국부동산원 부동산통계정보 R-ONE(r-one.co.kr) 상업용부동산 임대동향조사 — 분기별, 상권 단위 임대료(㎡당)·공실률·투자수익률. OpenAPI 제공 여부와 상권 단위 코드 체계 확인 필요. 없으면 분기별 엑셀 수동 적재.
- 용도: 사용자가 임대료를 입력하지 않았을 때 대체값, 그리고 "상권 평균 대비" 비교.
- 테이블: `rent_survey(district_code, district_name, quarter, building_class, rent_per_m2, vacancy_rate)`
- S1은 강남구 대상 상권 자료를 적재한다. 후보 좌표와 임대동향 상권의 연결 자료·코드 체계는 실제 자료로 확인한다. 연결 자료가 없으면 임대료·공실률을 결측으로 반환하며 **임의 근접 상권 대체는 금지**한다.

### 2.11 사용자 입력 (임대료 효율 축)

- 후보지 등록 시 선택 입력: 보증금, 월세, 관리비, 전용면적. 저장은 `candidates` 테이블 컬럼으로.
- 이 값은 사용자 소유 데이터이므로 다른 사용자 집계에 쓰지 않는다.

## 3. 반경 집계 RPC 입출력 (S1 완료 기준)

`score_inputs(lat float, lng float, radius_m int, floor int)` → JSON

S1 계약은 **7개 데이터 묶음** `demand`, `flow`, `transit`, `market`, `compete`, `building`, `rent`와 `meta`다. 최종 점수 축의 개수를 뜻하지 않으며 정규화·가중치·과목 기준·등록 가능성 판정은 S2에서 정의한다.

아래는 필드 구조 예시이며 실제 API 응답이나 관측 수치가 아니다. `hourly`는 0~23시 순서로 24개 값을 갖고, `null`은 결측을 뜻한다.

```json
{
  "demand": {
    "pop_5_9": null, "pop_10_14": null, "pop_15_18": null,
    "schools": {"elem": null, "mid": null, "high": null},
    "estimated": true
  },
  "flow": {
    "weekday": {
      "golden_avg_pop": null,
      "hourly": [null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null]
    },
    "weekend": {
      "golden_avg_pop": null,
      "hourly": [null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null]
    },
    "estimated": true
  },
  "transit": {"nearest_subway_m": null, "subway_boardings_golden": null, "bus_stops": null},
  "market": {"stores_total": null, "stores_by_lcls": null},
  "compete": {"academies_total": null, "academies_by_field": null},
  "building": {"floors_above": null, "height_m": null, "height_estimated": null, "floor_use": null, "elevators": null},
  "rent": {"trade_median_per_m2": null, "survey_rent_per_m2": null, "survey_vacancy": null},
  "meta": {"radius_m": 500, "sources": {}, "computed_at": null}
}
```

### 3.1 집계 규칙

- 모든 개수 지표(학교·상가·학원·분야별 학원·버스정류장)는 요청 `radius_m` 기준이다. `academies_total`은 개원 중 학원·교습소 수, `academies_by_field`는 원천 분야명별 개수 map이다. 예를 들어 적재·분류가 확인된 경우 `{"보습": 3, "외국어": 2}`처럼 반환하며, 미적재를 빈 map으로 위장하지 않는다.
- 최근접 지하철역만 요청 반경 밖에서도 찾되 상한 2,000m, 없으면 `null`이다. 골든타임 지하철 승하차의 공간 범위는 요청 반경을 따른다.
- 인구는 행정동, 생활인구는 집계구와 반경 원의 면적 비례 배분으로 추정하고 `estimated=true`를 남긴다. 생활인구는 `weekday`/`weekend`를 분리하고 골든타임 [15:00, 22:00)을 적용한다. S1에서 평일·주말 종합값을 계산하지 않는다.
- `building`은 후보 좌표와 요청 층의 원천 사실이며 `academy_eligible`은 제외한다. 높이 추정은 2.7절을 따른다.
- `rent`의 매매 통계는 후보 좌표가 속한 법정동·층별 집계다. 임대동향은 연결이 확인된 조사 상권 자료만 사용한다. 개인 임대료를 조회하거나 다른 사용자의 집계에 섞지 않는다.
- `meta.sources`에는 소스별 기준일·적재 시각·적재 범위·결측 사유를 기록한다. 실제 관측 범위에서 대상이 없으면 0, 미적재·매핑 실패·비공개 값은 `null`로 구분한다. 지오코딩 실패 등의 누락은 집계 범위의 한계로 명시한다.
- 가시성 축은 클라이언트(Web Worker)에서 계산하므로 이 RPC에 포함하지 않는다. 별도 엔드포인트 `buildings_in_radius`는 반경 1km 내 `buildings` geom+height와 높이 추정 여부·실제 적재 범위를 내려준다. S1 건물 적재 범위는 강남구다.

### 3.2 S1 검증 기준

- 데이터 범위: 인구·생활인구·교통·상가·학원·학교는 서울 전체, 건축물·실거래·임대동향은 강남구. 이 범위의 **실제 데이터**로 성능을 판정하며 빈 DB나 fixture 테스트로 대체하지 않는다.
- 대치동 내 확인된 좌표 3건을 고정하고 반경 500m·1km 각각에서 `score_inputs`를 반복 측정한다. **각 좌표·반경 조합의 DB 실행 시간 p95 < 1,000ms**를 충족해야 한다.
- HTTP 왕복 시간은 별도 기록만 하며 성능 합격 기준으로 사용하지 않는다. DB 환경·데이터 기준일과 건수·준비 호출 여부·반복 횟수·측정 방식을 함께 기록한다.
- `pnpm lint`, `pnpm typecheck`, `pnpm test` 통과와 실제 DB 통합·성능 검증이 모두 필요하다. 키나 데이터 부족으로 미실행한 검사를 통과로 표시하지 않는다.

## 4. 갱신 주기

| 데이터             | 주기                                       | 방식                              |
| ------------------ | ------------------------------------------ | --------------------------------- |
| 생활인구           | 월 1회                                     | 파일 다운로드 → 적재 스크립트     |
| 지하철·버스 승하차 | 월 1회(매월 5일 이후)                      | API 또는 파일                     |
| 상가정보           | 분기 1회                                   | CSV 전체 교체                     |
| 학원·교습소, 학교  | 월 1회                                     | API → upsert + 신규 주소 지오코딩 |
| 주민등록 인구      | 월 1회                                     | 파일                              |
| 건축물대장         | S1 강남구 초기 적재 + 월 1회 캐시 갱신 | Python 배치 API. 캐시 미스 사용자 흐름은 S3에서 정의 |
| 실거래가           | 월 1회                                     | API                               |
| 임대동향           | 분기 1회                                   | 파일 또는 API                     |

GitHub Actions 스케줄로 Python 배치와 DuckDB 집계를 실행한다. `pg_cron`으로 외부 API를 호출하지 않는다. 원격 환경 준비 전에는 로컬에서 같은 배치를 검증한다.

## 5. 라이선스

열린데이터광장·공공데이터포털 데이터는 대부분 공공누리 1유형(출처표시, 상업적 이용 가능). 화면 하단에 출처 표기 영역을 둔다. Kakao Local API는 약관상 결과 캐싱 기간 제한이 있을 수 있으니 확인 필요.

## 변경 이력

| 날짜       | 버전 | 내용                                                                                  |
| ---------- | ---- | ------------------------------------------------------------------------------------- |
| 2026-09-16 | v1   | 최초 작성. 건물 footprint 소스, 임대동향 API, 주민등록 인구 API 경로는 확인 필요 상태 |
| 2026-09-16 | v1.1 | PR 0 사용자 승인: 단계적 적재, Python·GitHub Actions, R2 원본/DB 집계, 7개 묶음 RPC·거리·시간·추정 규칙, DB p95 기준, 환경변수·S2/S3/v2 범위 정리. API 실응답 검증 없음 |
| 2026-09-16 | v1.2 | PR 1 사용자 승인: R2 미설정 시 로컬 파일 폴백, 일부 설정·원격 오류는 실패 처리, 환경변수 예시 추가. 공공 API·R2 실응답 검증 없음 |
