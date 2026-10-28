# Vworld ingest 호출 대체 검증 — 2026-10-28

**R2 읽기·로컬 코드/검증만 수행. 원격 DB 쓰기·R2 게시·기존 좌표/키 삭제 없음. migration·기존 DB 객체 변경 없음.**

| 경로 | 대체 | 실제 확인 |
|---|---|---|
| T1 지오코더 검증 | Juso 좌표, 별도 journal | legacy journal 거부, 역사 fingerprint 불일치 중단 유지 |
| 공급자 진단 | Juso 검색+좌표 | 공개 주소1건 ready, 건물관리번호 일치·EPSG:5179 |
| 법정동 WFS | 기존 R2 원본 재생 | 68행·346,410B, 강남14동 코드·도형 유지 |
| 건물 WFS | 기존 R2 원본 재생 | 33,345행·4,600,279B, 속성/도형·정규화 전수 동일 |

원본 SHA256:

- `raw/legal_boundaries/2026-09.parquet`: `8253b39f923001a8874ee08f74c7543156a8822a99fbc674a513d0506fc4340f`
- `raw/vworld_building_footprints/2026-09.parquet`: `6cda38773a28f479dcdcde157ab1be68c1bf208dbcc40eb60c247a9c93ba7ae5`

R2 HEAD 크기·SHA, 실제 다운로드 SHA·행수를 S1 manifest와 대조했다. 기존 restore 방식과 새 adapter의 전체33,345개 속성/도형, 같은 SHP28,227개로 정규화한 두 DataFrame을 전수 비교했다. 5,117개 보조 후보(기존 공간 겹침 제거 **전**)가 동일하다. 이후 공간 중복 제거·DB 적재 함수는 변경하지 않았다. 기존1,885개 최종 보조 건물은 재적재/삭제하지 않았다. 새 a~e 점수를 만들었다고 주장하지 않으며 기존 원격 점수/원천은 그대로다.

첫 Python dict equality는 양쪽 동일 NaN(`vl_rat`) 때문에 실패했다. 값 변경이 아님을 확인해 동일 JSON 표현·pandas 전수 비교로 검산했다. Decimal/결측 정밀도를 유지하도록 기존 restore와 같은 `fetchall → DataFrame`을 쓴다.

Juso 진단은 검색1회·좌표1회, bdMgtSn 일치·EPSG:5179 확인. 민감 응답·좌표·키는 보고서에 넣지 않는다. 과거 Vworld 출처를 Juso로 소급 변경하지 않았다.

`pnpm lint/typecheck/test` 통과: Vitest223, Python322. 집중 검사58개 통과: 캐시/변조/불완전 경계 중단, 공급자 HTTP·업무·미확보·키누락·건물불일치, 로그 비밀 미노출, retired Vworld 전송 거부. 새 라이브러리 없음.

[기계 판독 증거](vworld-ingest-retirement-20261028.json). [운영·삭제 대상](../operations/vworld-ingest-retirement.md). Draft PR 검토/머지 후 키 삭제는 한별이 수행한다.
