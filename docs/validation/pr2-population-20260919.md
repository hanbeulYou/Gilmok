# PR 2 실제 응답·250m 격자 검증 — 2026-09-19

PR 2 최초 조사 시점의 중간 검증 기록이다. **아래 저장 형식 대기는 이후 사용자 결정으로 해소되었으며, JSONB는 거절되고 고정 컬럼을 채택했다. 저장 정책과 용량은 [후속 기록](pr2-living-fixed-20260919.md)을 따른다. 최신 행정동 427개·주민등록 적재와 실제 R2 게시·재집계 검증도 [최종 기록](pr2-publication-20260919.md)에서 완료했다.** 아래의 미완료·로컬 준비 상태는 당시 이력이다. 원격 Supabase는 연결하지 않았고 S1 전체 성능 검증은 아직 남아 있다.

## 환경변수와 외부 키: 소스별 인증 요청 1회

`.env.example` 대비 빠진 이름과 추가된 이름은 없다. 빈 값은 `SUPABASE_SECRET_KEY`뿐이다. 사용자 설명과 달리 `NEIS_API_KEY`에는 값이 있지만 호출하지 않았다. Supabase DB·API URL은 모두 127.0.0.1이며 원격 ref·access token·DB password·publishable key의 인증은 검사하지 않았다. 비밀 값은 이 기록에 포함하지 않는다.

| 소스 | 한 번 실행한 요청 | 실제 결과 | 검증 범위의 한계 |
| --- | --- | --- | --- |
| data.go.kr | HTTPS `/B553077/api/open/sdsc2/storeListInRadius`, radius=500, cx=127.062, cy=37.494, numOfRows=1, pageNo=1, type=json | HTTP 200, resultCode=00, 1행 | 상가 API만 확인. 건축HUB·실거래 활용승인은 미확인 |
| 서울 | `/json/CardSubwayStatsNew/1/1/20260901/` | HTTP 200, INFO-000, 1행 | 인증키 동작 확인. 생활인구 API 호출 성공을 의미하지 않음 |
| Kakao | `/v2/local/search/address.json`, query=서울 강남구 삼성로 212, size=1 | HTTP 403, NotAuthorizedError | 정확한 원인 미확정. 사용자 앱의 Local API 권한·키 종류 확인 필요. 재호출 안 함 |
| R2 | HeadBucket | HTTP 200, RetryAttempts=0 | 버킷 접근만 확인. 객체 쓰기·읽기·DuckDB R2 조회 미검증 |

위 인증 요청에는 재시도·리디렉션을 적용하지 않았다. 이후 PR 2 원본 수집은 키를 보내지 않는 공개 파일 다운로드다. 로컬 상세 결과: `.local/validation/credentials-20260919.jsonl` (비밀 값 없음, Git 제외).

상가 실응답에서 `bizesId`, `bizesNm`, `adongCd`, `adongNm`, `ldongCd`, `ldongNm`, 업종 분류 코드·이름, `lon`, `lat`, `flrNo`를 확인했다. 명세의 `/sdsc/`는 `/sdsc2/`로 수정했다. 서울 실응답의 지하철 일계 컬럼은 `USE_YMD`, `SBWY_ROUT_LN_NM`, `SBWY_STNS_NM`, `GTON_TNOPE`, `GTOFF_TNOPE`, `REG_YMD`다. 이 일계 서비스를 시간대별 승하차 소스의 대체로 쓰지 않는다.

## 다운로드 근거와 재현 정보

