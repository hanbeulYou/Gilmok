# PR 2 최종: 행정동·주민등록 및 실제 R2 대조

2026-09-19. 사용자가 남은 최신 행정동 경계와 실제 R2 게시·DuckDB 재집계 대조를 승인했다. Supabase는 로컬 PostgreSQL 17.6/PostGIS 3.3.7을 유지했다. 원격 Supabase 연결·마이그레이션은 하지 않았다.

## 최신 행정동과 주민등록

- [vuski/admdongkor](https://github.com/vuski/admdongkor/tree/dd1881663fcabc69b81393604e91ebf3a4202e9a/ver20260701)의 2026-07-01 GeoJSON을 직접 받아 검증했다. 전국 3,558개 중 서울 427개. SGIS 기반 공개 가공물이며 정부가 직접 배포한 최신 원본이라고 표현하지 않는다.
- 파일 SHA-256: `c01ef44a0eb00978662ba7a6240ccb1da287fb52abd85104a1758969d391132f`.
- 원래 CRS84의 경도·위도 순서를 유지해 DB EPSG:4326으로 저장했다. 427개 기하 모두 유효하며 임의 보정·분할·단순화를 하지 않았다.
- `adm_cd2`(행안부 10자리) 말미 00을 제거한 8자리 코드 집합이 2026-08 주민등록의 427개 코드와 완전 일치했다. SGIS 통계용 `adm_cd`와 혼용하지 않는다.
- 2025-07-01 용신동→신설동·용두동 분동이 반영되어 있다. [동대문구 연혁](https://www.ddm.go.kr/www/contents.do?key=259) 및 가공자 변경 이력과 대조했다. 공식 생활인구 뷰어 426개·OA-22160의 425개 파일은 현재 적재에 쓰지 않았다.
- 원자 적재: admin_dongs 427행, population_age 1,281행. 세 밴드 모두 427동이며 합계는 5~9세 244,007명, 10~14세 341,692명, 15~18세 291,292명.
- 출처 표시: [SGIS 공공누리 1유형 + 가공자 CC BY 4.0](../data-attribution.md). Parquet 속성에도 출처·버전·커밋·출처 표시를 보존했다.

## 실제 R2 게시와 재읽기

`.env`의 실제 R2 버킷에 아래 6개 객체를 게시했다. 버킷·계정 식별자와 인증키는 문서·로그에 남기지 않는다. 생활인구는 원천 33개 컬럼과 `*`를 그대로 보존한다. 행정동은 서울 부분의 원래 속성과 GeoJSON 기하를 보존하고 검증된 조인 코드·WKT·출처를 추가했다. 격자는 원래 10,125개 기하를 WKB+EPSG:5179로 저장하며 생성한 두 셀을 원본에 섞지 않았다.

| 객체 키 | byte | 원본 행 수 | SHA-256 |
| --- | ---: | ---: | --- |
| raw/living_population/2026-06.parquet | 454,527,464 | 7,616,470 | `9976c52b2f43f689ec039eb95eca70fd498598dd48b37cbe273b27bf5ea064b3` |
| raw/living_population/2026-07.parquet | 469,086,652 | 7,866,059 | `e264b3ddce84ce6e127ac97486936c8d4360405c30dbb0dd6592e2e772554b20` |
| raw/living_population/2026-08.parquet | 468,798,845 | 7,861,840 | `978e5bd5deb9ce50d7b740503135ca3eb46712810ff24a7ec6754e2acbfb828b` |
| raw/resident_population/2026-08.parquet | 408,846 | 3,919 | `360342f7ddf7c36cba4107f572dfb4f4162d42d1a6803300e895bc50cb3e8a57` |
| raw/admin_boundaries/2026-08.parquet | 389,338 | 427 | `1ae1cc97bc78ceebb479acb49af41270ce7e33ca386c90b214a10eca7a7afc56` |
| raw/population_grid/2026-08.parquet | 167,768 | 10,125 | `b0fb676da2afe6a0bef0b4f1cb2783fd34d84852beba6cc683239bab54c1adb4` |

게시 시 로컬 SHA-256을 객체 메타데이터로 기록하고 HeadObject의 크기·메타데이터를 확인했다. 이 메타데이터만으로 원격 내용 검증을 주장하지 않고, 다음 DuckDB 값 대조를 추가했다. Multipart ETag를 파일 SHA-256으로 해석하지 않는다. 기존 객체와 해시·크기가 다르면 게시를 중단한다.

생활인구는 `RawStore.connection`의 DuckDB/httpfs로 실제 R2 객체 세 개를 읽어 **별도 readback Parquet**를 만들었다. 그 파일만으로 `aggregate_window`를 실행했다. R2 오류 시 로컬 원본으로 대체하지 않는다. 날짜별 컬럼 합계·유효 일수→최종 SUM(sum)/SUM(days) 코드는 로컬 폴백과 같다.

| 비교 항목 | 결과 |
| --- | --- |
| 기간·관측 셀 | 2026-06-01~08-31 / 8,598개 |
| 최종 전수 비교 | 411,512행, 불일치 **0행** |
| 키·NULL·sample_days·기간 | 정확 비교, 모두 일치 |
| 인구 컬럼 10개 | 허용오차 `1e-8 + 1e-10*abs(reference)`, 모두 일치 |
| 최대 절대 차이 | 1.4551915228366852e-11 (부동소수점 합산 순서 차이) |
| total NULL | 양쪽 모두 85,265행 |
| R2 재읽기본 집계 Parquet | 12,082,069 byte |
| 원래 로컬 집계 Parquet | 12,115,328 byte |

Parquet의 물리적 바이트 동일성을 요구하지 않는다. 재인코딩·행 순서에 따라 파일 크기가 달라도 키별 값·결측·분모·기간이 같음을 검증했다. 나머지 세 객체는 DuckDB 재읽기 후 양방향 `EXCEPT ALL`로 원본과 전수 비교하여 각각 차이 0행이었다.

## 용량·테스트·인계

생활인구+PK **98,787,328 byte(98.79MB)**는 [앞선 실측](pr2-living-fixed-20260919.md)과 같다. 주민등록·경계 추가 직후 admin_dongs 524,288 byte, population_age 352,256 byte, 전체 DB **122,285,203 byte(122.29MB)**. 시점별 할당 공간이며 최대 운영 디스크 사용량은 아니다. S1 나머지 소스를 아직 적재하지 않아 전체 S1 용량·RPC 성능은 미검증이다.

- `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm test:db` 통과. Vitest 1 + Python 단위 56 + DB 통합 41 = **98개**.
- 새 테스트: 게시·재사용·충돌/오류 시 폴백 금지, 비밀 오류 감춤, 원격 DB 접속 사전 차단, 집계 키/NULL/값/일수 차이 탐지, 행안부 코드·경계 검증, 주민등록과 경계의 원자 재적재/실패 복원/읽기 전용 RLS.
- 마이그레이션은 CLI로 새 `20260919114511_resident_population.sql`을 만들었다. 기존 마이그레이션·자료는 보존했다. 문제 시 새 주민등록 경로를 중지하거나 검증된 원본에서 원자 재적재하며 자동 DROP은 하지 않는다.
- 이번 세션 결정 7개는 data-sources.md §2.1과 §6 및 AGENTS.md §7에서 대조 완료: 250m, 고정 연령 컬럼, sample_days=total, 연령별 유효일 평균·편향, JSONB 제외, 날짜별 합계·일수, 실측 용량.
- 재현 명령은 [개발 문서](../development.md#pr-2-실데이터-재현), 다음 PR의 미확인 사항은 [명세 §6](../planning/data-sources.md#6-pr-2-인계--다음-세션의-시작점)을 따른다. 다음 PR은 새 세션에서 교통·상가 계획부터 시작하며 이번 PR에서 착수하지 않는다.

원본 로컬 감사 파일: `.local/validation/r2-living-publish.json`, `.local/validation/r2-readback/report.json`, `.local/validation/pr2-final/report.json`. 이 문서에 필요한 비밀 없는 검증 수치를 옮겼고 대용량 원본은 Git에 넣지 않았다.
