# LEARNINGS — DwgRework

## 2026-10-28
- 데스크탑 앱(Electron) 설계: 파이썬 엔진은 그대로 두고 `userData\{app,runtime}` 로 복사해 bat 패키지와 같은 레이아웃을 유지 → run_pipeline.py 수정 0. 임베디드 파이썬은 `._pth` 때문에 PYTHONPATH 가 무시되므로 app 폴더가 runtime 옆(`..\app`)에 있어야 한다(복사 방식을 택한 이유).
- 자동 업데이트 3층: 스크립트(app.zip, 즉시)·런타임(zip, 작업 없을 때)·셸(Setup.exe /S, 창 숨김+작업 없을 때). zip 해제는 런타임 파이썬 `-I -c zipfile` 로(Node 내장 zip 없음, tar 는 폴백).
- 공개 저장소 배포물에 서버 키를 넣는 설계는 auto mode 분류기가 Credential Leakage 로 차단 → 업로드 엔드포인트를 키 없이(IP 제한·zip 검사) 열고 조회·삭제만 키로 보호. 결과적으로 더 깔끔.
- 사용자 원칙: 생성기는 실행 시 AI 를 쓰지 않는 규칙 코드. 설정 옵션은 "모든 도면 공통"인 것만, 한 도면에서만 필요한 값은 옵션이 아니라 자동 판별 로직. 피드백은 공통/파일 전용 판별 후 코드 반영(docs/FEEDBACK_LOOP.md).
- 새 도면 쌍(A31)은 원본이 XREF 의존 → 원본 DWG 만으로는 처리 불가. 인수 시 "XREF 바인딩본 또는 XREF 파일 동봉" 을 요구해야 함.
- 함정 재발: Bash heredoc 으로 한글·백슬래시 문서를 쓰면 `\a`→벨, `\n`→줄바꿈, `\t`→탭 오염(README 깨짐). 문서·코드 패치는 Edit/Write 도구로. MSYS 에서 `taskkill /F` 는 `/F` 가 경로로 변환돼 실패 → PowerShell `Stop-Process`. Electron `minWidth` 는 저장된 bounds 를 키워 주지 않음 → `Math.max` 로 직접 보정.
- 검증 패턴: 앱을 `--remote-debugging-port` 로 띄우고 CDP(Runtime.evaluate `window.girder.*`, Page.captureScreenshot)로 무GUI 조작·스크린샷. 설치본과 dev 앱은 같은 userData·단일 인스턴스 잠금을 쓰므로 둘 중 하나만.

## 2026-10-28 (색 기준 일반화, v1.1.3)
- 새 도면 쌍(A31)으로 1단계를 레이어명(CON/COL/CEN)에서 벗어나 공통 규칙으로 바꿈: 노랑=골조, 일점쇄선·축선 레이어=중심선, OPEN 레이어+문자. 두 참조 모두로 검증해야 과적합을 피할 수 있었음(빨강만 쓰면 1차 45%, 선종류 쓰면 95%).
- 참조(사람 작업)끼리도 규칙이 다르다: 1차 참조는 하위 블록 중심선 포함, A31 참조는 세대 블록 내부 제외 → "반복 부품 블록(같은 층 2회 이상·층 크기 30% 미만) 안의 중심선 제외"가 둘을 가장 잘 설명. 블록 인스턴스는 삽입점이 아니라 내용 중심·크기로 기록해야 층 배정이 맞음.
- XREF 원본은 ezdxf.xref.embed 로 블록에 심고(DWG 는 dwg2dxf 로 임시 변환), XCLIP 은 전개 때 대표점 기준으로 잘라냄. FOEM(도면틀)은 DXF 버전이 높아 결합 실패해도 무방.
- 2단계 비교: 라멘 층(2~4층)은 참조와 800mm 기준 86% 일치, 지하(무량판)·주거(벽식)는 설계 선택이라 명령문 규칙과 다름 → 도면 전용 판정(feedback_judgments/A31_2026-10-28.md). 보 간격·거더 축선 정렬은 전문가 확인 항목.
- 숫자 없는 층 제목(PIT)은 층 번호로 쓰지 말고 시트 배치 순서로 끼워 넣어야 지지층이 맞음(0층으로 두면 1층 아래로 들어감).

## 2026-10-28 (3단계 MGT, 샘플 4종, v1.2.0)
- MGT 문법은 공식 Quick Reference 만으로는 필드 순서가 애매했고, GitHub 의 STKO MidasGenImporter 파서(parser.py)와 그 Examples 의 실제 내보내기 .mgt 를 템플릿으로 써서 확정(NODE/ELEMENT BEAM·WALL/MATERIAL CONC DB/SECTION DBUSER SB/THICKNESS VALUE/STORY/CONSTRAINT/GROUP 이어쓰기 ` \`). FRAME-RLS 만 실례가 없어 Quick Reference 필드 순서대로 작성(미검증).
- 층 덩어리를 골조+중심선으로 만들면 도로 축선(빨강 CEN)이 층 사이를 이어 붙여 두 층이 한 덩어리가 됨 → 노랑 골조만으로 묶고, 제목은 층 표시가 있는 문자만. 제목 없는 작은 덩어리(범례·상세)는 층이 아님.
- 샘플 투입은 "큰 틀이 깨지는 지점"을 바로 드러냄: ezdxf 블록 이름 금지 문자(F?1), XREF 없는 DXF, 같은 행 가로 배치. 매번 샘플 4종을 회귀로 돌릴 것(`run_pipeline.py` 10초~2분).
- 앱 dev 테스트 전 `release.py --dry` 로 pkg/app 을 갱신해야 함: dev 앱은 설치본(pkg/app) 버전이 더 높으면 userData/app 을 덮어써서 수작업 복사가 사라진다.
