# 길목(GILMOK) 데이터 소스 명세

> 작성일: 2026-09-16 · 버전: v1.6 (PR 2 행정동·주민등록 적재 및 실제 R2 재집계 검증)
> 기준 문서: docs/planning/location-simulator.md
> 목적: S1(데이터 기반) 구현에 필요한 소스별 접근 방법·컬럼·좌표계·적재 방식을 한 곳에 모은다. "확인 필요" 표시는 실제 키 발급 후 응답 스키마로 검증할 것.

## 0. 공통 원칙

- 외부 API는 **배치 적재 스크립트에서만** 호출한다. 프론트와 Edge Function은 Supabase DB만 조회한다.
- 저장 좌표계는 **EPSG:4326**(WGS84)으로 통일한다. 거리 계산은 PostGIS `geography` 타입 또는 `ST_Transform(…, 5186)` 후 `ST_DWithin`을 쓴다. 원천이 EPSG:5179/5181/5186/5174/2097인 파일은 적재 시 변환한다.
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

PR 1에서 `.env.example`을 추가했다. 2026-09-19 이름 대조 결과 누락·추가 이름은 없으며 `SUPABASE_SECRET_KEY`만 비어 있다. `NEIS_API_KEY`는 값이 있지만 호출하지 않았다. 원격 Supabase 인증은 미검증이며 DB 연결은 로컬을 유지한다. 외부 키별 1회 검증 결과는 [PR 2 실측 기록](../validation/pr2-population-20260919.md)을 따른다. 다음 이름을 사용하고, 실제 비밀 값은 사용자가 `.env`에 채운다.