- [현재 내국인 250m 생활인구 OA-22784](https://data.seoul.go.kr/dataList/OA-22784/S/1/datasetView.do)
- [구 집계구 자료 OA-14979](https://data.seoul.go.kr/dataList/OA-14979/S/1/datasetView.do): 2026-07-31 이후 생산 종료 안내 확인.
- [서울 생활인구 공식 안내](https://data.seoul.go.kr/dataVisual/seoul/seoulLivingPopulation.do): 현행 정의서, 매뉴얼, 격자 SHP 제공.
- [행정안전부 연령별 주민등록 인구](https://jumin.mois.go.kr/ageStatMonth.do)
- [서울시 상권분석서비스 행정동 경계 OA-22160](https://data.seoul.go.kr/dataList/OA-22160/S/1/datasetView.do)

서울 페이지의 실제 다운로드 폼을 확인했다. POST `https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?useCache=false`에 다음 값을 전송했다. API 키는 사용하지 않는다. 아래 seq는 이번 파일의 식별값이며 미래 월의 seq를 추측해 만들지 않는다.

| 자료 | infId | infSeq | seq |
| --- | --- | --- | --- |
| 2026-06 / 07 / 08 생활인구 | OA-22784 | 1 | 2606 / 2607 / 2608 |
| 250m SHP | DOWNLOAD | 4 | 37 |
| 현행 정의서 XLSX / 매뉴얼 PDF | DOWNLOAD | 4 | 34 / 35 |
| 행정동 코드 ZIP (월별 CSV) | DOWNLOAD | 4 | 18 |
| 상권분석 행정동 SHP | OA-22160 | 3 | 1 |

주민등록 CSV는 `/downloadCsvAge.do?searchYearMonth=month&xlsStats=3`에 공식 화면의 폼을 POST했다. `sltOrgType=1`, `sltOrgLvl1=A`, `sltOrgLvl2=`, `gender=gender`, `sum=sum`, `sltUndefType=`, 시작/종료 연월=2026/08, `sltOrderType=1`, `sltOrderValue=ASC`, `sltArgTypes=1`, `sltArgTypeA=5`, `sltArgTypeB=18`, `category=month`다.

| 로컬 원본 식별명 | 크기(byte) | SHA-256 |
| --- | ---: | --- |
| grid250.zip | 329,428 | `5f7f95db30f1d4a433d9905b281c3fb95b59cd8200985512a897326208bf525e` |
| living_definition (XLSX) | 266,797 | `18238af79d3af821d4b2b029d7512385286a3a0e9ae76113f0fbef8f744bf93a` |
| living-202606.zip | 448,638,322 | `953e9790e174220eee0d028f1ae393ccd3e5fd88579db32b5b4a60cf2ba13d62` |
| living-202607.zip | 422,066,022 | `c4f27c5516cf734a19ef6b1f4b51fd00253d70710cf2777a06eb65301e9a0280` |
| living-202608.zip | 465,599,054 | `8210f1c3ad9224f5cbd16d2c35fe4daae0d0f9f7a642880063d6d9dbd3a51c5e` |
| residents-202608.csv | 1,170,189 | `a05aea5237364f21c2b4f1716d855346c85747b9768f2d57529ef30fe6fa9334` |

원본은 `.local/validation`, Parquet는 `.local/ingest`에 있으며 Git에 넣지 않는다. 수집 시점 이후 게시 파일이 교체될 수 있으므로 해시와 기준월을 함께 비교한다.

## CELL_ID → 폴리곤 검증

공식 ZIP의 `match/match.shp`·DBF·SHX·PRJ·CPG를 읽었다. 컬럼은 `CELL_ID`, `CELL_X`, `CELL_Y`, `GID`와 기하정보다. PRJ와 DuckDB 공간 메타데이터가 EPSG:5179를 가리킨다. EPSG의 투영 원점은 경도 127.5°, 위도 38°, 축척 0.9996, false easting/northing 1,000,000/2,000,000m, GRS80이다.

국가지점번호의 이번 `다사` 블록 원점은 EPSG 투영 원점과 별도로 **900,000 / 1,900,000m**다. 실제 모든 경계가 다음 규칙을 만족하는지 검증했으며 불일치는 0건이었다.

```text
CELL_ID = 다사 + XXXX(4자리) + YYYY(4자리)
xmin = 900000 + int(XXXX) × 10
ymin = 1900000 + int(YYYY) × 10
xmax = xmin + 250; ymax = ymin + 250
CELL_X = xmin + 125; CELL_Y = ymin + 125
```

| 검증 항목 | 실측 |
| --- | ---: |
| SHP의 고유 셀 | 10,125 |
| 모든 원천 폴리곤 면적 | 62,500㎡ |
| 3개월 원본에서 실제 관측한 셀 | 8,598 |
| 원본에 있으나 SHP에 없는 셀 | 2 |
| 보완 후 DB 경계 수 | 10,127 |
| 보완 후 원본 경계 미매칭 | 0 |
| 로컬 DB 유효하지 않은 폴리곤 | 0 |
| DB 경계 테이블·인덱스 실제 크기 | 3,571,712 byte |

누락 셀 `다사47256125`의 최소점은 (947250, 1961250), `다사67254075`는 (967250, 1940750)이다. 위 규칙으로만 생성했고 `boundary_generated=true`를 남겼다. 접두어·격자 정렬·원천 파일의 전체 extent 범위가 검증되지 않으면 생성을 거부한다. 좌표는 longitude/latitude 순서를 명시해 EPSG:4326으로 변환했다.

`population_cells`는 `(resolution_m, cell_id)` PK와 `geom` GiST 인덱스를 가진다. `cell_id`가 원천 의미를 정확히 표현하므로 추상적인 `spatial_unit_id`로 바꾸지 않았다. 다른 해상도는 복합 키로 구분하되, 현재 적재기는 실제 확인한 250m만 허용한다. 다른 코드 체계를 쓰는 격자까지 자동 지원한다고 주장하지 않는다.

## 기존 계약과 실제 시간·연령·요일 대조

| 항목 | 기존 문서 | 실제 파일 / 처리 |
| --- | --- | --- |
| 공간 키 | 통계청 집계구 `tot_reg_cd` | `250M격자` = CELL_ID, 250m 정사각형 |
| 날짜·시간 | 시간대 0~23 | `일자` YYYYMMDD, `시간` 문자열 00~23. 시간 범위 동일 |
| 연령·성별 | 연령·성별이라는 설명만 존재 | 남녀 각각 14밴드. 0~9, 10~14, 이후 5세 단위로 65~69까지, 70세 이상 |
| 학령인구 | 주민등록 5~9·10~14·15~18 | 생활인구 0~9·10~14·15~19와 다름. 주민등록 단일 연령을 별도 사용 |
| 요일 | 평일·주말 분리 평균 | 요일 컬럼 없음. 날짜에서 월~금/토·일 파생, 공휴일 재분류 없음 |
| 골든타임 | [15:00, 22:00) | 15~21 사용, 변경 없음 |
| 비공개 | 3명 이하 `*` → NULL | 실제 `*` 확인. 합계의 일부라도 비공개면 결과 NULL |
| 원본 행 단위 | 집계구×시간×연령 가정 | 일자×시간×행정동×셀. 같은 셀의 행정동 조각은 합산 필요 |

실제 CSV는 CP949의 한글 헤더 33개다. 정의서의 `YMD`, `TT`, `H_DNG_CD`, `CELL_ID`, `SPOP`, `M00`/`F00` 등 영문 필드를 그대로 헤더라고 가정하면 읽기에 실패한다. 정상 수치에 `39.` 같은 소수점 종결 문자열도 있어 이를 허용한다.

기존 정의서의 상세 연령밴드와 1:1 동일하다고 확인한 것은 아니다. 기존 기획 문서에는 상세 밴드가 없고 이전 정의서 다운로드 링크는 실제 XLSX를 반환하지 않았다. 이번 현행 정의서와 실제 CSV 간에는 14밴드를 대조했다.

원본의 4중 키 중복은 없었다. 셀·날짜·시간만 보면 행정동 조각이 여러 개인 그룹이 **4,109,051개**다. 원본에서 조각을 보존하고 셀 총합을 일수로 나눈다. 전체값은 SPOP를 사용하며 남녀·연령 합계로 대체하지 않는다. NULL인 평균 3,773,657개는 비공개 조각 또는 누락 날짜에 따른 것으로 0이나 관측일만의 평균으로 대체하지 않았다.

## 서울 전체 건수와 용량

| 월 | 원본 행 수 | 고유 셀 | 날짜 수 | 원본 Parquet byte |
| --- | ---: | ---: | ---: | ---: |
| 2026-06 | 7,616,470 | 8,593 | 30 | 454,527,464 |
| 2026-07 | 7,866,059 | 8,591 | 31 | 469,086,652 |
| 2026-08 | 7,861,840 | 8,596 | 31 | 468,798,845 |
| 합계 / 셀 합집합 | 23,344,369 | 8,598 | 92 | 1,392,412,961 |

3개월 집계 Parquet는 **6,172,680행 / 17,132,020 byte**다. 전체+14연령대의 값, 관측/예상 일수, 비공개 조각 수를 담는다. 셀·요일 유형·시간 조합은 **411,512개**다. 완전히 미관측한 조합은 행을 만들어 0으로 채우지 않는다.

PostgreSQL 17.6/PostGIS 3.3.7 로컬 DB에서 실제 집계 표본을 임시 테이블에 COPY하고 ANALYZE 후 `pg_total_relation_size`를 측정했다. 두 구조 모두 공통 출처 컬럼·적재 시각·추정 플래그와 PK 인덱스를 포함했다. 측정 트랜잭션은 rollback했다.

| 구조 | 실제 표본 행 | 실제 표본 byte | 전체 행 수 | 전체 환산 예상 byte |
| --- | ---: | ---: | ---: | ---: |
| 연령대별 행 | 100,000 | 22,118,400 | 6,172,680 | 1,365,298,053 |
| 연령값·비공개 수 JSONB map | 29,518 | 25,337,856 | 411,512 | 353,236,391 |

장형 표본은 `(cell_id,dow_type,hour,age_band)` 해시순 100,000개, JSONB 표본은 셀·요일·시간 해시 `%14=0`인 조합이다. 값과 NULL, 비공개 수를 줄이지 않고 표현만 바꿨다. **환산치는 전체 DB 적재 실측이 아니다.** 보조 인덱스, 다른 S1 테이블, DB 시스템 공간·갱신 중 임시 공간·팽창은 포함하지 않는다. JSONB여도 500MB 전체 목표 충족은 보장하지 않는다. 최종 형식 승인 후 전체 적재 크기와 RPC 실행 시간을 다시 측정해야 한다.

최초 조사 당시 승인된 장형은 생활인구만으로 500MB 목표를 초과했다. JSONB 대안을 제안한 상태이며 이 PR의 현재 마이그레이션은 경계만 생성한다. `living_pop` 물리 스키마와 DB 적재는 답변을 기다린다.

## 주민등록 인구·행정동 경계 불일치

2026-08 CSV의 서울 행정동 427개에서 3개 학령 밴드 **1,281행**을 정규화했다. 합계는 5~9세 244,007명, 10~14세 341,692명, 15~18세 291,292명이다. 19세를 포함하지 않는다.

공식 생활인구 뷰어의 DONG GeoJSON(2025-06-30)은 426개, SIGUNGU는 25개다. 현재 행정동 코드 파일에는 구 용신동 대신 신설동(11230515)·용두동(11230533)이 있다. 이름의 점/가운뎃점 표기를 정규화해도 이 분동은 해소되지 않는다. 별도로 받은 OA-22160의 SHP는 게시 페이지 갱신일이 2026-09-11이지만 실제 경계는 **425개 / EPSG:5181**이다. 게시일만으로 최신 경계라고 판단하지 않는다.

현재 427개 코드와 맞는 경계 파일을 아직 확보하지 못했다. 구 경계를 임의 분할하거나 주민등록 인구를 250m 셀에 추측 배분하지 않았다. 정규화 함수만 제공하며 서울 전체 인구의 공간 적재 완료로 표시하지 않는다.

## 재실행·전환 경계

월별 원본 검증은 다음 명령으로 실행한다. 다운로드는 승인된 소스 폼을 사용하는 `/ingest` 수집 과정에서 수행하며 아래 명령은 파일만 읽는다.

```sh
uv run --frozen python -m ingest.living_population \
  .local/validation/living-202608.zip 2026-08 \
  .local/ingest/raw/living_population/2026-08.parquet
```

3개월 집계는 `ingest.living_population.aggregate_window(paths, date(2026,6,1), date(2026,8,31), destination)`으로 재현한다. 경계는 `ingest.population_grid.grid_rows(shp, observed_cells)`로 검증·변환한 뒤 `ingest.population_database.load_population_cells`로 적재한다. 원천 불일치·빈 스냅샷·중복 키·잘못된 기하는 실패 처리하고 이전 DB 스냅샷과 성공 감사 기록을 보존한다.

새 마이그레이션은 CLI로 생성했고 기존 마이그레이션과 `census_blocks` 데이터를 수정하지 않았다. 롤백은 새 경로의 사용을 중지하는 것으로 가능하다. 테이블 삭제·기존 집계구 제거 같은 축소 마이그레이션은 이번 PR에 포함하지 않는다. 원격 Supabase 전환은 필요 시 먼저 사용자에게 알린다.

검증 범위: 소스 fixture 단위 테스트와 로컬 DB 통합 테스트, 실제 3개월 파일 정규화·집계·경계 적재. `score_inputs`와 S1 성능 기준은 후속 RPC 작업에서 검증하며 이번 결과로 통과 처리하지 않는다.
