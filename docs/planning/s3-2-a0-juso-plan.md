# S3-2 A0 — Juso 전환·단계별 데이터 교체

base: main

2026-09-30 **구현·로컬 T1 검증·승인된 원격 migration1개 적용 완료**. PR [#23](https://github.com/hanbeulYou/Gilmok/pull/23), 브랜치 `s3/juso-transition`. #22는 주소 공급자 인터페이스만 맞춰 병행하고, 데이터/fixture는 A0 머지 후 동기화한다. A의 백분위/context RPC WIP를 이 PR에 섞지 않는다.

## 1. 이번 승인 범위와 중단 조건

- Juso 검색 키 `JUSO_API_KEY` + 임시 **Vworld 좌표**로 파이프라인과 대치동3곳 T1 검증까지 진행한다. Juso 출입구 좌표라고 표시하지 않는다. 실제 coordinate_provider를 보존한다.
- `JUSO_COORD_API_KEY` 발급 후 좌표 공급자를 교체하고 **13,542건 전량 재산출은 별도 실행·보고**한다. 키가 생겼다고 자동 실행하지 않는다.
- 사용자 검색은 무캐시 실시간. 좌표는 등록 시1회 조회 후 후보 행에만 저장. 공용 geocode_cache는 Actions/직접 DB URL 배치만 쓴다. uid별 응답 캐시·서명 RPC·서명키 없음. 이번 A0에서 Vercel 변수 변경 없음.
- 카카오 키·cache 삭제는 **재산출→8축 차이 보고→manifest 승인 후**. 현재 .env/Actions Secrets 값과 활성 원본/기존 cache는 보존한다. 과거 응답의 순수 파서는 S2 재현에만 남기며 외부 카카오 요청 함수는 제거한다.
- 원격 migration은 최종 `db push --dry-run` 보고 후 별도 승인. 리전 변경은 아래 §9의 조건부 제안일 뿐 실행하지 않는다.
- 새 좌표가 다른 PNU/도형 밖이면 결과와 거리를 보고한다. 중심점·근접 도형으로 자동 교체하지 않는다. 동일 PNU 포함 확인을 통과하기 전 새 기준 fixture를 확정하지 않는다.

## 2. 공급자 계약·해외 서버 확인 결과

계약 v1: `lib/geo/address-provider.ts`와 `ingest/juso.py`. 주소 선택 식별자와 좌표 공급자는 독립이다. Python 배치와 #22 Route Handler는 같은 필드 이름을 사용하며, 외부 API 호출은 허용된 서버 경로에만 둔다.

Juso 검색의 `admCd(10)` + 산여부(`0→1`, `1→2`) + 지번본번4자리 + 지번부번4자리로 PNU19자리를 구성한다. 도로 건물번호/지하여부를 필지번호에 넣지 않는다. 선택 건물 `bdMgtSn`과 좌표 응답의 건물을 검증한다. Juso 좌표 원천5179→저장4326/계산5186. 현재 임시 Vworld는4326이며 원CRS를 별도 기록한다. 도형 포함은 `ST_Covers`, 거리는 geography/5186이다.

2026-09-30 공식 원문 확인:

| 원문 | 확인 결과 | 한계 |
| --- | --- | --- |
| [현행 Juso 이용약관](https://www.juso.go.kr/Terms), 시행2026-08-20 | 공식 SPA의 Terms-79fce816.js 원문 조회. SHA256 `6f09c82acfff44282fa042673efdcc9df8ff53d2713197f3213c668bf1083e26`. 약관 자체에 해외/국외 조항 없음 | 약관에 없다는 이유로 좌표의 해외 저장 허용을 추정하지 않음 |
| [주소정보 전산체계 운영규정, 훈령196호](https://www.mois.go.kr/frt/bbs/type001/commonSelectBoardArticle.do?bbsId=BBSMSTR_000000000016&nttId=84852), 2021-06-09 | 공식 HWP 원문 SHA256 `0b6f85d324c2806a2dd4740ba483b93c988b4e687f0c1ce955f5a07fbb1f88e4`. 제19조는 품질관리이며 국외/해외 문구 없음 | 과거 Q&A가 인용한 구 「도로명주소정보체계 운영규정」 제19조와 동일하게 취급하지 않음 |
| [주소정보 제공에 관한 규정, 고시2024-45호](https://www.law.go.kr/admRulLsInfoP.do?admRulSeq=2100000242090), 2024-06-07 | 공식 본문 `admRulLsInfoR.do?admRulSeq=2100000242090` 조회. 제2조는 좌표가 포함된 제공 정보의 유형을 구분한다. 제5조제3항은 제한제공 주소정보의 목적 심사에서 국외 반출 등 보안지침 위반 시 미제공을 규정 | 공개 API 출입구 좌표 전부를 해외 저장 금지로 단정할 근거로 일반화할 수 없음 |
| [공식 Q&A114474](https://eng.juso.go.kr/addrlink/qna/qnaDetail.do?bulletinRefSn=114474&currentPage=184&keyword=&noticeMgtSn=114474&noticeType=QNA&noticeTypeTmp=QNA&page=&searchType=), 2023-05-09 | 앞선 조사에서 공간정보(지도·좌표) 해외 업로드 제한 안내 확인 | 이번 원문 재조회는 timeout. 2026년 공개 API 좌표/도쿄 DB 적용 범위를 확정한 신규 답변 아님 |

[최근 공식 Q&A142076](https://m1.juso.go.kr/addrlink/qna/qnaDetail.do?bulletinRefSn=142076&currentPage=2&keyword=&noticeMgtSn=142076&noticeType=QNA&noticeTypeTmp=QNA&page=&searchType=)(2025-12-10)는 **주소정보 안내도/공간정보 SHP**의 해외 서버 적재·운용 불가 및 한국 소재 서버의 별도 제약 없음을 안내한다. 이번 재조회에서는 검색 색인 답변을 확인했으나 상세 URL은 timeout이었다. 공개 좌표 API의 현행 적용 범위까지 답한 자료로 확대하지 않는다.

**결론: 현재 공개 API 좌표의 Tokyo DB·해외 백업 적용 범위는 미확정.** 로컬 구현·3곳 검증은 진행하고 해외 저장 승인으로 표현하지 않는다. 문의할 내용: 공개 검색API(좌표) 결과를 한국 리전 Route Handler가 받아 도쿄 DB, R2 및 CI artifact에 저장할 수 있는지, 금지 시 서울 리전의 외국계 클라우드/백업/국외 처리 로그도 제한되는지, 적용 조문과 허용 범위를 요청한다. 계정 문의는 아직 제출하지 않았다. [data-sources §2.8](data-sources.md#28-지오코딩--juso-전환-계약)의 저장·쿼터·출처 근거를 함께 적용한다.

## 3. 현재 의존성 목록

2026-09-30 로컬·원격 DB를 `default_transaction_read_only=on`으로 조회했다. 비밀·사용자 식별자는 기록하지 않았다. [목록·행수·해시 JSON](../validation/s3-2-a0-inventory-20260930.json)은 코드/문서 검색 당시 A WIP 브랜치의 파일 목록도 포함한다.

| 저장소/경로 | 로컬 / 원격 현황 | A0 처리 |
| --- | --- | --- |
| `public.geocode_cache`, kakao | 각각 **13,542행**: 성공13,481·실패61. 정렬한 주소/provider/성공여부/좌표/실패사유 SHA256 동일 | 성공·실패 전부 재판정 대상. Juso shadow 결과 검증 후 교체. 기존 성공값 provider만 변경 금지 |
| 같은 테이블, vworld | 각각 성공11·실패17 | 독립 출처로 보존·약관/주소 동일성 재확인. Juso 우선순위로 소비자 수정 |
| `academies` | 각각 kakao 성공25,412·실패86, vworld 성공10 | 원천 주소로 재연결. 기관25,508행과 ID/분류/원문 보존, geom/provider/reason만 계수해 교체 |
| `schools` | 각각 kakao 성공1,312·실패7 | 원천 주소로 재연결. 학교1,319행·ID·학교급 보존. 출입구 대표점 변경이 학교 반경/동선에 미치는 영향 계수 |
| `ingest_private.geocode_requests` | 각각 kakao 성공13,480·ambiguous26·invalid8·not_found27 | provider CHECK 확장, 새 juso claim은 별도 키. 구 카카오 실패/중단을 Juso 실패로 복제하지 않음 |
| `ingest_private.building_address_cache` | 각각1행. source가 대장 출처라 geocoder를 직접 식별하지 못함 | `raw_key`→저장 geocode 응답의 계보 대조. 대장 payload는 보존하며 좌표/PNU/provider 계보 재검증 |
| `public.candidates` | 각각0행 | 적용 직전 재계수. 그 사이 사용자 행이 생기면 소유권·임대료·비교 연결 보존하며 별도 전환 명세 필요 |
| `ingest/geocode.py` | 요청/파서/기본 provider/claim/journal/CLI가 kakao | 공용 Juso 파서·PNU·좌표 변환·provider 선택으로 교체 |
| `ingest/building_on_demand.py` | `request_kakao`, `address_parcel`, 키 검사, `geocode.json` 저장 | Juso 주소 검증/좌표/PNU를 사용. 건축HUB 호출은 계속 `/ingest` |
| `ingest/commerce_education_database.py` | 성공 캐시 중 kakao 우선 | juso→vworld 명시적 순위. 기존 kakao로 암묵 fallback 금지 |
| `ingest/refresh_sources.py` | 학원·학교 갱신에서 Kakao 키 전달 | Juso 키/제한기 주입. 일괄 갱신과 on-demand에 같은 판정 규칙 |
| `ingest/verify_s2_4.py`, A의 `verify_registration_reference.py` | 저장 카카오 응답/좌표를 재현 입력으로 소비 | 새 Juso 기준 fixture를 별도 생성. 기존 fixture는 전환 전 비교 증거로 구분 |
| `.github/workflows/{address-queue,refresh-source}.yml`, `.env.example` | Kakao 키 주입/계약 | Juso 키 두 종류로 변경. `.env`·Actions의 `KAKAO_REST_API_KEY` 제거는 전환 검증 후 작업 목록. 이번에는 값/Secrets 변경 없음 |
| R2·로컬 raw/journal | `raw/academies/`, `raw/schools/`, 주소 워커 geocode 응답 및 과거 고정 복원 manifest | 활성 원본/파생 Parquet/reference/복원 manifest를 새 버전으로 재발행. 객체·버전·해시·파생관계의 전수 목록은 A0에서 확정. 원격 객체 삭제는 별도 검토된 목록으로 승인 |
| 문서·fixture | PR4 지오코딩, S2-3 exposure 보고서, S2-4 원본/v0.3 JSON·MD, S3 검증·계획·운영 문서 | 현행 기준은 Juso로 교체하고 기존 실측을 사후에 Juso 결과처럼 고쳐 쓰지 않음. 역사 기록은 구 공급자/대체 문서 링크로 구분. 공개 raw 정리와 Git 이력 재작성은 별개이며 이력 강제 재작성은 범위 밖 |

대상 cache digest: `90c26f4a3b1c7be5f5163102e16c3d2825f83dce659bacc989b4959e84131d7a`. 캐시 목록 전체를 사용자 화면이나 문서에 노출하지 않고 승인용 manifest에서 키·행수·해시로 대조한다.

### 대치동 3곳의 전환 전 기준

| 후보 | 기존 위도, 경도 | PNU | 기존 total / confidence |
| --- | --- | --- | --- |
| a 역삼로460 3층 | 37.5025724504279, 127.057585738094 | 1168010600109120013 | 85.085005 / 90 |
| b 도곡로409 2층 | 37.4973692137569, 127.055167024731 | 1168010600109380022 | 93.372948 / 90 |
| c 역삼로546 덕일빌딩 3층 | 37.5042868910393, 127.062872712855 | 1168010600109670000 | 83.863983 / 85 |

세 좌표는 과거 S2-4에서 해당 PNU 도형 내부였다. **Juso 좌표/포함 여부/점수 차이는 아직 값 없음**이다. 정확한 숫자가 등장하는 추적 파일/행 목록을 inventory에 넣었다. 반올림 좌표·다른 과거 좌표의 계보는 문자열 검색만으로 확정할 수 없으므로 생성 스크립트와 raw manifest를 함께 대조한다. 최초 요청의 오인 좌표와 후속 도형 중심점은 카카오 원응답과 구분한다.

## 4. 구현과 검증 순서

1. 순수 Juso 검색/식별자 파서→선택→교체 가능한 좌표 공급자를 구현한다. 실시간 검색 목록은 캐시하지 않는다. 배치는 유일하고 정확한 도로명/지번만 자동 선택하며 건물명 검색은 사용자가 결과를 선택한다.
2. Vworld의 정제 도로명·건물번호·구가 Juso의 도로명주소와 일치하는지 확인한다. 인증/제한/장애를 주소 없음으로 저장하지 않으며 잘못 보정한 주소를 거부한다. 키 포함 URL/응답 echo를 오류 로그에 넣지 않는다.
3. 확장 migration: geocode_requests provider CHECK에 juso 추가, 공용 cache의 provenance JSONB 추가. 기존 행은 NULL 보존. 앱 JWT 역할은 cache 쓰기 불가, DB 배치만 쓴다. 기존 migration 수정·기존 데이터 삭제 없음.
4. `/ingest/geocode.py`, 주소 워커, 학원·학교 refresh, Actions의 호출 경로를 Juso+Vworld로 교체한다. cache reader는 신규 juso 우선, 아직 교체하지 않은 기존 배경은 보존한다. 워커의 강남구 범위·건축HUB 조회·대장 캐시30일은 유지한다.
5. `ingest/verify_juso_transition.py`가 로컬 읽기 전용 DB에서 3곳만 조회한다. 응답을 로컬 journal에 남겨 재실행 시 재사용한다. 신구 좌표·PNU·도형·이동거리·포함 여부·응답 SHA를 manifest에 기록한다. 공용 cache, R2, 원격 DB에는 쓰지 않는다.
6. `ingest/verify_juso_transition.mjs`가 동일 v0.3 순수 채점/exposure 함수로 T0 완전 재현과 T1의8축·총점·신뢰도·순위를 보고한다. 좌표 실패를 숨기거나 프리셋을 변경하지 않는다.

## 5. 사용자·배치 쓰기 분리 (D2 확정)

사용자 검색은 `no-store`; 좌표는 등록1회 호출 후 uid 소유 candidate에만 저장한다. 공용 cache는 사용자 경로에서 읽거나 쓰지 않는다. API 키는 서버 전용이며 uid 일100회 제한은 유지한다. Juso 검색/좌표/Vworld 호출량은 별도 기록한다. 서명 캐시 RPC·GEOCODE_CACHE_WRITE_SECRET·DB 관리자키를 Vercel에 추가하는 제안은 폐기했다.

배치는 직접 DB URL로 claim을 먼저 커밋하고 요청·journal·cache를 기록한다. 기존 kakao provider 행과 claims는 재산출·8축 차이·manifest 승인 전 보존한다. `.env.example`과 워크플로우에서 Kakao 사용을 제거하되 실제 .env/Secrets 삭제는 뒤로 미룬다. 대량 교체 후 provenance/기관 위치/reference가 일관된 snapshot을 별도 발행한다.

## 6. 전량 전환·롤백 — 후속 실행

JUSO_COORD_API_KEY 발급 후 새 shadow cache/기관 snapshot·reference를 수집한다. 실 호출 총량/시간/실패/PNU·도형 불일치/원본 hash·R2 객체 의존관계를 manifest로 고정한다. provider 좌표5초10건을 모든 프로세스 합계로 제한하고, full13542·키 삭제·원격 promotion은 별도 보고·승인한다.

promotion 전 old/new snapshot·행수/digest·불변 ID를 검산한다. 실패 시 이전 snapshot/metadata로 복구하며 객체 삭제나 git 이력 재작성은 자동 수행하지 않는다. 리전 이전은 §9 별도 승인이다.

## 7. 채점 비교

v0.3 고정: 반경800m·학교1000m·임대료NULL·exposure0.2.2, cluster.p50=`3.332204510175204`, upper=`7.070653980704802`(p99.97). 상수·가중치·식을 바꾸지 않는다.

| 단계 | 후보 좌표 | 배경/reference | 이번 범위 |
| --- | --- | --- | --- |
| T0 | 기존 S2-4 fixture | 기존 snapshot | 기존 결과 완전 재현 |
| T1 | Juso 검색+Vworld 임시 좌표 | 기존 snapshot | 3곳 8축/총점/신뢰도/순위 차이 |
| T2 | 승인된 Juso 출입구 | 13,542건 교체 후 기관/reference | 좌표 키 발급 후 별도 실행·보고. 무작위5셀 시드20260926 포함 |

T1을 Juso 좌표·전량 교체 완료로 부르지 않는다. PNU/도형 불일치 시 manifest에 사유를 기록하고 후보 기준을 확정하지 않는다.

## 8. 완료 기준·현재 상태

- [x] 실제 Juso 검색+Vworld 3곳 PNU/도형 검증 및8축 T1 보고. [결과](../validation/s3-2-a0-juso-20260930.md).
- [x] `pnpm lint/typecheck/test/test:db`, 기존 T0 재현, 공용 cache 쓰기 차단 검증.
- [x] 원격 최종 dry-run1개 확인 후 사용자 승인으로 push 성공(1.000초). schema/권한·기존13,570행 해시 보존 검증. [적용 기록](../validation/s3-2-a0-juso-20260930.md#원격-migration-적용--2026-09-30).
- [x] D2·공급자 계약·기존 의존성 목록과 해외 제한 원문 확인 내용 문서화.
- [ ] 공개 API 좌표의 해외 저장 적용 범위 공식 답변 확보. 미확정 상태에서 해외 데이터 전환하지 않음.

2026-09-30 착수 시 .env의 JUSO_API_KEY/JUSO_COORD_API_KEY는 없고 VWORLD_API_KEY만 확인했다. 값은 출력하지 않았다. 이후 사용자가 검색 키를 제공하여 Juso 도로명3·지번1·건물명1 검색과 Vworld 좌표3회를 성공했다. 좌표 키는 미발급이며 전량 실행하지 않았다.

## 9. 조건부 Supabase 서울 이전안 — 실행 미승인

국외 저장 제한이 이 서비스에 적용된다는 공식 확인을 받으면 제안한다. Supabase 공식 [리전 목록](https://supabase.com/docs/guides/platform/regions)의 **ap-northeast-2(Seoul)** 새 프로젝트를 사용한다. `icn1`만 지정해서 DB/백업 위치가 바뀌는 것은 아니다.

1. **사용자:** 제공기관의 적용 범위 회신 확보, Vercel Marketplace 관리 조직에서 서울 새 프로젝트 생성 가능 여부·동시 프로젝트 비용/컴퓨트/디스크/백업 위치 확인·승인. 기존 Pro 포함분이 새 프로젝트 비용까지 면제한다고 추정하지 않는다. 새 프로젝트 ref/password/서버용 키는 .env에만 등록.
2. **에이전트 준비:** 쓰기 중지 창과 되돌림 시점을 정한다. 현재 원격의 최신 원천·주소큐·후보/비교·Auth UID/소유권·schema/정책/권한·설정·Vault·webhook을 목록화한다. 예전 S3-1의18테이블 manifest만으로 Auth/사용자 데이터를 복원했다고 하지 않는다. 새 export/추가 manifest와 digest 검증 계획을 먼저 보고한다.
3. **복원 재사용:** `ingest/restore_remote.py`, `restore_manifest.py`, `restore_provenance.py`의7단계 커밋·단계 해시/재개·5만행 COPY·keepalive 구조를 재사용한다. 서울 임시 DB에서 rehearsal→18테이블 digest + 추가 사용자/Auth 데이터 소유권 검증→최종 migration dry-run/전체 manifest·용량 보고→사용자 승인 후 원격 복원. 원본·임시·백업도 승인된 국내 위치로 이동해야 하며 R2/GitHub artifact 위치를 별도 확인한다.
4. **검증:** VACUUM ANALYZE 후6조합 SQL/익명 authenticated HTTP·PNU3곳·8축·RLS/익명 uid 데이터 연결·주소 pending/ready·Realtime 설정을 검증. 외부 webhook은 cutover 전 비활성, 이중 워커 금지. 단계 실패 시 다음 단계로 넘어가지 않는다.
5. **사용자 cutover:** 새 프로젝트 Auth URL/익명 로그인 설정, Vercel의 공개 URL/publishable key 교체와 재배포. 프로젝트 변경 시 이전 세션의 재사용/재인증 및 소유권 보존 결과를 먼저 확인한다. Actions DB URL/ref 및 Vault 토큰은 별도 승인된 대상에 주입하고 검증 창에서만 webhook 활성화한다.
6. **롤백:** 기존 Tokyo 프로젝트/스냅샷은 검증 창 동안 보존한다. 신규 쓰기 이후 단순 URL 복귀로 데이터 유실이 없도록 차분 동기화 계획을 별도 둔다. 성공 후 구 프로젝트·키·공간 원본 삭제도 별도 승인한다.

## 10. 사용자가 처리할 단계

1. 검색용 JUSO_API_KEY 로컬 제공 완료. 실제 Actions 운영 전 해당 검색 키 등록이 필요하며 이번에는 Secrets 값을 변경하지 않았다. 실제 키는 채팅/문서/로그에 넣지 않는다. 좌표용 JUSO_COORD_API_KEY는 별도 발급 후 전량 실행 일정을 결정한다.
2. A0 결과를 검토해 새 fixture·8축 차이와 후속 전량 manifest를 승인한다. 카카오 cache/키 삭제는 그 뒤다.
3. 주소정보누리집 공식 문의에서 §2의 해외 저장 적용 범위를 확인한다. 서울 이전이 필요하면 §9의 프로젝트/비용·복원 manifest·cutover를 별도로 승인한다.
4. #22의 사용자 경로는 A0와 같은 인터페이스로 병행한다. A0 머지 후 데이터 기준을 동기화한다. 이번 A0는 Vercel 환경변수와 실제 Secrets 값을 변경하지 않는다.