| 목적 | 환경변수 | 필요 조건 |
| --- | --- | --- |
| 건축HUB·상가 검증·실거래 | `DATA_GO_KR_SERVICE_KEY` | 각 서비스 활용승인 필요 |
| 서울 데이터 | `SEOUL_OPEN_DATA_API_KEY` | 인증 API 사용 시 필요 |
| 주소 지오코딩 | `KAKAO_REST_API_KEY` | 1순위 제공자 |
| Vworld 대체 경로 | `VWORLD_API_KEY` | 대체 지오코더·건물 소스를 채택할 때 |
| 나이스 직접 조회 | `NEIS_API_KEY` | 서울 제공 자료 대신 직접 조회할 때 |
| Supabase 배치 DB 직접 연결 | `SUPABASE_DB_URL` | 현재 Python 적재 코드에서 사용. 원격 준비 전 로컬 DB 기본값 사용 |
| Supabase 브라우저·사용자 세션 조회 | `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | 클라이언트 구현 시 사용. Publishable key(`sb_publishable_...`), RLS 적용 |
| Supabase 서버 관리자 API | `SUPABASE_URL`, `SUPABASE_SECRET_KEY` | 관리자 API 구현 시 사용. Secret key(`sb_secret_...`), RLS 우회. 브라우저 노출 금지 |
| R2 | `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` | 사용자가 버킷 준비 후 설정 |
| 키 없는 원본 저장 | `INGEST_LOCAL_ROOT` | 기본 `.local/ingest`; R2 변수가 모두 없을 때 사용 |
| CLI 원격 관리·배포 | `SUPABASE_PROJECT_REF`, `SUPABASE_ACCESS_TOKEN`, `SUPABASE_DB_PASSWORD` | 원격 프로젝트 연결·배포 시 사용. Access Token은 계정 Personal Access Token, DB 비밀번호는 프로젝트별 값 |

Publishable/Secret key는 데이터 API용이며 CLI Access Token이나 DB 비밀번호를 대체하지 않는다. PR 1의 배치와 로컬 테스트는 API 키 없이 실행한다. 기존 `SUPABASE_ANON_KEY`는 새 계약에서 제거하며, 클라이언트에는 레거시 키의 이름만 바꾸지 말고 새 Publishable key를 설정한다. `.env`의 CLI 변수를 명령 환경에 주입하는 방법과 발급 위치는 `docs/development.md`를 따른다. 이 변경은 [Supabase API 키 문서](https://supabase.com/docs/guides/getting-started/api-keys)와 [CLI 배포 문서](https://supabase.com/docs/guides/deployment/managing-environments)에 근거하며 원격 인증 성공을 검증한 것은 아니다.

소스별 URL도 환경변수로 관리하며 정확한 이름과 값은 소스 확정 시 `.env.example`에 추가한다. 임대동향 API의 인증 방식은 확인 후 필요한 변수만 추가한다. 키가 없는 소스는 실응답 검증 완료로 표시하지 않는다.

## 2. 소스별 명세

### 2.1 생활인구 (유동 축)

- 소스: 서울 열린데이터광장 **[내국인 서울생활인구(250m), OA-22784](https://data.seoul.go.kr/dataList/OA-22784/S/1/datasetView.do)**. 기존 집계구 OA-14979는 2026-07-31 이후 생산 종료 공지를 확인했다. S1은 사용자 승인에 따라 250m 격자로 전환한다.
- 형태: 월별 ZIP의 CP949 CSV. 2026-06·07·08월 실제 파일을 모두 확인했다. 7월은 ZIP 안에 월별 디렉터리가 있고 6·8월은 CSV가 루트에 있다. 원본은 `raw/living_population/{YYYY-MM}.parquet`에 컬럼과 `*`를 보존한다. **실제 R2 버킷 게시 완료**. DuckDB/httpfs로 세 객체를 다시 읽은 별도 검증본만으로 재집계한 411,512행을 로컬 폴백과 대조해 불일치 0행을 확인했다. [게시·재검증 기록](../validation/pr2-publication-20260919.md) 참조.
- 실제 컬럼: `일자`(YYYYMMDD), `시간`(00~23), `행정동코드`(공백 제거 후 8자리), `250M격자`(CELL_ID), `생활인구합계`(SPOP), 남녀 각각 14개 연령대. 연령대는 0~9, 10~14, 15~19, 20~24, 25~29, 30~34, 35~39, 40~44, 45~49, 50~54, 55~59, 60~64, 65~69, 70세 이상이다. 세부 비교는 실측 기록 참조.
- 원본의 유일 키는 **일자 × 시간 × 행정동코드 × CELL_ID**다. 한 셀이 행정동별 여러 행으로 나뉘므로 셀·시간만으로 중복 제거하면 안 된다. 먼저 셀의 행정동 조각을 합산한 다음 날짜 평균을 낸다. 전체 인구는 연령대 합계로 재구성하지 않고 SPOP를 쓴다.
- 3명 이하의 `*`는 NULL. 먼저 날짜×셀×시간별로 행정동 조각과 남녀·원천 연령 밴드를 합산한다. 해당 연령대에 필요한 조각 중 하나라도 비공개이면 그 날짜의 연령대 합계를 NULL로 한다. **연령대 평균은 각 컬럼이 유효한 날짜만으로 계산하고, 유효 날짜가 하나도 없을 때만 NULL**이다. 한 날짜의 유효 조각만 부분 합산하거나 모든 연령대에 같은 분모를 적용하지 않는다.
- **허용한 편향:** `*`(3명 이하)인 날짜를 제외하면 연령대 평균이 다소 높아질 수 있으며, 사용자가 이 편향을 반경 집계에서 허용하기로 결정했다. 오차가 반경 전체에서 3명 이내라고 보장하는 것은 아니다.
- `sample_days`는 해당 셀·요일 유형·시간에서 **total(SPOP)의 모든 관측 행정동 조각이 유효한 날짜 수**다. 연령대별 유효 일수의 대체값이 아니며 DB에는 요청대로 이 표본 수 컬럼 하나만 저장한다. `total`은 기존의 완전기간 조건을 유지하여 기간 중 누락·비공개 날짜가 있으면 NULL이다. 미관측 날짜·셀을 0으로 채우지 않는다. 기간 시작·종료일은 출처 메타데이터로 저장한다.
- 요일 컬럼은 없다. 한국 날짜의 월~금을 `weekday`, 토·일을 `weekend`로 파생한다. 공휴일은 별도로 재분류하지 않는다. 시간대 0~23과 골든타임 **[15:00, 22:00)**는 기존 계약과 같다. 평일·주말 종합 방식은 S2에서 정한다.
- 임시 날짜별 Parquet에는 원천에서 제공되는 각 컬럼의 합계와 유효 일수(0/1)를 저장한다. 최종 합칠 때 컬럼별 합계의 합÷유효 일수의 합으로 계산한다. 평균의 평균은 금지하며 최종 DB에는 sample_days 하나만 남긴다.
- 적재 범위: 서울 전체 최근 완료 3개월. 월평균의 평균이 아니라 위 정책에 따라 전체 기간의 컬럼별 합계÷유효 일수를 사용한다. 현재 2026-06-01~08-31 원본 23,344,369행, 관측 셀 8,598개를 확인했다.
- 경계: [공식 생활인구 안내](https://data.seoul.go.kr/dataVisual/seoul/seoulLivingPopulation.do)의 250m SHP `match.shp`를 실제 확인. **EPSG:5179**, 경계 10,125개, 모두 250×250m/62,500㎡다. `CELL_ID=다사XXXXYYYY`의 실측 생성 규칙은 `xmin=900000+int(XXXX)*10`, `ymin=1900000+int(YYYY)*10`, 최대점은 각각 +250m, 중심은 +125m다. 전체 SHP 행에서 ID·중심·경계가 이 규칙과 일치한다. EPSG 투영 파라미터와 격자 원점을 혼동하지 않는다.
- 공식 SHP에 없는 관측 셀 `다사47256125`, `다사67254075`는 위 규칙으로 생성했다. 검증한 `다사` 접두어·250m 정렬·파일 범위를 벗어나면 생성하지 않고 오류로 중단한다. `boundary_generated=true`는 정확한 격자 생성 이력이며 인구 추정 플래그와 구분한다. DB에는 EPSG:4326으로 변환한 10,127개 경계를 저장한다.
- 반경 집계는 격자 폴리곤과 요청 반경 원의 **EPSG:5186 면적 비례 배분**, `estimated=true`다. 주민등록 학령인구 5~9·15~18을 생활인구의 0~9·15~19에서 임의로 나누지 않는다.
- 공간 테이블: `population_cells(resolution_m, cell_id, geom, boundary_generated, source, source_version, ingested_at, estimated)`. PK `(resolution_m, cell_id)`, GiST `(geom)`. 일반 이름 `spatial_unit_id` 대신 원천과 같은 `cell_id`를 사용하고 해상도를 키에 포함한다. 다른 격자 체계가 도입되면 코드 체계 충돌 여부를 별도 검증한다.
- `living_pop`는 **셀×요일 유형×시간당 1행의 고정 컬럼**이다. PK `(resolution_m, cell_id, dow_type, hour)`. 인구 컬럼은 `total`, `age_0_4`, `age_5_9`, `age_10_14`, `age_15_19`, `age_20_29`, `age_30_39`, `age_40_49`, `age_50_59`, `age_60_plus`(모두 nullable double precision), 표본 수는 `sample_days smallint`다. `period_start`, `period_end`와 공통 출처 컬럼을 포함한다. `population_cells` FK와 경계 GiST→생활인구 PK 순서로 조회한다. 인구 테이블에 공간 기하를 중복 저장하지 않는다.
- `age_0_4`, `age_5_9`는 현행 원본의 0~9세를 나눌 수 없으므로 **NULL**이다. 10~14·15~19는 그대로 쓰며 20~29·30~39·40~49·50~59는 각각 두 5세 밴드, 60세 이상은 60~64+65~69+70세 이상을 합산한다. 모든 연령대에서 남녀를 합산한다. raw Parquet에는 원천 연령대·성별·비공개 표시를 모두 유지한다.
- **학원 채점의 생활인구 입력은 15~19세를 그대로 사용한다. 15~18세로 자르거나 비례 추정하지 않는다.** 주민등록 `demand.pop_15_18`은 단일 연령 자료에서 정확히 합산한 별도 지표이며 생활인구에서 재구성하지 않는다. S2 채점 로직은 채점 명세 작성 전 구현하지 않는다.
- JSONB는 채택하지 않는다. 원본 전체 밴드는 R2 Parquet로 보존하고, DB는 고정된 타입의 최소 조회 컬럼만 저장해 키 반복 저장과 JSON 추출·인덱스 관리 복잡도를 피한다. JSONB 자체가 인덱스를 지원하지 않는다는 일반화는 하지 않는다.
- 최초 고정 컬럼 표본 100,000행의 실제 PG 크기(PK 포함)는 24,141,824 byte, 411,512행 예상은 **99,346,503 byte**였다. 모든 인구 값이 비NULL인 보수적 표본은 **117,381,922 byte**로 환산되어 500MB 조건에 따라 구현을 진행했다. 연령대별 유효 날짜 평균으로 변경한 뒤의 전체 적재 실측은 [고정 컬럼 검증 기록](../validation/pr2-living-fixed-20260919.md)을 따른다. 최종 실측은 living_pop+PK 98,787,328 byte, 정리 후 로컬 DB 전체 121,416,851 byte다. 재적재 이전 행 공간을 포함한 DB도 209,202,323 byte로 500MB 이내였다. 24시간과 평일/주말을 유지하며, 요청한 두 축소 대안은 500MB를 넘을 때만 검토한다. 다른 S1 소스까지 모두 적재한 최종 DB 용량·RPC 성능을 확인한 것은 아니다.
- 기존 `census_blocks` 및 기존 마이그레이션은 보존한다. 신규 경계만 추가하므로 롤백 시 기존 경로로 돌아갈 수 있으며, 기존 테이블 삭제나 원격 배포는 하지 않는다.

### 2.2 대중교통 (교통 축)

- 지하철: "서울시 지하철 호선별 역별 시간대별 승하차 인원 정보" OA-12252. 매월 5일 전월 갱신. 1~9호선 서울 관할만 포함. **신분당선은 열린데이터광장이 제공하지 않음(FAQ 명시).** 서울 내 신분당선 역(강남·신논현·논현·신사)은 모두 환승역이라 타 노선 데이터로 커버된다. 경기권 확장 시 대안: (1) 교통카드 빅데이터 통합정보시스템(STCIS, 한국교통안전공단) 신청 — 확인 필요, (2) 역세권 집계구 생활인구로 대체 추정 `estimated=true`, (3) 철도통계연보 연간 승하차(보조).
- 버스: "서울시 버스노선별 정류장별 시간대별 승하차 인원 정보"(OA-12912 계열, 정확한 OA 번호 확인 필요). 정류장 좌표는 "서울시 버스정류소 위치정보"와 조인.
- 역 좌표: "서울시 지하철역 좌표" 또는 역명 매칭. 역명 표기 불일치(괄호 부기 등) 정규화 필요.
- 테이블: `transit_stops(id, type, name, geom)`, `transit_boardings(stop_id, hour, boarding, alighting)`
- S1은 서울 전체를 적재한다. 정류장 개수·승하차 집계의 공간 범위는 요청 `radius_m`이며 고정 300m 범위를 사용하지 않는다. 골든타임은 [15:00, 22:00)이다.
- 최근접 지하철역만 요청 반경 밖에서도 조회하되 후보 좌표로부터 최대 2,000m로 제한하고, 없으면 `nearest_subway_m=null`을 반환한다. 승하차의 원천 단위·기간은 실제 응답으로 확인하고 출처 메타데이터에 기록한다.

### 2.3 상가·상권 (상권 축, 경쟁 축 일부)

- 소스: 소상공인시장진흥공단 상가(상권)정보. 실제 확인한 엔드포인트: `https://apis.data.go.kr/B553077/api/open/sdsc2/storeListInRadius`(반경), HTTP 200 / resultCode 00. 기존 명세의 `/sdsc/`를 수정했다. 건물·지번 오퍼레이션과 페이지 상한은 별도 확인 필요.
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

