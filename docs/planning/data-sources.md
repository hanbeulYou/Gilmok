# 길목(GILMOK) 데이터 소스 명세

> 작성일: 2026-09-16 · 버전: v1.11 (PR 7 S2 입력 계약·통합 검증, 2026-09-21)
> 기준 문서: docs/planning/location-simulator.md
> 목적: S1(데이터 기반) 구현에 필요한 소스별 접근 방법·컬럼·좌표계·적재 방식을 한 곳에 모은다. "확인 필요" 표시는 실제 키 발급 후 응답 스키마로 검증할 것.

## 0. 공통 원칙

- 외부 API는 **배치 적재 스크립트에서만** 호출한다. 프론트와 Edge Function은 Supabase DB만 조회한다.
- 저장 좌표계는 **EPSG:4326**(WGS84)으로 통일한다. 거리 계산은 PostGIS `geography` 타입 또는 `ST_Transform(…, 5186)` 후 `ST_DWithin`을 쓴다. 원천이 EPSG:5179/5181/5186/5174/2097인 파일은 적재 시 변환한다.
- 모든 적재 데이터에 `source`, `source_version`(데이터 기준일), `ingested_at`을 남긴다. PR 4 사용자 승인에 따라 `stores`만 행별 중복을 피하고 `ingest_private.place_snapshots`에서 스냅샷 단위로 관리한다.
- 결측·추정값은 `estimated boolean` 플래그로 남긴다. 추정 로직은 이 문서에 적는다.
- 로컬 인증키는 `.env`에만 둔다. GitHub Actions에서는 Secrets를 실행 환경에 주입한다. 키 값은 리포지토리·로그에 남기지 않는다. 최초 커밋부터 `.gitignore`의 `.env*`로 제외하고 `!.env.example`만 예외로 둔다.
- **두 층 저장 구조.** 원본은 오브젝트 스토리지(Cloudflare R2, S3 호환)에 `raw/{source}/{YYYY-MM}.parquet`로 쌓고, Supabase에는 조회용 집계와 공간 조회에 필요한 최소 개체 정보(경계·점포·학원·학교·정류장·건물 등)를 둔다. 개별 실거래와 대용량 원본 이력은 R2에만 저장한다. 집계는 `/ingest/aggregate.py`와 `/ingest/sql/*.sql`에서 DuckDB로 R2 Parquet를 직접 읽어 계산한다. 집계 방식이 바뀌면 재다운로드 없이 재집계한다. 로컬 DB에는 500MB 제한을 적용하지 않는다. 원격 Supabase는 S1까지 무료 플랜을 유지하고 S2 서울 전체 건물 적재 시점에 Pro 전환을 검토한다. 이후 PR은 용량을 이유로 데이터 구조·필드·해상도·적재 범위를 바꾸지 않는다. DB·테이블·인덱스·원본·임시 공간의 실측만 기록하며 원격 한도 접근 시 보고한다. 자동 축소·유료 전환은 하지 않는다.
- 배치는 **Python 3.12 + PublicDataReader + DuckDB + psycopg**, 실행 스케줄은 **GitHub Actions**로 통일한다. [PublicDataReader](https://github.com/WooilJeong/PublicDataReader)를 우선 활용하되 현재 API와의 호환성은 소스별 실제 응답으로 확인하고, 미지원 소스도 Python으로 처리한다. 키 신청은 기관별로 따로 해야 한다.
- S1 적재 범위: **인구·생활인구·교통·상가·학원·학교는 서울 전체**, **건축물·실거래·임대동향은 강남구 한정**. 서울 전체 건축물 적재는 S2 초반 별도 태스크로 이관한다. 공동주택 세대수는 **v2(S1 제외)**다.
- 미적재·비공개·매핑 실패는 결측으로 남기고 실제 관측 0과 구분한다. 조회 응답에 소스별 기준일·적재 범위·결측 사유를 남긴다. 단계적 적재 범위 밖의 건물·부동산 자료를 임의 추정값으로 채우지 않는다.
- 원격 Supabase 프로젝트와 R2 버킷은 사용자가 만들고 `.env`에 설정한다. 준비 전에는 `supabase start`로 로컬 Supabase에서 개발하며, R2 실연결 검증은 버킷 준비 후 수행한다.
- PR 1 로컬 폴백: R2 환경변수 4개가 모두 비어 있으면 `INGEST_LOCAL_ROOT`(기본 `.local/ingest`) 아래의 로컬 파일시스템을 사용한다. R2와 같은 `raw/{source}/{YYYY-MM}.parquet` 규칙을 유지하고 DuckDB가 로컬 Parquet를 읽는다. 일부 R2 변수만 설정됐거나 설정된 R2 접근에 실패하면 오류를 보고하며 로컬로 몰래 전환하지 않는다. 키 없는 로컬 검증을 R2 실연결 검증으로 표시하지 않는다.
- 사용자 결정과 실제 응답 검증 결과를 구분한다. 실제 응답으로 확인되지 않은 항목은 계속 "확인 필요"로 남긴다. 실제 확인 결과가 승인된 결정과 충돌하면 해당 구현을 진행하지 말고 먼저 보고한다.

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
- 최초 고정 컬럼 표본 100,000행의 실제 PG 크기(PK 포함)는 24,141,824 byte, 411,512행 예상은 **99,346,503 byte**였다. 모든 인구 값이 비NULL인 보수적 표본은 **117,381,922 byte**로 환산되어 500MB 조건에 따라 구현을 진행했다. 연령대별 유효 날짜 평균으로 변경한 뒤의 전체 적재 실측은 [고정 컬럼 검증 기록](../validation/pr2-living-fixed-20260919.md)을 따른다. 최종 실측은 living_pop+PK 98,787,328 byte, 정리 후 로컬 DB 전체 121,416,851 byte다. 재적재 이전 행 공간을 포함한 DB도 209,202,323 byte로 500MB 이내였다. 위 500MB 비교는 PR 2 당시 검증 이력이다. 2026-09-20 사용자 결정으로 해당 크기를 근거로 한 축소 검토 조건은 폐기했다. 24시간·평일/주말·고정 연령 컬럼을 유지하며 이후 PR은 용량 실측만 기록한다. 다른 S1 소스까지 모두 적재한 최종 DB 용량·RPC 성능을 확인한 것은 아니다.
- 기존 `census_blocks` 및 기존 마이그레이션은 보존한다. 신규 경계만 추가하므로 롤백 시 기존 경로로 돌아갈 수 있으며, 기존 테이블 삭제나 원격 배포는 하지 않는다.

### 2.2 대중교통 (교통 축)

- **PR 3 사용자 승인(2026-09-19, 아래 실응답 검증과 구분):** 생활인구와 같은 최근 완료 3개월인 2026-06~08을 집계한다. 6월로 원천 단위·조인·중복 규칙을 먼저 검증한 뒤 같은 규칙을 7·8월에 적용한다. 조인율은 고정 합격선 없이 실측치·미매칭 목록을 보고하되, 승하차량 기준 조인율이 90% 미만이면 나머지 적재 전에 사용자에게 보고한다. 신분당선 누락을 명시하고 이번 PR에서는 대체 추정하지 않는다. 교통 적재와 조회 검증까지 진행하며 전체 `score_inputs`·S1 전체 p95 판정은 후속 통합 PR에 남긴다.

- 지하철: [OA-12252](https://data.seoul.go.kr/dataList/OA-12252/S/1/datasetView.do), `CardSubwayTime/{start}/{end}/{YYYYMM}`. 실제 6월 응답에는 27개 원천 노선명이 있으며 경부·분당·공항철도·신림선 등도 포함한다. 기존 "1~9호선만" 설명을 실제 응답에 맞게 수정했다. `USE_MM`, `SBWY_ROUT_LN_NM`, `STTN`, `HR_{0..23}_GET_{ON|OFF}_NOPE`, `JOB_YMD`. 역 코드는 없다.
- 버스: 정확한 시간대 소스는 [OA-12913](https://data.seoul.go.kr/dataList/OA-12913/S/1/datasetView.do), `CardBusTimeNew/{start}/{end}/{YYYYMM}`. `USE_YM`, `RTE_NO`, `RTE_NM`, `STOPS_ID`, `STOPS_ARS_NO`, `SBWY_STNS_NM`, 교통수단 코드·명, `REG_YMD`. 시간 컬럼은 `HR_{h}_GET_{ON|OFF}_TNOPE`이며 **1시만 `NOPE`**다. 48개 시간 컬럼 전부 검증한다.
- 위치: 지하철 [OA-21212](https://data.seoul.go.kr/dataList/OA-21212/S/1/datasetView.do)의 `subwayStationMaster` (`BLDN_ID`, `BLDN_NM`, `ROUTE`, `LAT`, `LOT`), 버스 [OA-15067](https://data.seoul.go.kr/dataList/OA-15067/S/1/datasetView.do)의 `busStopLocationXyInfo`를 사용한다. 버스 위치 **`STOPS_NO`가 내부 ID, `NODE_ID`가 ARS 번호**다. 승하차 `STOPS_ID = 위치 STOPS_NO`로 조인하며 ARS 번호를 내부 ID 대신 사용하지 않는다. ID는 선행 0을 보존한 문자열이다.
- 좌표는 실제 API의 경도·위도 도 단위, 검증한 대치동 역 좌표·경계와 일치하는 EPSG:4326이다. 버스 안내 페이지의 "WGS84 (EPSG-5179)"라는 상충 표기를 그대로 코드에 적용하지 않는다. 2026-09-19 조회 위치 784개 지하철 노선별 역·11,236개 버스정류장 중 검증된 서울 427동 경계가 덮는 401개·11,219개를 DB에 저장한다. **6~8월 당시의 위치·개폐 이력은 검증하지 않았다.** 최신 위치를 과거 월과 조인한 한계를 메타데이터에 명시한다.
- 지하철은 노선명과 괄호 부기를 제거한 역명으로 **노선 안에서 유일한 경우만** 조인한다. 원천→위치 노선명 대응은 `9호선2~3단계→9호선(연장)`, `경의선→경의중앙선`, `공항철도 1호선→공항철도1호선`이다. 개명역·누락역을 이름 유사도·근접 좌표로 연결하지 않는다. 환승역의 노선별 ID는 유지하고, 다른 노선 행을 동일 역명만으로 지우거나 복제하지 않는다.
- 버스 원천의 노선·내부 ID가 같아도 정차 순번(이름 말미)·이름 변경·노선명·교통수단별 행은 구별한다. 100번의 개명 구간, 5511번의 반복 정차 구간을 포함하여 일별 30일 합계와 시간대 월 합계가 정류장별로 모두 일치했다. 별도 행은 합산하되 **모든 원천 컬럼이 동일한 복제 행만 제거**한다. 원천 식별 차원이 같은데 수치가 다르면 오류다. 7월 지하철 API 1,242행은 정확한 복제 621행을 포함해 집계에는 621행만 쓴다. 원본 Parquet에는 복제를 보존한다.
- **원천 단위는 시간대별 월 합계**다. 6월 지하철 전체 및 버스 100·5511번의 일별 자료 30일과 승차·하차를 각각 대조해 불일치 0을 확인했다. DB는 정류장·시간별 6~8월 월 합계의 합÷**92일**인 일평균이다. 월별 일평균의 단순 평균은 쓰지 않는다. 월 자료로 평일·주말이나 방학/학기 값을 따로 추정하지 않는다. 승하차는 관측 이벤트 수이며 중복 없는 이용자 수나 환승객 수가 아니다.
- **S2 인계: 교통 축은 요일 구분 없는 일평균, 생활인구는 평일/주말 분리.** 지하철·버스의 6~8월 시간대 원본에는 요일·평일/주말 구분이 없고 기준월만 있다. `JOB_YMD`·`REG_YMD`는 등록일이지 승하차 관측일이 아니다. 따라서 교통 일평균을 평일 또는 주말의 관측값으로 간주하거나 생활인구의 요일별 값과 같은 시간 기준이라고 해석하지 않는다. 이 차이의 채점 반영은 S2 `scoring-spec.md`에서 명시한다.
- 한 월·시간의 구성 행 중 필요한 값이 NULL이면 부분 합계를 만들지 않는다. 세 월 중 하나라도 그 정류장·시간 값이 없으면 해당 3개월 평균은 NULL이다. 유효 월 수 `sample_months`(승차·하차 중 적은 수)를 저장한다. 현재 6개 버스정류장 144행은 1~2개월만 관측되어 평균 NULL이며 나머지 264,552행은 세 월이 유효하다. 원천 관측 0은 보존한다.
- **신분당선 승하차는 누락**이며 0이나 다른 노선·생활인구로 대체하지 않는다. 실제 위치 소스의 서울 신분당선 7개 역에는 양재·양재시민의숲·청계산입구도 포함돼 기존 "서울 내 4개 모두 환승역" 설명을 수정했다. 해당 좌표는 최근접 거리에는 사용하고 승하차는 NULL로 남긴다. 다른 노선의 관측치는 해당 노선 자료로만 사용한다. 김포골드라인·GTX 등의 좌표만 있는 역과 개명 미매칭도 별도 메타데이터로 보존한다.
- 조인율 분모는 **서울 경계 필터 전 전체 원천의 정확한 복제 제거 후 관측**이다. 고유 ID·행·승하차량 기준을 각각 보고한다. 월별 승하차량 조인율: 지하철 **99.7421 / 99.7330 / 99.7074%**, 버스 **95.2379 / 95.3846 / 95.4168%**. 위치가 없으면 서울 안/밖 판정도 불가하므로 서울 밖으로 제외하지 않는다. 매칭된 서울 안·밖과 위치 미확인을 별도로 기록한다. 90% 미만 또는 분모 수치 미확인 시 배치를 중단하고 `coverage.json`·`unmatched.csv`로 먼저 보고한다.
- **버스 누락은 균일하지 않다.** 3개월 합산 미매칭은 41,280,731/886,937,877건(**4.6543%**). 미매칭량의 간선/지선 비중은 **52.85%/38.61%**, 유형 내부 누락률은 서울광역 **49.96%**, 간선 **5.91%**, 지선 **4.71%**, 마을 **0.63%**다. 원천에는 `경기광역` 분류가 없으므로 서울광역을 경기광역으로 바꿔 부르지 않는다. 누락 상위 노선은 군포·성남 등 서울 외 지역을 연결하며, 미매칭량의 **94.62%는 2xx 내부 ID 대역**이다. 이는 위치 소스 범위와 관련된 편중의 근거지만 미매칭 정류장의 실제 위치를 전수 확인한 것은 아니다. 100~124 ID 대역의 잔여 누락에서는 홍대입구·합정 등 마포권 이름의 가상정류장이 두드러진다. 상세 유형·월·노선·ID 구간 분석과 지리 판정 한계는 [버스 편중 분석](../validation/pr3-bus-coverage-20260919.md)을 따른다. S2에서 4.65%가 서울 모든 후보지에 균일하게 빠진다고 가정하거나 일괄 보정하지 않는다.
- 테이블: `transit_stops(id, type, name, line, geom, source, source_version, ingested_at, estimated)`, `transit_boardings(stop_id, hour, boarding, alighting, sample_months, period_start, period_end, unit, source, source_version, ingested_at, estimated)`. PK는 각각 `id`, `(stop_id,hour)`, 위치는 geography GiST로 조회한다. 승하차 단위는 `persons_per_day`, 단순 합산·일수 정규화는 관측 통계로 `estimated=false`다. 원천별 조인·미매칭·좌표만 존재하는 개체는 비공개 `ingest_private.transit_coverage`에 보존한다. 두 테이블·품질 메타데이터·성공 이력은 원자 교체한다. 공개 역할은 읽기만 허용한다.
- 원본: `raw/{subway,bus}_boardings/2026-{06,07,08}.parquet`, `raw/{subway,bus}_stops/2026-09.parquet`의 8개 R2 객체. 위치 키의 월은 조회 월이지 과거 위치 유효월이 아니다. 실제 R2 재읽기와 원본 행의 복제 횟수까지 대조해 불일치 0, 원격 원본만 재집계한 결과도 동일하다. 상세 수치·해시·재현·미매칭 목록 위치는 [PR 3 검증 기록](../validation/pr3-transit-20260919.md)을 따른다.
- PublicDataReader의 현재 `Transportation`은 일별 API만 지원하고, 실제 `지하철승하차` 호출 결과 616행의 6개 컬럼이 모두 빈 문자열이었다(구 컬럼명 파싱). 이번 소스는 Python 표준 HTTP 라이브러리로 실제 새 컬럼을 읽는다. 1,000행 페이지 호출을 검증했고 월별 선언 건수와 수집 건수를 대조한다. 1,001행 요청은 실제 `ERROR-336`으로 거부돼 요청당 최대 1,000건을 확인했다. 계정별 일 쿼터는 응답으로 확인되지 않았으며 임의 수치를 가정하지 않는다.
- S1은 서울 전체를 적재한다. 정류장 개수·승하차 집계의 공간 범위는 요청 `radius_m`이며 고정 300m 범위를 사용하지 않는다. 골든타임은 [15:00, 22:00)이다.
- 최근접 지하철역만 요청 반경 밖에서도 조회하되 후보 좌표로부터 최대 2,000m로 제한하고, 없으면 `nearest_subway_m=null`을 반환한다. 승하차의 원천 단위·기간은 실제 응답으로 확인하고 출처 메타데이터에 기록한다.

### 2.3 상가·상권 (상권 축, 경쟁 축 일부)

- 소스: [소상공인시장진흥공단 상가정보 CSV, 15083033](https://www.data.go.kr/data/15083033/fileData.do). 2026-09-19 확인한 최신 분기는 **2026-06-30 기준**, 게시일 2026-08-05다. ZIP 안 `소상공인시장진흥공단_상가(상권)정보_서울_202606.csv`를 사용한다.
- 실제 서울 **554,092행**, 고유 상가업소번호 554,092개, 전 행 시도코드 `11`. 상권업종 대/중/소 분류는 **10/75/247개**, 코드는 2/4/6자리 문자열이다. `P1 → P105 → P10501`과 별도 표준산업분류 `P85501`을 혼동하지 않는다. 코드·명 원문과 표준산업분류(실측 373개)는 원본에 모두 보존한다.
- **2026-09-20 사용자 승인:** DB `stores`는 `store_id, inds_lcls, inds_mcls, inds_scls, floor, geom` **6개 컬럼만** 둔다. 상호명·주소·표준산업분류는 R2 원본에만 둔다. 행별 `source/source_version/ingested_at/estimated` 중복 대신 `ingest_private.place_snapshots`에서 스냅샷 단위로 관리한다. 이 저장 결정은 API 검증 결과가 아니다.
- 층정보 공란 **177,468행**은 DB NULL로 둔다. 지상 1층으로 추정하지 않는다. 경도·위도 결측·범위 무효는 0건, EPSG:4326으로 보존한다. 서울 범위는 원천 시도코드 `11`이다. 현재 427동 경계 밖 좌표 74행도 원본대로 보존하고 품질 보고서에 기록한다. 주소·좌표를 임의 보정하지 않는다.
- 원본: `raw/stores/2026-06.parquet`(전체 원천 컬럼). 분기 갱신은 완전한 서울 스냅샷으로 reconcile하며 변경 없는 행은 재작성하지 않는다. 새 스냅샷에 없는 업소는 제거한다. 검증 실패 시 이전 스냅샷을 보존한다.
- 이전 실제 API 검증: `https://apis.data.go.kr/B553077/api/open/sdsc2/storeListInRadius`, HTTP 200/resultCode 00. PR 4는 CSV를 사용했으며 건물·지번 오퍼레이션과 API 페이지 상한은 검증하지 않았다.

### 2.4 학원·교습소 (경쟁·클러스터 축)

- 소스: [서울시 학원 교습소정보 OA-20528](https://data.seoul.go.kr/dataList/OA-20528/S/1/datasetView.do), 원천 NEIS. 서비스 `neisAcademyInfo`, 2026-09-19에 1,000행씩 26페이지로 **25,508행** 수집. `PEI_DSGN_NO` 고유값 25,508개. 전체 `REG_STTS_NM=개원`, 학원 15,292·교습소 10,216개다. 폐원·휴원 이력이 포괄된다고 해석하지 않는다.
- 원문 대응: `FLD_NM → field`, `TRNG_AFLT_NM → affiliation`, `TRNG_CRS_LIST_NM → course_list`, `TRNG_CRS_NM → course`. 원문 문자열을 분리·합치거나 과목으로 분류하지 않는다. 특히 `보습·논술`을 국어/논술 학원으로 재분류하지 않는다. 과목 식별과 클러스터 기준은 **S2 scoring-spec.md**에서 정한다.
- 원문 분야 분포: 입시.검정 및 보습 14,143; 예능(대) 6,536; 국제화 1,320; 기예(대) 808; 직업기술 750; 기타(대) 693; 종합(대) 582; 독서실 418; 인문사회(대) 230; 정보 26; 특수교육(대) 1; 빈 문자열 1. 빈 문자열을 다른 분야명으로 바꾸지 않는다.
- 본주소 `ROAD_NM_ADDR`를 지오코딩한다. `DADDR` 및 그 외 원천 컬럼은 R2 원본에 보존한다. `LOAD_DT`는 20231018~20260913으로 행마다 다르므로 조회일을 모든 행의 원천 갱신일로 표시하지 않는다.
- DB는 개원 중인 행만 유지한다. 완전한 후속 스냅샷에서 사라지거나 폐원·휴원된 행이 계속 개원으로 남지 않도록 reconcile한다. 새로운 등록상태 값은 추측하지 않고 적재를 중단한다.
- `academies`에는 ID·이름·기관 구분·등록상태·분야/계열/과정 원문·캐시 조회용 주소·geom·지오코딩 실패/사유/provider·출처 메타데이터를 둔다. 실제 좌표 확보 25,422행, 실패 **86행**. 실패 행도 보존하며 반경 개수에서는 위치가 확인된 행만 센다.
- 원본: `raw/academies/2026-09.parquet`. S1의 `academies_total`은 개원 학원·교습소 개수, `academies_by_field`는 원천 분야명별 map이다. 원문 공란의 key는 빈 문자열이며 전체 개수에서 누락하지 않는다.

### 2.5 학교 (수요 축)

- 소스: [NEIS 학교기본정보](https://open.neis.go.kr/) `schoolInfo`, `ATPT_OFCDC_SC_CODE=B10`. 2026-09-19 실응답 1,415행, 고유 `SD_SCHUL_CODE` 1,415개. 인증 정상. 기존 예시 OA-20561의 `neisSchoolInfoIs`는 특수학교 21행을 반환하므로 초·중·고 전체 소스로 사용하지 않는다.
- `SCHUL_KND_SC_NM`이 정확히 초등학교/중학교/고등학교인 행만 `elem/mid/high`로 대응한다. 각각 **610/390/319개**, 합계 **1,319개**. 다른 학교급 96행은 R2 원본에 보존하며 임의로 세 학교급에 편입하지 않는다. 학생 수는 v2다.
- `ORG_RDNMA` 본주소를 지오코딩한다. DB `schools`에는 ID·이름·원천 학교급·level·주소·geom·실패/사유/provider·출처 메타데이터를 둔다. 좌표 확보 **1,312행**, 실패 **7행**. 원본은 `raw/schools/2026-09.parquet`.
- 학교 범위는 서울 교육청/원천 주소 기준이다. 태강삼육초·한국삼육고는 같은 `서울특별시 노원구 화랑로 815`의 대표 좌표가 현재 행정동 경계 밖에 놓인다. 캠퍼스 대표점과 개별 교문 위치의 일치는 미검증이며 좌표를 임의 이동·보정하지 않는다. 같은 주소의 서로 다른 학교 ID를 중복 제거하지 않는다.

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
- 주의: 건축HUB 전환으로 PK(관리번호) 체계가 바뀌었다. 공식 첨부 문서에서 22자리 신규 PK는 그대로, 구 일련번호는 통합분류코드+대장구분+일련번호로 변환함을 확인했다. 강남구는 `1024`, 실대장은 `1`이며 표본 SHP 70개가 PNU와 변환 PK 모두 일치했다. 폐말소대장(`0`)은 섞지 않는다. 반경 조회 API는 아니지만 **법정동·대지구분만 지정하고 번/지를 생략한 페이지 조회도 실제 확인했다.** footprint를 확보하고 동 단위로 수집한 대장을 PNU/변환 PK로 연결한다. 같은 필지의 다동 표제부를 임의 선택하지 않는다.
- PR 5 footprint 비교 대상은 사용자 결정에 따라 **GIS건물통합정보 SHP(기존 NSDI, 현재 Vworld 파일 배포)·Vworld WFS `lt_c_bldginfo`·OSM**이다. 강남구 전체 도형 수·PNU 보유·높이/층수 보유율과 동일 대치동 표본의 대장 연결률·이용조건을 비교했다. 사용자 최종 승인으로 SHP를 주 소스, WFS는 SHP에 없는 도형의 보조 소스로 확정한다. PNU 100%·대장 연결률 우위·CC BY 배포 조건·주 원본의 API 약관/쿼터 비의존이 선정 근거다. 포털 메타데이터나 WFS 응답을 SHP 실측으로 대신하지 않는다.
- 도로명주소 **건물DB는 TXT 주소·지번 속성 자료**이며 건물 도형/전자지도는 별도 제공 자료다. 사용자는 아직 신청하지 않았으며 위 세 소스가 모두 부족할 때만 신청을 제안한다. 기존 문서의 “건물DB = 건물 폴리곤” 설명을 정정한다. [공식 건물DB 명세](https://www.data.go.kr/data/15050424/fileData.do), [SHP 배포 페이지](https://www.vworld.kr/dtmk/dtmk_ntads_s002.do?svcCde=NA&dsId=18).
- 사전 확인: Vworld WFS는 `domain=http://localhost`로 정상 응답했다. 원천 높이 0은 결측이며 층수 추정과 구분한다. 건축HUB 표제부·층별개요는 `_type=json`을 지원하지만 1,000행 요청에도 응답 페이지는 100행으로 제한됐다. 반환 `numOfRows`·`totalCount`를 기준으로 수집한다. 현행 대장 PK는 표본에서 최대 22자리이므로 문자열로 보존한다. WFS 대장 PK를 현행 PK와 그대로 조인하지 않는다. 상세 수치·접근 제약은 [PR 5 계획](pr5-buildings-plan.md)을 따른다.
- 실제 파일 확인: `.local/downloads/AL_D010_11_20260909.zip`은 서울 전체 DBF 695,754행이다. 압축을 풀지 않고 읽었으며 PRJ는 **EPSG:5186**, 문자 속성은 CP949로 정상 해석했다. `A23='11680'`인 강남구 **28,228행**, PNU 유효 100%, 지상층수>0 **22,241행(78.79%)**, 원천 높이>0 **16,653행(58.99%)**다. 원천 29컬럼·완전 중복 1쌍·self-intersection 4건·비교 결과는 [검증 기록](../validation/pr5-footprints-20260920.md)을 따른다. SHP 중복 제거·수리 후 28,227개를 적재했고 [최종 검증 기록](../validation/pr5-buildings-20260920.md)에 결과를 남겼다.
- 전수 비교: WFS 33,345개, 일반/산 PNU 33,343개, 양수 높이 16,655개, 양수 층수 27,122개다. SHP 고유 GIS ID 28,227개를 모두 포함하며 추가 NN 5,115개 중 4,879개는 층수가 있다. NN을 유일 키로 쓰지 않고 토지구분 6인 PNU 2개는 API 변환 미확정으로 남긴다. OSM은 강남구 경계 내 17,263개, 직접 PNU 태그 0개다. 상세 판정·중복·이용조건은 PR 5 계획과 검증 기록을 따른다.
- SHP 운영은 사용자 결정에 따라 **수동 다운로드 후 R2 raw/에 게시, 갱신 주기 분기**다. 로그인 다운로드를 자동화하지 않는다. 수동 ZIP의 전체 원문 속성·원천 좌표 geometry를 Parquet로 보존하고, ZIP 해시·PRJ·컬럼 정의서·배포/행 기준일을 기록한다. 새 파일 없이 기준일을 새 분기로 올리지 않는다. 2026-09-20 원본 ZIP과 서울 전체 Parquet를 R2에 게시하고 SHA-256/전체 행 재읽기를 검증했다.
- 대장 전수 수집: 14개 법정동·일반/산 21조합에서 표제부 24,324행·층별개요 198,637행을 확보했다. 정상 0건 조합의 첫 페이지를 포함해 성공 페이지는 256/2,001개, 합계 2,257개다(재시도 별도). 계정 잔여 쿼터는 미확인이다. HTTP 503·200 빈 본문은 재시도하며 오류를 정상 0건으로 저장하지 않는다. 65개 오류 기록은 모두 회복했고 성공 캐시 재검증은 추가 API 호출 0건이었다.
- 적재 범위: S1은 강남구의 footprint·건축물대장·층별개요. 서울 전체 건축물 적재는 S2 초반 별도 태스크다.
- 확정 높이: SHP 또는 WFS 도형의 원천 높이>0이면 그대로 사용한다. 없으면 양수 지상층수×3.3m, 원천 주용도 코드 앞 두 자리 `03`(제1종 근린생활시설)·`04`(제2종 근린생활시설)·`07`(판매시설)인 1층 단층 건물은 4.0m다. 그 밖의 코드·용도 미상은 3.3m이며 학원 등록 적합성 분류와 무관하다. 이때 `height_source='floors_estimate'`, `estimated=true`, `height_estimated=true`다. 둘 다 없으면 `height_m=NULL`, `height_source='unknown'`으로 유지하고 3D 표시·차폐 입력에서만 4.0m를 사용한다. 원천 양수 높이는 `height_source='source'`다.
- WFS 보조는 `source`를 구분하고 대장 미연결로 유지하며 건물 적합성·용도·승강기 등 대장 기반 집계에서 제외한다. SHP와 WFS 모두 차폐 대상이며 unknown도 4m로 포함한다. 신뢰도는 차폐 대상 중 unknown 비율(`unknown_ratio`, 대상 0개면 NULL)을 반환한다. PR 5는 RPC 데이터 계약을 제공하고 실제 렌더러·레이캐스트는 S2/S3에서 이를 소비한다.
- SHP 정규화에서 완전 중복 1쌍은 1건으로, 자기 교차 4건은 `ST_MakeValid`로 정리한다. ZIP 원본과 원천 geometry/속성은 R2에 그대로 보존하고 `geometry_repaired`를 기록한다.
- S1은 층별 용도·면적·승강기 등 사실을 제공한다. `academy_eligible`(학원 등록 가능성)은 S2 채점 명세에서 정의하며 S1 응답에 넣지 않는다.
- PR 5 구현 스키마: 도형 `buildings`, 현행 대장 PK(text)의 `building_registers`, 원천 행을 보존하는 `building_floors`와 명시적 연결 관계로 나눈다. 도형·표제부를 일대일로 강제하지 않으며 PK 미연결 도형도 유지한다. 원천 ID·PNU·geometry·높이/층수·용도·출처와 추정/수리/연결 상태를 보존한다. 마이그레이션 `20260920095423_buildings.sql`과 [최종 검증 기록](../validation/pr5-buildings-20260920.md)을 따른다.

- WFS 보조 판정: SHP와 GIS ID가 다른 5,117개를 EPSG:5186에서 대조해 SHP 교차 면적 >0.01㎡인 3,231개와 폴리곤이 아닌 수리 결과 1개를 제외했다. 1,885개만 보조 적재하며 제외 원본·ID·사유를 보존한다. 좌표 단순화는 하지 않는다.
- 전체 건물 30,112개 중 SHP 대장 연결은 19,016/28,227(67.37%)이다. 원천 PK 없음 5,957개·현행 표제부에 변환 PK 없음 3,254개를 유지하며 PNU만으로 임의 연결하지 않는다. 층별개요는 198,571행 연결, 부모 표제부 없는 66행(4개 PK)은 원천 PK·미연결 상태로 보존한다.
- 높이는 원천 16,652개·층수 추정 7,308개·unknown 6,152개다. `buildings_in_radius`는 SHP와 WFS 전체를 차폐 입력에 포함하고 `meta.confidence`에 unknown_count/occluder_count/unknown_ratio를 반환한다. `meta.estimated_buildings`는 층수 추정 수, 개체 `estimated`는 unknown 표시 기본값도 포함한다. 대장 집계는 연결된 SHP의 고유 표제부 PK만 센다. 대치동 3좌표×2반경에서 p95 16.084~157.651ms이며 전체 score_inputs 검증은 아니다.

### 2.8 지오코딩

- 배치에서만 Kakao 주소 검색 `https://dapi.kakao.com/v2/local/search/address.json`을 호출한다. `analyze_type=exact`, 1페이지 최대 30개로 요청하고 유일한 상세 주소만 허용한다. REGION/ROAD 중심점이나 다중 후보를 첫 번째 좌표로 임의 선택하지 않는다.
- 본주소를 NFKC와 공백 정리만으로 정규화한다. 건물번호·도로명·괄호 내용을 추측 변경하지 않는다. 학원 본주소 12,377개 + 학교 1,166개 − 공통 1개 = **13,542개**. 원천 좌표가 있는 상가는 지오코딩하지 않는다.
- 캐시는 기존 `geocode_cache`의 `(address, provider)` PK를 사용한다. 성공과 확정 실패 모두 영속 보관하며 같은 provider에 같은 주소를 재호출하지 않는다. 실패는 `geocode_failed=true`, `geom=NULL`, `failure_reason`으로 보존한다. 다른 기관이 같은 본주소를 사용해도 결과를 공유한다.
- 외부 호출 전 `ingest_private.geocode_requests`에 claim을 커밋한다. 동시 실행은 advisory lock/PK로 중복을 막는다. 타임아웃·중단 후 pending/unknown/blocked 요청은 자동 재시도하지 않는다. 저장된 응답 journal이 있으면 검토 후 API 호출 없이 복구할 수 있다. 401/403/429는 배치 중단 사유이며 주소 실패로 기록하지 않는다.
- 2순위 Vworld `https://api.vworld.kr/req/address`(getcoord, road, EPSG:4326)는 **Kakao NOT_FOUND 주소에만** 각 1회 조회한다. 다중 후보·불완전 주소를 보조 소스로 무리하게 확정하지 않는다. 실제 HTTP 200의 OK/NOT_FOUND 스키마를 확인했다.
- **실응답으로 확인한 주소 보정 위험:** Vworld가 `신반포로 50`을 `신반포로33길 50`으로, `월드컵로7길 27`을 `27-10`으로 반환하는 사례가 있었다. 두 provider 모두 반환 도로명·건물번호·구가 원문과 일치하는지 대조한다. Kakao는 정확한 법정동·지번도 대조하며, 숫자 뒤 `번지` 단위와 공백 차이만 허용한다. 불일치는 실패이며 추정 좌표로 채우지 않는다. 저장 응답 전수 대조에서 Vworld의 잘못 보정된 5개를 제외했다. Kakao의 `145번지`와 `성수동1가 72-64` 2개는 공식 주소 구성요소가 원문과 정확히 일치하여 저장 응답으로 복원했다. 원문과 캐시 키를 변경하거나 API를 재호출하지 않았다.
- 결과: **13,491개 주소 좌표 확보, 51개 실패**. Vworld 보조 경로에서 추가 확보한 주소는 10개다. 기관별로 학원 86행·학교 7행의 위치가 없다. 검증 SQL의 `meta`에 원천 행 수·위치 확보·미확보 개수를 동봉하며 반경 개수는 위치 확보 대상만 센다.
- [Kakao 공식 기본 쿼터](https://developers.kakao.com/docs/ko/getting-started/quota)는 주소 검색 100,000건/일. 예상 최초 대상은 13.542%다. 사용자 활성화 후 실제 1건 HTTP 200을 확인하고 캐시한 뒤 시작했다. 실제 일괄 Kakao 요청 13,541건 + 기존 성공 캐시 1건; Vworld는 보조 27건 + 별도 정상 스키마 점검 1건이다. 앱의 무료 적용·다른 사용처의 잔량과 Vworld 계정 상한은 미확인이다. 실행에서는 로컬 일일 한도 14,000/1,000과 오류 중단을 적용했으며 이를 계정 쿼터 확인 결과로 표현하지 않는다.
- 같은 주소 목록 재실행은 Kakao 캐시 13,542개·Vworld 캐시 27개를 사용하고 **외부 호출 0건**이었다. 상세 응답·실패 목록은 `.local/validation/pr4/`에 있으며 비밀 키/키 포함 URL은 기록하지 않는다. 캐시 최신성 운영 정책의 구체적 TTL은 확인되지 않아 자동 만료·재호출을 임의 구현하지 않는다.
- S1은 배치·캐시 구축까지다. 등록 화면의 캐시 미스 흐름은 S3 `screens.md`에서 정한다. 프론트·Edge Function은 외부 API를 직접 호출하지 않는다.

### 2.9 상업용 부동산 매매 실거래 (임대료 효율 축)

- 소스: 국토교통부 상업업무용 부동산 매매 실거래가 자료(공공데이터포털 15126463). 파라미터 `LAWD_CD`(법정동 5자리, 예 강남구 11680), `DEAL_YMD`(계약년월). XML.
- 실제 응답은 `sggCd`, `sggNm`, `umdNm`, `jibun`, `floor`, `buildingAr`, `plottageAr`, `buildingType`, `dealAmount`, 계약일, `cdealType`, `cdealDay` 등 22필드다. 건물명·좌표·고유 거래 ID·10자리 법정동코드는 없다. 금액은 만원, 건물면적은 ㎡이며 공식 화면은 전용/연면적이다. 일반/집합 모두 원천 명칭 `building_area`를 유지하고 전용면적으로 일괄 해석하지 않는다.
- 적재 범위: 최근 24개월, **강남구(LAWD_CD=11680) 한정**.
- 원본: 전 필드·조회월·페이지·행 순서를 `raw/commercial_trades/{YYYY-MM}.parquet`에 보존한다. 정정본은 `raw/commercial_trades/revisions/{조회일시}/{YYYY-MM}.parquet`와 스냅샷 manifest로 보존한다. Supabase에는 개별 거래 테이블을 만들지 않는다.
- 파생: 일반/집합을 분리한 법정동·층별 원/㎡ 중앙값을 DuckDB에서 기간 전체 원본으로 계산한다. 월별 중앙값들의 중앙값을 쓰지 않는다. 취소(`cdealType=O` 또는 해제일 있음), 지분, 금액/면적 미상·0 이하를 제외하고 사유를 기록한다. 공개 필드가 같은 행도 별개 거래일 수 있어 값만으로 제거하지 않는다. 층 미상은 전체층 집계에만 포함한다.
- 2026-09-20 사용자 승인: `score_inputs`용 기본값은 같은 동·요청 층·기간에서 유효 표본이 많은 유형이다. `trade_building_type`(`general`/`collective`)과 `trade_sample_count`를 반환하며 표본 5건 미만이면 단가 NULL이다. 동률은 집합을 고정 선택해 재현성을 유지한다. 층 지정 시 전체층으로 몰래 대체하지 않는다.
- 집계 키는 법정동 8자리 코드·유형·전체층/층별·기간이다. 중앙값·표본수·층 미상 건수·면적 기준과 출처를 보존한다. 법정동은 Vworld `lt_c_ademd_info`의 `emd_cd`, `emd_kor_nm`을 사용하는 별도 `legal_dongs` 경계로 찾으며 행정동 `admin_dongs`와 직접 조인하지 않는다.
- 좌표를 법정동에 연결해 통계를 제공하며 반경 내 개별 거래 통계로 표현하지 않는다. 정확한 연결 자료가 없으면 결측이다.

### 2.10 상업용 임대 동향 (임대료 효율 축)

- 소스: 한국부동산원 R-ONE `https://www.reb.or.kr/r-one/openapi/`의 `SttsApiTbl.do`, `SttsApiTblItm.do`, `SttsApiTblData.do` 실제 응답을 확인했다. 키는 `RONE_API_KEY`; 무키 5행 샘플을 전체 자료로 적재하지 않는다. 원천 임대료 천원/㎡를 DB 원/㎡로 정규화하고 공실률은 %를 유지한다. 통계표·유형별 코드와 경계는 [PR 6 계획](pr6-rent-plan.md)을 따른다.
- 용도: 사용자가 임대료를 입력하지 않았을 때 대체값, 그리고 "상권 평균 대비" 비교.
- 테이블은 상권/권역 수준, 원천 통계표·분류 코드, 분기, 건물유형, 임대료·공실률과 공간 연결 검증 상태를 보존한다. 같은 상권도 유형별 `CLS_ID`가 다르므로 통계표와 함께 식별한다.
- 2026-09-20 최종 사용자 승인: **검증된 포함 상권 → 공식 정의에 포함되는 권역 → NULL**, `rent_level='district'|'region'|NULL`이다. 자치구(gu) 폴백은 폐기했다. 근접 상권 대체는 금지한다. 한국부동산원 조사개요·공식 통계정보보고서·공식 GIS에서 강남 권역의 포함 자치구 또는 경계를 확인하지 못했으므로 권역 수치는 원천 사실로 보존하되 공간 매핑은 비활성화한다. 정의를 찾기 전 대치동 3곳은 region 값 NULL이 정상이다.
- 같은 `rent_level`에 서로 다른 공간 수준의 수치를 섞지 않는다. 상권 임대료가 NULL이면 권역으로 내려가며, 상권 임대료가 있고 공실률만 없으면 상권 단계와 공실률 NULL을 유지한다. 건물유형별 결과를 보존하며 유형을 지정하지 않은 조회에서 여러 유형이 가능하면 임대료 scalar는 NULL과 `building_class_required`를 반환한다. 한 유형만 가능하면 그 유형을 반환한다.

- PR 6 실제 적재: 매매 24개월 2,092행 중 유효 1,744행을 180개 동·유형·층 집계로 저장했다. R-ONE 8개 표 1,810행 원본에서 34개 조사 집계를 저장했으나 공간 연결 12개는 미검증으로 비활성화했다. 원본·경계/분류 근거 R2 27개 객체 재읽기 불일치 0, DB 집계 전수 차이 0. [PR 6 검증](../validation/pr6-rent-20260920.md)을 따른다. 한티 검증 좌표의 실제 법정동은 도곡동이며 층2 표본1건의 단가는 NULL이다.

### 2.11 사용자 입력 (임대료 효율 축)

- 후보지 등록 시 선택 입력: 보증금, 월세, 관리비, 전용면적. 저장은 `candidates` 테이블 컬럼으로.
- 이 값은 사용자 소유 데이터이므로 다른 사용자 집계에 쓰지 않는다.

## 3. score_inputs — S2 채점 입력 계약 v1.0

`public.score_inputs(lat double precision, lng double precision, radius_m integer, floor integer) → jsonb`. PostgREST는 이름 있는 JSON 인자로 호출한다. 좌표는 EPSG:4326, 반경은 m(1~5,000), 층은 지상 양수/지하 음수(-100~200, 0 제외)이며 네 인자 모두 필수다. NULL·범위 오류는 SQLSTATE 22023으로 거부한다. 내부 `ST_MakePoint`는 lng,lat 순서다.

**이 절이 S2 채점 명세의 입력 계약이다.** 7개 묶음 `demand`, `flow`, `transit`, `market`, `compete`, `building`, `rent`와 `meta`는 항상 존재하는 비NULL 객체다. 한 묶음의 관측 결측은 그 묶음의 값만 NULL로 만들고 다른 묶음을 제거하지 않는다. DB/프로그래밍 오류를 결측으로 삼켜 정상 응답처럼 반환하지는 않는다. 채점·가중치·과목 분류·학원 등록 가능성 판정은 포함하지 않는다.

### 3.1 JSON 타입과 묶음별 전체 필드

`number`는 유한 JSON 숫자, `integer`는 정수 JSON 숫자, `string`은 문자열이다. 아래 경로는 모두 필수이며 NULL 허용과 키 생략은 다르다. 동적 map의 키는 관측된 분류/건물유형만 포함한다. 금액은 DB numeric에서 JSON number로 출력하며 원천·DB 정밀도를 유지한다. JavaScript 소비자는 IEEE-754 표현 오차를 고려한다.

| 경로 | 타입 | NULL | 단위·의미 | 추정 플래그 |
| --- | --- | --- | --- | --- |
| demand.pop_5_9, pop_10_14, pop_15_18 | number | 허용 | 명. 주민등록 연령대별 반경 배분 인구 | demand.estimated=true |
| demand.schools | object | 불가 | 학교급별 관측 개수 | 학교 개수 자체는 비추정 |
| demand.schools.elem, mid, high | integer | 허용 | 개. 초/중/고 요청 반경 내 위치 확인 학교 | 비추정 |
| demand.estimated | boolean | 불가 | 인구에 면적 비례 방식을 적용하는 묶음임을 표시. 학교까지 추정이라는 뜻은 아님 | 항상 true |
| flow.weekday, flow.weekend | object | 불가 | 평일/주말을 별도 유지 | flow.estimated |
| flow.{weekday,weekend}.hourly | array[number 또는 null], 길이 24 | 배열 불가, 원소 허용 | 명. 인덱스 0~23시의 공간 배분 생활인구 | true |
| flow.{weekday,weekend}.golden_avg_pop | number | 허용 | 명. [15:00,22:00) 7개 시간 인구의 평균 | true |
| flow.estimated | boolean | 불가 | 격자 면적 비례 배분 방식 | 항상 true |
| transit.nearest_subway_m | number | 허용 | m. 최대 2,000m 내 최근접 역 거리(역 위치와 같으면 0) | false |
| transit.subway_boardings_golden | number | 허용 | 명/일. 반경 내 지하철 15~21시 승차+하차 일평균 합 | false |
| transit.bus_stops | integer | 허용 | 개. 요청 반경 내 버스정류장 | false |
| transit.subway_units_missing_golden | integer | 불가 | 개. 반경 내 7시간 승하차가 불완전한 지하철 위치 단위. 소스 미적재 시 이 값만으로 완전성을 판정하지 않음 | false |
| transit.estimated | boolean | 불가 | 원천 관측의 집계 | 항상 false |
| market.stores_total | integer | 허용 | 개. 요청 반경 내 업소 | false |
| market.stores_by_lcls | object[string→integer] | 허용 | 원천 대분류 코드별 개수. 적재 확인 후 관측 0개면 {} | false |
| market.estimated | boolean | 불가 | 원천 관측의 집계 | 항상 false |
| compete.academies_total | integer | 허용 | 개. 요청 반경 내 개원 학원·교습소 | false |
| compete.academies_by_field | object[string→integer] | 허용 | 원천 분야명별 개수. 원문 빈 문자열도 유효한 키이며 임의 재분류 없음 | false |
| compete.estimated | boolean | 불가 | 원천 관측의 집계 | 항상 false |
| building.id | string | 허용 | 후보를 포함하는 유일한 footprint ID | 비추정 |
| building.source | string | 허용 | gis_buildings_shp 또는 vworld_wfs_supplement | 비추정 |
| building.register_pk | string | 허용 | 검증된 대장 PK. 22자리도 문자열로 유지 | 비추정 |
| building.floors_above | integer | 허용 | 층. 선택 footprint의 지상층수 | 비추정 |
| building.height_m | number | 허용 | m. 원천 양수 높이 또는 승인된 층수 기반 추정. unknown은 NULL | height_estimated |
| building.height_estimated | boolean | 허용 | 선택 건물이 있으면 true/false, 건물 미매칭/모호하면 NULL | 높이만 표시 |
| building.height_source | string | 허용 | source / floors_estimate / unknown. 후보 미매칭/모호 시 NULL | 근거 구분 |
| building.floor_use | array[FloorUse] | 허용 | 요청 층 원문 용도 목록. 여러 용도/주부속을 보존. 미연결·해당 층 없음은 NULL | 비추정 |
| building.elevators | object | 불가 | 대장 연결 건물 승강기 | 비추정 |
| building.elevators.passenger, emergency | integer | 허용 | 대. 승용/비상용을 구분. 원천 0은 0 | 비추정 |
| building.estimated | boolean | 불가 | 높이 추정 여부. 후보 없음/unknown은 false이며 관측값이 있다는 뜻은 아님 | height_estimated가 true일 때만 true |
| rent.trade_median_per_m2 | number | 허용 | 원/㎡. 법정동·요청 층·24개월에서 선택된 유형의 중앙값, 최소 5건 | false |
| rent.trade_building_type | string | 허용 | general / collective. 표본수가 큰 쪽, 동률 collective | false |
| rent.trade_sample_count | integer | 허용 | 건. 선택 유형의 공개 레코드 수. 5 미만이어도 수 자체는 보존 | false |
| rent.trade_by_building_type | array[TradeType] | 불가 | 같은 동·층의 유형별 집계. 없으면 [] | false |
| rent.survey_rent_per_m2 | number | 허용 | 원/㎡. R-ONE 임대료(원천 천원/㎡×1,000). 면적 기준을 사용자 점포 면적으로 변환하지 않음 | false |
| rent.survey_vacancy | number | 허용 | %. 같은 공간 단계·유형의 공실률 | false |
| rent.rent_level | string | 허용 | district / region. 검증된 포함 상권→공식 정의의 포함 권역→NULL | false |
| rent.survey_building_class | string | 허용 | office / medium_large / small / collective. 통합 RPC에서 여러 유형이 가능하면 scalar와 함께 NULL | false |
| rent.survey_by_building_class | object[string→SurveyType] | 불가 | 적용 가능한 유형별 값. 미검증 공간은 포함하지 않으며 없으면 {} | false |
| rent.estimated | boolean | 불가 | 원천 조사 집계/실거래 집계. 점포별 추정 임대료가 아님 | 항상 false |

중첩 배열·map 값의 **전체** 스키마:

| 객체 | 필드 | 타입·NULL | 단위·의미 |
| --- | --- | --- | --- |
| FloorUse | use_code, use_name, other_use, main_attached_code | 각각 string 또는 null | 원천 용도 코드·명칭·기타 용도·주부속 코드 |
| FloorUse | area_m2 | number 또는 null | ㎡. 원천 층 용도 면적 |
| TradeType | building_type | string, 비NULL | general / collective |
| TradeType | sample_count | integer, 비NULL | 건 |
| TradeType | median_per_m2 | number 또는 null | 원/㎡. 해당 유형 표본도 5건 미만이면 NULL |
| TradeType | area_basis | string, 비NULL | building_area. 전용면적으로 단정하지 않음 |
| TradeType | period_start, period_end | 각각 string, 비NULL | YYYY-MM-DD, 계약일 집계 기간 양 끝 포함 |
| SurveyType | rent_per_m2 | number, 비NULL | 원/㎡. 임대료가 있어 선택된 단계 |
| SurveyType | vacancy_rate | number 또는 null | %. 공실률만 없으면 같은 단계에서 NULL 유지 |
| SurveyType | rent_level | string, 비NULL | district / region |
| SurveyType | area_code | string, 비NULL | 내부 조사 공간 식별자. 법정동/행정동 코드가 아님 |
| SurveyType | quarter | string, 비NULL | YYYY-Q1~Q4 |

### 3.2 meta 전체 스키마

| 경로 | 타입·NULL | 단위·계약 |
| --- | --- | --- |
| meta.schema_version | string, 비NULL | 현재 1.0 |
| meta.radius_m, meta.floor | integer, 비NULL | m / 요청 층. 입력값 그대로 |
| meta.computed_at | string, 비NULL | 시간대 포함 ISO 타임스탬프. DB statement_timestamp |
| meta.sources | object[string→Source], 비NULL | 아래 17개 고정 소스 키 모두 존재 |
| meta.estimated_fields | array[EstimatedField], 비NULL | 실제 비NULL 추정값 경로 목록. 없으면 [] |
| meta.missing_fields | array[MissingField], 비NULL | 7개 데이터 묶음의 NULL leaf 전체 경로와 사유. meta 자체의 NULL은 이 목록에 포함하지 않음 |
| meta.height_quality | object, 비NULL | 요청 반경 내 SHP+WFS 고유 footprint 기준 |
| meta.height_quality.radius_m | integer, 비NULL | m |
| meta.height_quality.total_buildings, unknown_buildings | integer, 비NULL | 개. unknown도 전체 분모에 포함 |
| meta.height_quality.unknown_ratio | number 또는 null | 0~1, unknown/total. total=0이면 NULL |
| meta.legal_dong_code | string 또는 null | 유일하게 포함되는 법정동 8자리 코드. 한티 고정 좌표는 11680118(도곡동) |
| meta.rent_spatial_scope | string, 비NULL | legal_dong_and_survey_area. 반경 거래 통계가 아님 |
| meta.flow_coverage | object, 비NULL | weekday/weekend 각각 아래 Coverage 객체 |
| meta.flow_coverage.{weekday,weekend}.expected_cells | integer, 비NULL | 개. 반경과 양의 면적으로 교차하는 250m 격자 |
| meta.flow_coverage.{weekday,weekend}.valid_cells | array[integer], 비NULL, 길이 24 | 시간별 total이 비NULL인 격자 수. 결측을 0명으로 채운 인구값이 아님 |
| meta.bundle_ms | object, 비NULL | demand/flow/transit/market/compete/building/rent의 7개 고정 키 |
| meta.bundle_ms.{묶음명} | number, 비NULL | ms. clock_timestamp 전후 차이. 해당 묶음 집계·JSON 구성 구간의 경과시간 |
| meta.sources_ms | number, 비NULL | ms. 출처 메타데이터·서울 포함 여부 조회 구간 |
| meta.total_ms | number, 비NULL | ms. 함수 진입부터 최종 meta 구성 직전까지. 공통 도형·결측/추정 목록 구성 포함 |

시간은 요청마다 달라지는 진단값이며 점수·캐시 키에 사용하지 않는다. bundle_ms 합에는 sources_ms와 공통 작업이 빠져 있으므로 total_ms와 같지 않다. total_ms는 EXPLAIN Execution Time이나 HTTP 왕복 시간과 같지 않으며, 성능 완료 판정은 별도로 측정한 DB EXPLAIN p95다. 같은 DB 문장 스냅샷에서 각 묶음을 순서대로 한 행으로 집계하므로 계측을 위해 별도 HTTP/RPC를 호출하지 않는다.

| 객체 | 필드 | 타입·NULL | 의미 |
| --- | --- | --- | --- |
| EstimatedField | path | string, 비NULL | 예: demand.pop_5_9, flow.weekday.hourly[15], building.height_m |
| EstimatedField | method | string, 비NULL | area_proportion_epsg5186 / approved_floor_height |
| MissingField | path | string, 비NULL | 객체는 점 표기, 배열은 0부터 시작하는 [인덱스] |
| MissingField | reason | string, 비NULL | 아래 결측 사유 코드. 같은 사유가 여러 경로에 적용 가능 |
| Source | source, source_version | 각각 string 또는 null | 출처 식별자와 원문 버전. 미적재는 NULL |
| Source | reference_date | string 또는 null | YYYY-MM 또는 YYYY-MM-DD. 의미는 date_kind와 함께 해석 |
| Source | date_kind | string, 비NULL | snapshot / reference_month / boundary_version / period / source_version / retrieved_on / contract_period / quarter / unknown |
| Source | period_start, period_end | 각각 string 또는 null | YYYY-MM-DD. 해당 소스가 기간형일 때 양 끝 포함 |
| Source | quarter | string 또는 null | YYYY-Q1~Q4 |
| Source | ingested_at | string 또는 null | 시간대 포함 ISO 타임스탬프. 기준일과 구분 |
| Source | coverage | string 또는 null | 적재된 원천의 범위 설명. 요청 원 전체의 무결측을 보장하는 플래그가 아님 |
| Source | available | boolean, 비NULL | 소스 적재/메타데이터 존재. 좌표 매칭 성공과는 다름 |
| Source | unlocated_count | integer 또는 null | 학원·학교·상가 스냅샷의 위치 미확보 행수. 집계하지 않는 소스는 NULL |
| Source | limitations | array[string], 비NULL | 부분 관측·이력 미확인·공간 연결 미검증 등 소스 제약. 없으면 [] |

고정 소스 키: `admin_boundaries`, `resident_population`, `population_grid`, `living_population`, `subway_positions`, `bus_positions`, `transit_counts`, `stores`, `academies`, `schools`, `building_shp`, `building_wfs`, `building_registers`, `building_floors`, `legal_boundaries`, `commercial_trades`, `rent_survey`.

현재 결측 사유: `missing_population_or_school_coverage`, `missing_cell_or_hour`, `missing_source_or_station_hours_or_outside_coverage`, `not_loaded_or_outside_coverage`, `no_containing_building`, `ambiguous_containing_building`, `source_or_requested_floor_missing`, `outside_coverage`, `ambiguous_legal_boundary`, `no_samples_for_requested_floor`, `fewer_than_five_samples`, `no_unique_legal_dong`, `no_verified_district_or_region_data`, `building_class_required`, `source_value_missing`.

Source.limitations의 현행 코드: `not_loaded`, `unlocated_records_not_in_spatial_counts`, `boundary_reference_date_not_verified`, `valid_days_mean`, `age_0_4_and_5_9_not_separable`, `historical_positions_unverified`, `daily_mean_without_weekday_split`, `unmatched_units_not_imputed`, `register_unlinked`, `legal_dong_not_radius`, `late_reports_and_cancellations_possible`, `no_verified_spatial_mapping`. 교통 원천의 누락 노선 설명 문자열도 그대로 포함한다. 이를 임대 공간 수준 코드나 점수로 해석하지 않는다.

### 3.3 집계·결측·호환 규칙

- 공통 EPSG:5186 반경 원에 행정동/격자 면적 비례 배분을 적용한다. 필요한 연령·셀·시간 값이 하나라도 없으면 해당 완전 집계값은 NULL이다. 유효 셀만 합산한 부분값을 전체값처럼 제공하지 않는다. 원천 PR 2의 셀별 유효 날짜 평균 정책은 바꾸지 않는다.
- 골든타임은 7시간 값 모두 유효할 때 산술평균이다. 평일·주말을 섞지 않는다. 학령인구 15~18세와 생활인구 15~19세를 임의 변환하지 않는다.
- 학교·상가·학원·버스 개수는 요청 반경이다. 미적재/범위 밖과 관측 0개를 구분한다. 위치 미확보 원천은 공간 개수에서 빠지며 소스별 limitations/unlocated_count로 한계를 표시한다. 해당 숫자는 위치가 확인된 원천의 관측 개수다.
- 최근접 역만 최대 2,000m까지 탐색한다. 지하철 골든타임은 해당 역별 승차·하차 7시간 완전성을 요구한다. 교통은 요일 구분 없는 일평균이고 신분당선 등을 대체 추정하지 않는다.
- 후보 건물은 ST_Covers로 유일한 도형만 선택한다. 최근접/동일 필지 대장으로 대체하지 않는다. 층 용도는 지상/지하 코드와 절대 층번호를 함께 확인한다. unknown 높이의 표시/차폐용 4m를 height_m에 대입하지 않는다.
- 매매는 법정동·요청 층별 일반/집합을 보존하며 다수 표본 유형, 동률 집합을 선택한다. 각 유형도 5건 미만이면 단가는 NULL이다. 층별 자료를 전체층 자료로 대체하지 않는다.
- 임대는 검증된 포함 상권→공식 정의가 확인된 포함 권역→NULL이다. 최신 적재 분기는 공간/NULL 필터 이전에 정하며, 과거 분기나 근접 상권으로 대체하지 않는다. 임대료가 있는 단계의 공실률만 NULL이면 그 단계를 유지한다. 여러 건물유형이 가능할 때 통합 RPC의 scalar는 NULL, 유형별 map은 보존한다.
- 소스별로 집계한 한 행만 최종 JSON에 결합한다. 기존 rent_inputs는 상세 조회와 과거 검증을 위해 병존하고 공통 내부 임대 함수를 사용한다. buildings_in_radius는 geometry·표시/차폐 높이용 별도 RPC로 유지한다.
- score_inputs는 SECURITY INVOKER이며 공개 원천 RLS를 따른다. 출처 조회만 제한된 SECURITY DEFINER helper를 사용하고 비공개 감사 보고서·R2 객체·개인 후보지 정보를 노출하지 않는다. 사용자 임대료는 이 응답과 타 사용자 집계에 포함하지 않는다.

### 3.4 실제 응답 예시 및 S1 검증

아래 예시는 **실제 로컬 적재 데이터에 대한 대치 좌표(37.494612,127.063642), 반경 500m, 2층 응답**이다. 값·NULL·필드 목록을 축약하거나 가상 수치로 바꾸지 않았다. 다른 요청의 computed_at/시간 계측은 달라진다. [동일 응답 JSON](../validation/pr7-score-inputs-example.json), [6조합 검증 기록](../validation/pr7-score-inputs-20260921.md)을 함께 본다.

생활인구의 격자 21개는 행이 있으나 시간별 total 비NULL 격자는 17~20개여서 hourly/golden 값이 NULL이다. 임대동향은 공간 정의 미검증으로 NULL이다. 이를 0·근접 상권·부분 인구 합계로 바꾸지 않는다. 나머지 묶음은 정상 반환된다.

<details>
<summary>실제 응답 전체 JSON</summary>

```json
{
  "flow": {"weekday": {"hourly": [null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null], "golden_avg_pop": null}, "weekend": {"hourly": [null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null], "golden_avg_pop": null}, "estimated": true},
  "meta": {"floor": 2, "sources": {"stores": {"source": "semas_stores", "quarter": null, "coverage": "Seoul", "available": true, "date_kind": "snapshot", "period_end": null, "ingested_at": "2026-09-20T08:22:14.138177+00:00", "limitations": [], "period_start": null, "reference_date": "2026-06", "source_version": "2026-06", "unlocated_count": 0}, "schools": {"source": "neis_schools", "quarter": null, "coverage": "Seoul", "available": true, "date_kind": "snapshot", "period_end": null, "ingested_at": "2026-09-20T08:22:14.138177+00:00", "limitations": ["unlocated_records_not_in_spatial_counts"], "period_start": null, "reference_date": "2026-09-19", "source_version": "2026-09-19", "unlocated_count": 7}, "academies": {"source": "seoul_neis_academies", "quarter": null, "coverage": "Seoul", "available": true, "date_kind": "snapshot", "period_end": null, "ingested_at": "2026-09-20T08:22:14.138177+00:00", "limitations": ["unlocated_records_not_in_spatial_counts"], "period_start": null, "reference_date": "2026-09-19", "source_version": "2026-09-19", "unlocated_count": 86}, "rent_survey": {"source": "R-ONE", "quarter": "2026-Q2", "coverage": "Gangnam-linked survey areas", "available": true, "date_kind": "quarter", "period_end": null, "ingested_at": "2026-09-20T12:11:36.518016+00:00", "limitations": ["no_verified_spatial_mapping"], "period_start": null, "reference_date": null, "source_version": "20260920T120200Z", "unlocated_count": null}, "building_shp": {"source": "gis_buildings_shp", "quarter": null, "coverage": "Gangnam-gu", "available": true, "date_kind": "source_version", "period_end": null, "ingested_at": "2026-09-20T10:33:29.603051+00:00", "limitations": [], "period_start": null, "reference_date": "2026-09-06", "source_version": "2026-09-06", "unlocated_count": null}, "building_wfs": {"source": "vworld_wfs_supplement", "quarter": null, "coverage": "Gangnam-gu", "available": true, "date_kind": "retrieved_on", "period_end": null, "ingested_at": "2026-09-20T10:33:29.603051+00:00", "limitations": ["register_unlinked"], "period_start": null, "reference_date": "2026-09-20", "source_version": "2026-09-20", "unlocated_count": null}, "bus_positions": {"source": "seoul_transit", "quarter": null, "coverage": "Seoul", "available": true, "date_kind": "retrieved_on", "period_end": null, "ingested_at": "2026-09-19T12:38:37.082199+00:00", "limitations": ["historical_positions_unverified"], "period_start": null, "reference_date": "2026-09-19", "source_version": "2026-09-19", "unlocated_count": null}, "transit_counts": {"source": "seoul_subway_boardings", "quarter": null, "coverage": "Seoul", "available": true, "date_kind": "period", "period_end": "2026-08-31", "ingested_at": "2026-09-19T12:38:37.082199+00:00", "limitations": ["daily_mean_without_weekday_split", "unmatched_units_not_imputed"], "period_start": "2026-06-01", "reference_date": null, "source_version": "2026-06-01/2026-08-31", "unlocated_count": null}, "building_floors": {"source": "building_hub_floor", "quarter": null, "coverage": "Gangnam-gu", "available": true, "date_kind": "retrieved_on", "period_end": null, "ingested_at": "2026-09-20T10:33:29.603051+00:00", "limitations": [], "period_start": null, "reference_date": "2026-09-20", "source_version": "2026-09-20", "unlocated_count": null}, "population_grid": {"source": "seoul_living_population_250m", "quarter": null, "coverage": "Seoul", "available": true, "date_kind": "unknown", "period_end": null, "ingested_at": "2026-09-19T10:12:14.655762+00:00", "limitations": ["boundary_reference_date_not_verified"], "period_start": null, "reference_date": null, "source_version": "2026-09-19;raw:2026-06/2026-08", "unlocated_count": null}, "admin_boundaries": {"source": "sgis_admdongkor", "quarter": null, "coverage": "Seoul", "available": true, "date_kind": "boundary_version", "period_end": null, "ingested_at": "2026-09-19T11:48:03.029308+00:00", "limitations": [], "period_start": null, "reference_date": "2026-07-01", "source_version": "2026-07-01", "unlocated_count": null}, "legal_boundaries": {"source": "vworld_lt_c_ademd_info", "quarter": null, "coverage": "Gangnam-gu", "available": true, "date_kind": "retrieved_on", "period_end": null, "ingested_at": "2026-09-20T12:07:27.825784+00:00", "limitations": [], "period_start": null, "reference_date": "2026-09-20", "source_version": "20260920T120200Z", "unlocated_count": null}, "subway_positions": {"source": "seoul_transit", "quarter": null, "coverage": "Seoul", "available": true, "date_kind": "retrieved_on", "period_end": null, "ingested_at": "2026-09-19T12:38:37.082199+00:00", "limitations": ["historical_positions_unverified", "신분당선: 승하차 미제공; 대체 추정 없음"], "period_start": null, "reference_date": "2026-09-19", "source_version": "2026-09-19", "unlocated_count": null}, "commercial_trades": {"source": "molit_commercial_trades", "quarter": null, "coverage": "Gangnam-gu", "available": true, "date_kind": "contract_period", "period_end": "2026-08-31", "ingested_at": "2026-09-20T12:07:27.825784+00:00", "limitations": ["legal_dong_not_radius", "late_reports_and_cancellations_possible"], "period_start": "2024-09-01", "reference_date": null, "source_version": "20260920T120200Z", "unlocated_count": null}, "living_population": {"source": "seoul_living_population_250m", "quarter": null, "coverage": "Seoul", "available": true, "date_kind": "period", "period_end": "2026-08-31", "ingested_at": "2026-09-19T11:24:30.244264+00:00", "limitations": ["valid_days_mean", "age_0_4_and_5_9_not_separable"], "period_start": "2026-06-01", "reference_date": null, "source_version": "2026-06/2026-08", "unlocated_count": null}, "building_registers": {"source": "building_hub_title", "quarter": null, "coverage": "Gangnam-gu", "available": true, "date_kind": "retrieved_on", "period_end": null, "ingested_at": "2026-09-20T10:33:29.603051+00:00", "limitations": [], "period_start": null, "reference_date": "2026-09-20", "source_version": "2026-09-20", "unlocated_count": null}, "resident_population": {"source": "mois_resident_population", "quarter": null, "coverage": "Seoul", "available": true, "date_kind": "reference_month", "period_end": null, "ingested_at": "2026-09-19T11:48:03.029308+00:00", "limitations": [], "period_start": null, "reference_date": "2026-08-01", "source_version": "2026-08", "unlocated_count": null}}, "radius_m": 500, "total_ms": 18.626, "bundle_ms": {"flow": 3.919, "rent": 0.273, "demand": 0.443, "market": 2.836, "compete": 0.87, "transit": 0.275, "building": 5.39}, "sources_ms": 3.91, "computed_at": "2026-09-21T06:12:23.852352+00:00", "flow_coverage": {"weekday": {"valid_cells": [18, 18, 19, 19, 18, 18, 18, 18, 18, 19, 20, 18, 18, 18, 17, 17, 17, 18, 18, 18, 18, 18, 18, 18], "expected_cells": 21}, "weekend": {"valid_cells": [18, 19, 19, 19, 19, 19, 19, 19, 19, 18, 18, 18, 18, 18, 18, 18, 18, 19, 18, 18, 18, 18, 19, 19], "expected_cells": 21}}, "height_quality": {"radius_m": 500, "unknown_ratio": 0.42, "total_buildings": 300, "unknown_buildings": 126}, "missing_fields": [{"path": "building.elevators.emergency", "reason": "source_or_requested_floor_missing"}, {"path": "building.elevators.passenger", "reason": "source_or_requested_floor_missing"}, {"path": "building.floor_use", "reason": "source_or_requested_floor_missing"}, {"path": "building.floors_above", "reason": "source_or_requested_floor_missing"}, {"path": "building.height_m", "reason": "source_or_requested_floor_missing"}, {"path": "building.register_pk", "reason": "source_or_requested_floor_missing"}, {"path": "flow.weekday.golden_avg_pop", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[0]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[1]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[10]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[11]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[12]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[13]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[14]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[15]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[16]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[17]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[18]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[19]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[2]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[20]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[21]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[22]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[23]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[3]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[4]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[5]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[6]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[7]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[8]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekday.hourly[9]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.golden_avg_pop", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[0]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[1]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[10]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[11]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[12]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[13]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[14]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[15]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[16]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[17]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[18]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[19]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[2]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[20]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[21]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[22]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[23]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[3]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[4]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[5]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[6]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[7]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[8]", "reason": "missing_cell_or_hour"}, {"path": "flow.weekend.hourly[9]", "reason": "missing_cell_or_hour"}, {"path": "rent.rent_level", "reason": "no_verified_district_or_region_data"}, {"path": "rent.survey_building_class", "reason": "no_verified_district_or_region_data"}, {"path": "rent.survey_rent_per_m2", "reason": "no_verified_district_or_region_data"}, {"path": "rent.survey_vacancy", "reason": "no_verified_district_or_region_data"}], "schema_version": "1.0", "legal_dong_code": "11680106", "estimated_fields": [{"path": "demand.pop_10_14", "method": "area_proportion_epsg5186"}, {"path": "demand.pop_15_18", "method": "area_proportion_epsg5186"}, {"path": "demand.pop_5_9", "method": "area_proportion_epsg5186"}], "rent_spatial_scope": "legal_dong_and_survey_area"},
  "rent": {"estimated": false, "rent_level": null, "survey_vacancy": null, "survey_rent_per_m2": null, "trade_sample_count": 11, "trade_building_type": "collective", "trade_median_per_m2": 23715087.702951, "survey_building_class": null, "trade_by_building_type": [{"area_basis": "building_area", "period_end": "2026-08-31", "period_start": "2024-09-01", "sample_count": 11, "building_type": "collective", "median_per_m2": 23715087.702951}], "survey_by_building_class": {}},
  "demand": {"pop_5_9": 770.368325549834, "schools": {"mid": 0, "elem": 2, "high": 0}, "estimated": true, "pop_10_14": 1927.69503102372, "pop_15_18": 1544.12863119103},
  "market": {"estimated": false, "stores_total": 822, "stores_by_lcls": {"G2": 160, "I1": 1, "I2": 139, "L1": 70, "M1": 56, "N1": 18, "P1": 216, "Q1": 63, "R1": 34, "S2": 65}},
  "compete": {"estimated": false, "academies_total": 207, "academies_by_field": {"국제화": 8, "독서실": 10, "기예(대)": 1, "기타(대)": 2, "예능(대)": 16, "종합(대)": 10, "입시.검정 및 보습": 160}},
  "transit": {"bus_stops": 15, "estimated": false, "nearest_subway_m": 0, "subway_boardings_golden": 10705.4565217391, "subway_units_missing_golden": 0},
  "building": {"id": "wfs:lt_c_bldginfo.15531428", "source": "vworld_wfs_supplement", "height_m": null, "elevators": {"emergency": null, "passenger": null}, "estimated": false, "floor_use": null, "register_pk": null, "floors_above": null, "height_source": "unknown", "height_estimated": false}
}
```

</details>

S1 완료 기준은 대치·학여울·한티 × 500m/1km × 2층의 각 30회 DB 실행 p95 < 1,000ms다. 각 조합 준비 호출 3회, nearest-rank p95(30개 중 29번째), HTTP 왕복 30회 별도 기록을 따른다. 내부 실행계획과 독립 집계 대조 결과도 검증 문서에 남긴다. 과거 개별 RPC 시간이나 빈 DB fixture의 시간을 전체 RPC 실측으로 대신하지 않는다.

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

아래는 PR 2 종료 당시 기록이다. PR 2는 GitHub #4로 머지됐으며, 교통 완료 후 최신 인계는 §7을 따른다.

- 완료: 서울 주민등록 427동×3밴드, 생활인구 관측 8,598셀×요일×시간 411,512행, 격자 경계 10,127개. 생활인구 98.79MB(PK 포함), 주민등록·행정동 추가 직후 DB **122,285,203 byte(122.29MB)**. 경계 524,288 byte, 주민등록 352,256 byte. 전체 S1 용량·RPC p95는 아직 미검증이다.
- 이번 세션의 확정 결정은 **§2.1**에 모두 포함한다: 250m 격자와 `(resolution_m, cell_id)`, 10개 고정 인구 컬럼, `sample_days=total` 유효 일수, 연령별 자기 유효일 평균·전부 결측이면 NULL·상향 편향 허용, JSONB 불채택, 날짜별 합계·일수 분할 집계, 표본 예상과 전체 실측 용량. 메모리 한도와 디스크 임시 경로를 사용하되 전체 날짜 중간 테이블은 실측 OOM이 있어 일별 분할을 유지한다.
- 실제 R2 객체: 생활인구 `raw/living_population/2026-{06,07,08}.parquet`, 주민등록 `raw/resident_population/2026-08.parquet`, 행정동 `raw/admin_boundaries/2026-08.parquet`, 격자 `raw/population_grid/2026-08.parquet`. 총 6개. 경계 키의 월은 함께 보관한 인구 스냅샷 기준월이며 경계 자체의 유효일·다운로드일과 다르다. 원래 격자 10,125개와 생성한 두 셀을 구분한다. 객체별 해시·행 수는 [최종 검증 기록](../validation/pr2-publication-20260919.md)에 있다.
- `RawStore.publish_file`은 기존 R2 객체의 크기·SHA-256 메타데이터가 같으면 재사용하고 다르면 덮어쓰지 않는다. 게시 후 메타데이터 확인에 더해 실제 DuckDB 재읽기로 값을 검증했다. R2 오류 시 로컬 폴백 금지. 생활인구 검증은 R2→DuckDB/httpfs→별도 Parquet→동일 일별 합계·일수 집계 경로이며, 로컬 원본을 원격 검증본으로 대신 쓰지 않는다.
- 재현 진입점: `ingest/publish_population.py`(주민등록·경계 게시/재읽기/로컬 DB 원자 적재), `ingest/verify_population_storage.py`(생활인구 원격/로컬 재집계 비교), `ingest/population_database.py`(격자·생활인구 DB 적재). 명령과 기존 파일 위치는 [개발 문서](../development.md#pr-2-실데이터-재현)를 따른다. 실제 자료와 비밀 값은 Git에 넣지 않는다.
- 새 마이그레이션 `20260919114511_resident_population.sql`만 추가했다. 기존 경계·격자·생활인구 마이그레이션과 census_blocks는 보존한다. 문제 시 새 주민등록 적재·조회 경로를 중지하고 검증된 R2 스냅샷으로 원자 재적재한다. 자동 DROP·원격 적용은 하지 않는다.
- Supabase는 **로컬 기본 유지**. 원격 ref/token/password/publishable key는 있어도 원격 접속·전환은 하지 않았다. 전환이 필요해지면 먼저 사용자에게 알린다. 현재 배치는 직접 DB 연결이므로 비어 있는 `SUPABASE_SECRET_KEY`가 필요하지 않다.
- 다음 PR은 **교통·상가의 서울 전체 적재** 계획부터 낸다. 역·정류장 좌표와 식별키, 시간대 승하차 실제 컬럼·쿼터, 최신 상가 CSV 범위·코드를 먼저 검증한다. 앞선 서울 API 1회 응답은 일별 `CardSubwayStatsNew`였으므로 시간대 자료 검증을 대신하지 않는다. 학원·학교 등 지오코딩 전에 Kakao 403(NotAuthorizedError) 원인을 해결해야 하며 해결된 것으로 간주하지 않는다. NEIS·원격 Supabase 인증은 미검증이다. 이번 PR에서 S2 채점·S3 화면·미정 스케줄을 추가하지 않는다.

## 7. PR 3 인계 — 교통 완료 후

- **게시 완료:** [PR 3 / GitHub #5](https://github.com/hanbeulYou/Gilmok/pull/5), 리뷰 대기·미머지. head `s1/지하철-버스` → base `s1/supabase-인증키`(PR 2 GitHub #4 머지 포함). 문서 커밋 `b709e4f`, 구현 커밋 `9402a6f`이며 게시 후 인계 갱신은 별도 문서 커밋이다. 로컬 lint·typecheck·test·test:db 모두 통과, 테스트 총 118개. GitHub CI·리뷰 최신 상태는 PR에서 확인한다.
- 사용자 승인 범위와 실측 계약은 §2.2, 재현 명령은 [개발 문서](../development.md#pr-3-교통-실데이터-재현), 증거는 [PR 3 검증 기록](../validation/pr3-transit-20260919.md)에 있다. 스크립트는 이번 검증 기간(2026-06~08)에 고정되어 있으며 월별 스케줄은 추가하지 않았다.
- 기존 인구 데이터를 보존한 채 서울 역·정류장 11,620개, 시간대 평균 264,696행을 추가했다. 교통 신규 R2 객체는 8개다. 정류장 개수는 위치 소스 기준이며 승하차 부재 정류장을 0명으로 만들지 않는다. 미매칭 전체 목록은 재현 디렉터리의 `unmatched.csv`, 월별 분모·분자와 위치 미확인 한계는 `coverage.json`·`report.json` 및 DB의 `ingest_private.transit_coverage`에 남는다.
- 위치 API는 9월 조회본이며 역명 개명·내부 ID 누락을 억지 매칭하지 않았다. 특히 서울 자양역의 구명 뚝섬유원지, 경원선 창동 등은 미매칭으로 남는다. 버스 위치 미매칭에는 서울 밖 노선 정류장 등이 섞일 수 있지만 위치가 없으므로 전부 서울 밖이라고 단정하지 않는다. 역사적 위치 정합성은 후속 확인 사항이다.
- 신규 마이그레이션은 `20260919122817_transit.sql`이며 기존 마이그레이션은 수정하지 않았다. 오류 시 교통 배치를 중단하고 검증된 원본으로 원자 재적재한다. 기존 인구 테이블·원격 Supabase에는 변경이 없다. 새 기능·스케줄·지오코딩 폴백은 추가하지 않았다.
- 대치·학여울·한티 위치에서 교통 SQL 500m·1km 검증을 수행했다. 이는 **전체 `score_inputs` 성능 검증이 아니다**. 전체 RPC·HTTP는 미구현이며 S1 전체 완료 기준은 남아 있다.
- 다음 PR: 상가 서울 전체 적재. 최신 분기 CSV의 범위·분류 코드·좌표·건수부터 확인한다. Kakao 403 원인·NEIS 인증·원격 Supabase 전환은 여전히 해결/검증되지 않았다.
- **PR 4는 새 세션에서 시작한다.** 먼저 GitHub #5의 리뷰·머지 여부와 기준 브랜치를 확인하고 상가 서울 전체 적재 계획을 제시한다. S2에는 교통의 요일 미분리 일평균과 생활인구의 평일/주말 분리, 버스 누락의 유형·ID 구간 편중을 함께 인계한다. 이번 PR에서 누락 보정·신규 좌표 소스·S2 채점·PR 4 구현은 시작하지 않았다.

## 8. PR 4 인계

- PR 1~3은 통합 PR [#6](https://github.com/hanbeulYou/Gilmok/pull/6)으로 main에 반영됐다. 사용자 요청으로 기존 `s1/supabase-인증키`는 원격·로컬에서 삭제했다. PR 4는 최신 main에서 `s1/상가-학원-학교`로 진행한다.
- 사용자 승인으로 **로컬에서만 VACUUM FULL 1회** 실행: 기존 DB 224,496,787 → 171,467,279 byte, 기존 인구·교통 행 수 불변. 이를 추가 용량의 기준으로 사용한다. 원격 VACUUM·원격 Supabase 전환은 하지 않았다.
- 상가 6컬럼·기관 원문 보존·성공/실패 캐시·원자 reconcile·R2 3객체 재읽기 대조·대치동 6조합 검증을 완료했다. 실제 수치와 트랜잭션 임시 공간/커밋 후 용량의 구분은 [PR 4 검증 기록](../validation/pr4-places-20260920.md)을 따른다.
- 설치된 PublicDataReader 1.1.0의 공개 Seoul 모듈은 교통만 노출한다. 학원·학교는 확인한 실제 HTTP 스키마 어댑터를 사용했으며 새 라이브러리를 추가하지 않았다.
- 전체 `score_inputs`·HTTP·S1 전체 성능 통과는 아직 아니다. 다음 태스크는 강남구 건축물/건축물대장 적재 계획이며 footprint 소스와 실제 응답을 먼저 확인한다. 과목 분류·점수는 S2, UI는 S3로 유지한다.

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
| 2026-09-19 | v1.7 | 사용자 승인: 교통 6~8월·90% 사전 보고·신분당선 추정 제외. 실응답: OA-12913·새 컬럼/ID 관계·월 합계·7월 복제 검증, R2 8개 원본/재집계 대조·로컬 교통 적재. 전체 RPC는 미검증 |
| 2026-09-20 | v1.8 | PR 4 최소 stores·원문 분야/과정·기관 지오코딩·주소 보정 거부·캐시 재사용·R2와 공간 조회 검증. 사용자 저장/브랜치/VACUUM 결정은 실제 응답 검증과 구분 |
| 2026-09-20 | v1.9 | 사용자 결정: 로컬 용량 제한 없음, S1 원격 무료 유지, S2 서울 전체 건물 적재 시 Pro 검토. 용량에 따른 구조 축소 조건 폐기. SHP 직접 ZIP 검증·강남구 WFS/OSM 전수 비교·공식 PK 변환·동 단위 API 페이지 수집 확인 |
| 2026-09-20 | v1.10 | PR 6 실제 XML·R-ONE 인증 응답, 법정동 경계, R2 27개·DB 집계 대조. 사용자 승인으로 district→region→NULL, 거래 다수 표본 유형·최소5건. 공식 권역 공간 정의 미확보로 region NULL 유지 |
| 2026-09-21 | v1.11 | PR 7 score_inputs 통합, S2 입력 전체 JSON 타입·NULL·단위·추정 계약과 실제 응답, 묶음별 ms, 부분 결측 격리·6조합 DB/HTTP 검증. 외부 원천 API 재호출 없음 |
