# score_reference 운영 — S2-1

기준은 [채점 명세 v0.1.1](../planning/scoring-spec.md)다. 이번 PR은 기준 분포와 공통 원시값 추출만 구현한다. 종합/축 점수, 가시성, 실제 학원 순위 검증은 포함하지 않는다. 원격 활성화 변수는 기존처럼 false 상태를 유지한다.

## 실행

```sh
pnpm score:reference:build
uv run --frozen python -m ingest.score_reference
```

기본은 로컬 Supabase, 주소 없는 floor=2. 검증된 250m 격자 10,127셀의 EPSG:5179 중심점을 4326으로 바꿔 800/1000m를 호출한다. 새 격자 수가 다르면 자동 축소/표본 적재하지 않고 실패한다. 기준 분포 갱신은 원본 수집 API를 재호출하지 않는다.

월간 workflow는 기존 6소스 matrix 성공 후 `needs: refresh`로 reference를 한 번 실행한다. 단일 소스 재시도 선택 시에도 완료 후 현재 모든 소스 버전으로 다시 만든다. 실패 시 별도 `score-reference.yml` 수동 실행이 가능하다. job은 30분 timeout, concurrency 중복 방지, 원격/R2 가드, 고정 main checkout을 사용한다. 실제 원격 전체 시간은 미검증이다.

원격은 `--target remote`, `INGEST_REMOTE_ENABLED=true`, 일치하는 프로젝트 ref·TLS DB URL·R2가 모두 필요하다. 기존 `ingest-production` Secrets만 사용하며 새 키는 없다. CLI 실행 코드가 달라졌으면 반드시 TS bridge를 다시 빌드한다.

## 수집과 원자 교체

1. 기존 refresh의 소스별 advisory lock으로 reference 작업 중복을 막는다.
2. 단일 REPEATABLE READ / READ ONLY 스냅샷에서 전체 셀·RPC·10개 관련 소스 버전을 읽는다. inside_seoul은 RPC와 같은 ST_Covers 조건이다. 주소 큐를 만들지 않는다.
3. Python 수집 파일을 기존 tsc로 컴파일한 `/lib/scoring/raw.ts`에 전달한다. 같은 TypeScript 함수를 S2-2도 사용하므로 두 언어에 가중식을 중복 구현하지 않는다.
4. NULL 행을 보존하고 셀×반경×지표 완전성·중복·유한값·버전을 검사한다. R2 입력/분포 Parquet를 게시 후 재읽기하고 **게시 입력에서 전 행을 재계산**해 게시 분포와 EXCEPT ALL 양방향 대조한다.
5. 활성화 전에 관련 소스 테이블을 짧게 SHARE NOWAIT 잠그고 source fingerprint가 수집 시점과 같은지 확인한다. 동시 갱신·변경 감지 시 이전 reference를 유지한다.
6. 값 테이블·공개 요약·private refresh manifest를 한 트랜잭션으로 교체한다. 커밋 후 별도 autocommit 연결에서 두 reference 테이블만 VACUUM ANALYZE 한다.

공개 테이블은 anon/authenticated SELECT만 허용한다. 사용자가 입력한 주소·임대료·candidate는 배치에서 조회하거나 기준 분포에 넣지 않는다. 강남구 전용 건물·실거래도 원시 분포 키로 쓰지 않는다.

## 저장 계약

- `score_reference`: preset_id, preset_version, snapshot, radius_m, cell_id, axis_key, raw_value(double precision/null), computed_at, inputs_schema_version. PK는 preset_id/radius/cell/axis. 비NULL raw_value는 음수/NaN/Infinity 불가.
- `score_reference_sets`: preset별 현재 version/snapshot, computed_at, inputs_schema_version, cell_count, source_fingerprint, source_versions, statistics. 값 행과 snapshot FK로 연결한다.
- `ingest_private.refresh_snapshots`: 기존 private 표에 source=score_reference의 활성 원본 manifest를 함께 기록한다.

공개 statistics의 각 반경/지표에는 cell_count, population_size(비NULL), missing_count, coverage, missing_ratio, min/max가 있다. 평균값으로 NULL을 채우지 않는다. 비NULL 분포 조회를 위한 부분 인덱스가 있다. preset/schema/radius/source 버전이 다른 분포로 채점하지 않는다.

source fingerprint는 관련 소스의 버전·기준일·ingested_at 및 격자 geometry MD5를 정규 JSON으로 묶은 SHA256이다. refresh/검증된 loader를 통한 교체를 전제로 하며 운영자의 출처 메타데이터 없는 임의 SQL 변경을 추적하는 감사 시스템은 아니다.

## 실패와 재실행

수집·TS 식·R2·검증·COPY 실패는 기존 활성 분포를 유지한다. R2에 게시만 된 미참조 revision은 자동 삭제하지 않는다. VACUUM 실패는 committed=true, maintenance_failed이며 새 분포 자체는 유효하다.

완료된 동일 snapshot 재시도는 source/현재 snapshot을 확인한 뒤 수집 없이 유지보수만 수행한다. 미완료 실행의 부분 파일은 임의 이어붙이지 않는다. 실패 후 새 실행은 새 UTC snapshot으로 시작한다. 원본 R2 revision을 덮어쓰지 않는다. 이전 버전으로 복구할 때에는 당시 source/preset/schema를 확인하고 R2 원본을 재검증하여 새 실행으로 게시한다. 이전 분포를 현재 소스와 같은 것으로 표시하지 않는다.

`report.json`은 결과·manifest·호출 시간 요약을 담는다. Actions에는 이 보고서만 30일 보관한다. R2 입력/분포/manifest는 [시즌 보존 정책](data-refresh.md#시즌-비교를-위한-r2-정책)에 따라 자동 만료 없이 보관한다. 로컬 작업 폴더 `.local/score-reference/<snapshot>/`에는 전체 배치와 재계산 파일이 있으므로 저장 공간 실측에 포함한다.

`cluster.saturation`은 8번째 근거 지표이며 점수에는 사용하지 않는다. 동일 셀의 n_field 또는 students가 NULL이거나 students=0이면 NULL, 관측 n_field=0·students>0이면 0이다. 교통 원천은 버스·지하철의 모든 버전을 manifest에 기록한다. S1 RPC의 transit_counts 메타데이터는 LIMIT 1에 따라 둘 중 하나를 반환하므로 이 검증된 버전 집합의 멤버인지 확인한다.

실측은 [S2-1 검증](../validation/s2-1-score-reference-20260923.md)을 따른다. 로컬 20,254회 조회·R2·전수 검증·적재 합계 483.816초다. PostgreSQL 텍스트 조회의 extra_float_digits 설정은 소수를 반올림할 수 있으므로 정확한 저장값 대조는 psycopg 바이너리 커서를 사용한다. S2-2 reference 공급 경로에서도 이 정밀도를 보존하고, HTTP 응답의 동률 판정은 별도로 검증해야 한다.