- 소스: [행정안전부 주민등록 인구통계](https://jumin.mois.go.kr/ageStatMonth.do) 월간 단일 연령 CSV. 2026-08 실제 파일에서 서울 427개 행정동을 확인했다. `행정구역`의 10자리 코드를 확인 후 말미 00을 제거해 8자리로 저장한다. 전국·시·구 합계 행은 제외하고 거주자·거주불명자·재외국민을 포함한 전체 인구의 남녀 합계 5~18세를 사용한다. 단일 연령으로 15~18세를 정확히 합산한다.
- 단위: 행정동. 반경 집계 시 행정동 폴리곤과 반경 원의 **면적 비례 배분**으로 추정하고 `estimated=true`.
- 학원 프리셋용 연령 밴드: 5~9, 10~14, 15~18.
- **최신 경계 확인 완료:** [vuski/admdongkor](https://github.com/vuski/admdongkor)의 `ver20260701/HangJeongDong_ver20260701.geojson`, 커밋 `dd1881663fcabc69b81393604e91ebf3a4202e9a`. SGIS 원자료에 행정구역 변경을 반영한 공개 가공물이며 정부의 최신 원본 파일이라고 표현하지 않는다. CRS84(경도·위도 순서) → DB EPSG:4326. 서울 427개 코드가 2026-08 주민등록 자료와 전부 일치하고 기하도 모두 유효하다. 2025-07-01 용신동→신설동(`11230515`)·용두동(`11230533`) 분동을 반영한다. 경계 임의 분할·보정 없음.
- 원천 `adm_cd`는 SGIS 통계 코드이므로 조인에 사용하지 않는다. `adm_cd2`의 행안부 10자리 코드에서 말미 `00`을 제거한 8자리와 주민등록 코드를 조인한다. 코드 집합 불일치·중복·잘못된 CRS·무효 기하는 적재 오류로 처리한다. 426개 공식 뷰어와 425개 OA-22160 경계는 현재 적재에서 제외했다.
- `population_age(adm_cd, age_band, population, ref_month, source, source_version, ingested_at, estimated)`: 최신 월 스냅샷, PK `(adm_cd, age_band)`, nullable 비음수 integer 인구, 월초 date, `admin_dongs` deferred FK. 반경은 기존 `admin_dongs.geom` GiST→인구 PK로 조회한다. 427개 경계·1,281개 인구 행을 함께 원자적으로 교체하며 실패 시 둘 다 이전 스냅샷과 감사 기록을 보존한다. 공개 API 역할은 읽기만 허용한다.
- 2026-08 전체 서울 합계: 5~9세 **244,007**, 10~14세 **341,692**, 15~18세 **291,292**. 원본 CSV 3,919행(서울 외·합계 포함)은 R2에 그대로 보존하며 DB에는 서울 행정동과 세 밴드만 저장했다.
- [출처 표시](../data-attribution.md): SGIS 공공누리 제1유형 + vuski/admdongkor 가공물 CC BY 4.0. R2 경계 Parquet에도 원래 속성·기하·버전·커밋·출처 표시를 저장한다. 향후 화면·내보내기에도 두 출처를 유지한다.
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
- 인구는 행정동, 생활인구는 250m 격자와 반경 원의 면적 비례 배분으로 추정하고 `estimated=true`를 남긴다. 생활인구는 `weekday`/`weekend`를 분리하고 골든타임 [15:00, 22:00)을 적용한다. S1에서 평일·주말 종합값을 계산하지 않는다.
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

## 6. PR 2 인계 — 다음 세션의 시작점

- 완료: 서울 주민등록 427동×3밴드, 생활인구 관측 8,598셀×요일×시간 411,512행, 격자 경계 10,127개. 생활인구 98.79MB(PK 포함), 주민등록·행정동 추가 직후 DB **122,285,203 byte(122.29MB)**. 경계 524,288 byte, 주민등록 352,256 byte. 전체 S1 용량·RPC p95는 아직 미검증이다.
- 이번 세션의 확정 결정은 **§2.1**에 모두 포함한다: 250m 격자와 `(resolution_m, cell_id)`, 10개 고정 인구 컬럼, `sample_days=total` 유효 일수, 연령별 자기 유효일 평균·전부 결측이면 NULL·상향 편향 허용, JSONB 불채택, 날짜별 합계·일수 분할 집계, 표본 예상과 전체 실측 용량. 메모리 한도와 디스크 임시 경로를 사용하되 전체 날짜 중간 테이블은 실측 OOM이 있어 일별 분할을 유지한다.
- 실제 R2 객체: 생활인구 `raw/living_population/2026-{06,07,08}.parquet`, 주민등록 `raw/resident_population/2026-08.parquet`, 행정동 `raw/admin_boundaries/2026-08.parquet`, 격자 `raw/population_grid/2026-08.parquet`. 총 6개. 경계 키의 월은 함께 보관한 인구 스냅샷 기준월이며 경계 자체의 유효일·다운로드일과 다르다. 원래 격자 10,125개와 생성한 두 셀을 구분한다. 객체별 해시·행 수는 [최종 검증 기록](../validation/pr2-publication-20260919.md)에 있다.
- `RawStore.publish_file`은 기존 R2 객체의 크기·SHA-256 메타데이터가 같으면 재사용하고 다르면 덮어쓰지 않는다. 게시 후 메타데이터 확인에 더해 실제 DuckDB 재읽기로 값을 검증했다. R2 오류 시 로컬 폴백 금지. 생활인구 검증은 R2→DuckDB/httpfs→별도 Parquet→동일 일별 합계·일수 집계 경로이며, 로컬 원본을 원격 검증본으로 대신 쓰지 않는다.
- 재현 진입점: `ingest/publish_population.py`(주민등록·경계 게시/재읽기/로컬 DB 원자 적재), `ingest/verify_population_storage.py`(생활인구 원격/로컬 재집계 비교), `ingest/population_database.py`(격자·생활인구 DB 적재). 명령과 기존 파일 위치는 [개발 문서](../development.md#pr-2-실데이터-재현)를 따른다. 실제 자료와 비밀 값은 Git에 넣지 않는다.
- 새 마이그레이션 `20260919114511_resident_population.sql`만 추가했다. 기존 경계·격자·생활인구 마이그레이션과 census_blocks는 보존한다. 문제 시 새 주민등록 적재·조회 경로를 중지하고 검증된 R2 스냅샷으로 원자 재적재한다. 자동 DROP·원격 적용은 하지 않는다.
- Supabase는 **로컬 기본 유지**. 원격 ref/token/password/publishable key는 있어도 원격 접속·전환은 하지 않았다. 전환이 필요해지면 먼저 사용자에게 알린다. 현재 배치는 직접 DB 연결이므로 비어 있는 `SUPABASE_SECRET_KEY`가 필요하지 않다.
- 다음 PR은 **교통·상가의 서울 전체 적재** 계획부터 낸다. 역·정류장 좌표와 식별키, 시간대 승하차 실제 컬럼·쿼터, 최신 상가 CSV 범위·코드를 먼저 검증한다. 앞선 서울 API 1회 응답은 일별 `CardSubwayStatsNew`였으므로 시간대 자료 검증을 대신하지 않는다. 학원·학교 등 지오코딩 전에 Kakao 403(NotAuthorizedError) 원인을 해결해야 하며 해결된 것으로 간주하지 않는다. NEIS·원격 Supabase 인증은 미검증이다. 이번 PR에서 S2 채점·S3 화면·미정 스케줄을 추가하지 않는다.

## 변경 이력

| 날짜       | 버전 | 내용                                                                                  |
| ---------- | ---- | ------------------------------------------------------------------------------------- |
| 2026-09-16 | v1   | 최초 작성. 건물 footprint 소스, 임대동향 API, 주민등록 인구 API 경로는 확인 필요 상태 |
| 2026-09-16 | v1.1 | PR 0 사용자 승인: 단계적 적재, Python·GitHub Actions, R2 원본/DB 집계, 7개 묶음 RPC·거리·시간·추정 규칙, DB p95 기준, 환경변수·S2/S3/v2 범위 정리. API 실응답 검증 없음 |
| 2026-09-16 | v1.2 | PR 1 사용자 승인: R2 미설정 시 로컬 파일 폴백, 일부 설정·원격 오류는 실패 처리, 환경변수 예시 추가. 공공 API·R2 실응답 검증 없음 |
| 2026-09-19 | v1.3 | Publishable/Secret key, CLI Personal Access Token, DB 비밀번호의 역할 분리. 현재 배치는 DB URL만 사용. 공식 문서 확인, 원격 인증 실검증 없음 |
| 2026-09-19 | v1.4 | PR 2 실파일 검증: 250m 격자·EPSG/생성 규칙·원본 키·연령/요일·실측 건수, 키별 1회 점검, 상가 endpoint 수정. 생활인구 저장 형식과 최신 행정동 경계는 미확정 |
| 2026-09-19 | v1.5 | 사용자 결정: JSONB 대신 고정 연령 컬럼, SPOP 기준 sample_days, 연령대별 유효 날짜 평균과 편향 허용. 15~19 원천 유지, 0~4·5~9 분리 불가로 NULL. 표본 용량 검증 후 로컬 적재 |
| 2026-09-19 | v1.6 | 날짜별 합계·유효 일수 집계 및 98.79MB 실측 확정. 최신 427개 행정동·주민등록 적재, R2 6개 객체 실제 게시·DuckDB 재읽기 및 생활인구 411,512행 대조 완료. 다음 세션 인계 명시 |
