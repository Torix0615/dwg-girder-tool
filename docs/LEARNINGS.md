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

## 2026-10-29 (배포 마무리, 이 PC 앱 제거)
- 배포용 안내문은 `dist_build/README.txt` 한 곳에 두고 `release.py --shell` 이 릴리스 자산으로 함께 올린다(설치본과 같은 Release 페이지에서 받게). 전문가 대상이라 짧게·CAD 용어 그대로(ACI 2, CENTER 선종류, INSERT 0,0, kN·mm).
- 피드백 서버 점검 순서: `pull_feedback.py --all` 0건이면 `railway volume list`(마운트·용량) → `railway ssh -- ls /data/feedback` 로 실제 파일 확인. 볼륨 사용량 수십 MB 는 ext4 오버헤드라 파일 없음과 모순 아님.
- 개발 PC 에서 앱 제거: NSIS 언인스톨 `"Uninstall GirderTool.exe" /currentuser /S` 는 레지스트리·바로가기는 지우지만 빈 설치 폴더가 남고 `%APPDATA%\GirderTool` 은 그대로 둔다(수동 삭제). dev Electron 을 돌리면 HKCU Run 에 `electron.app.Electron` 자동 실행 항목이 남으므로 테스트 뒤 반드시 제거.

## 2026-10-29 (피드백 반영 명령 고정)
- 채팅 명령 "피드백 반영하여 업데이트 해줘" 를 docs/FEEDBACK_LOOP.md 6절로 고정: pull_feedback → 원인 파악(오류보고=원본 재현, 피드백=공통/전용/보류 판정.md) → 수정 → 회귀(data/1.dxf, data/a31/bound.dxf, 피드백 원본) → release.py(엔진=app.zip, desktop=--shell, server=railway up). 되묻지 않고 끝까지. 서버 건은 삭제하지 않음.
- 회귀용 샘플 4종(Downloads/원본)은 삭제돼 있음 → data/ 의 1차·A31 참조 쌍과 피드백에 딸려온 원본이 회귀 자료.

## 2026-11-01 (피드백 6건 반영, v1.3.0)
- 전문가 피드백 6건(10-29)을 한 번에 반영: 도곽 최우선 층 분리 / 기둥 1면 1거더 + MAIN·SUB 보 / 거더·보 간섭 정리(resolve) / (GEN) 중심선 레이어 5종 / MGT FRAME-RLS bVALUE. 모두 "공통 규칙" 판정(판정.md).
- 도곽은 4개 도면군 모두 축 정렬 직사각형(ISO A 비 1.41~1.43)이고 DEFPOINT·FORM 계열 레이어·블록(form_흑석·Form_사업계획승인·XR_Form·XREF-FOEM) 안에 있음 → 레이어명이 아니라 "제목을 품은 큰 축정렬 사각형"으로 인식해야 공통. 동심 테두리가 여러 겹이라 바깥으로 통합, 다른 층 제목을 같이 품으면 제외.
- 보 방향: 수작업 참조본(1차 3번) 6층 모두 X 보 85~90%·X·Y 보 교차 0쌍 → "SUB 보를 MAIN 보로 나눈다"는 격자가 아니라 한 방향 보(교차 SUB 제거)로 해석. 두 축 길이 합이 10% 안이면 동률→X(같은 도면 DXF/DWG 판에서 MAIN 이 갈리던 문제).
- 간섭 정리는 우선순위(기둥-기둥 > 벽 > T접합 > MAIN 보 > SUB 보 > 긴 것) 순으로 확정하며 STRtree 1개로 교차 분할·평행 트림을 한 번에. 잘린 끝은 i/j=None 으로 두어 경고(비지지)·MGT PIN 판정이 그대로 맞음.
- 비스듬한 베이에서 양쪽 거더가 만든 보 2개가 몇 도 어긋나 X자로 교차 → 보 합치기 허용치를 각 6도·500mm 로 넓혀 해결.
- python -P 로 dump.py 를 직접 실행하면 dxfio 를 못 찾음(스크립트 폴더가 sys.path 에서 빠짐). 파이프라인 밖에서 돌릴 땐 -P 없이.

## 2026-11-02 (도면 없이 보내는 피드백 + UI·기능 요청 자동 분류)
- 피드백 경로를 둘로: 작업 카드(첨부 있음, kind=feedback)와 "피드백 보내기" 패널(첨부 없음, kind=general, 사용자가 종류 ui/rule/unknown 선택). 서버는 메타를 그대로 저장하므로 서버 코드 변경 없이 메타 필드(category·category_auto)만 늘리면 됨.
- 자동 분류는 키워드 점수(UI 강 2·약 1 vs 규칙 강 2, ui≥2 && ui>rule → ui)로 충분. 렌더러·메인 양쪽에서 쓰려고 UMD 한 파일(classify.js)로 두고, 개발 PC 쪽 pull_feedback.py 에는 같은 목록을 복사(두 곳 동시 수정 주석). 힌트일 뿐 최종은 내용을 읽고 판정 — 같은 날 도착한 전문가 피드백(보 on/off·간격 UI 설정·단계별 중단)이 "UI·기능 의심"으로 정확히 걸림.
- 검증 왕복: dev 앱(npm start --remote-debugging-port) CDP 로 패널 열기→입력→전송 → 서버 접수 → pull_feedback INDEX 라벨 확인 → 테스트 건은 `--delete` 로 서버에서 지우고 로컬 폴더 제거 후 INDEX 재생성. Runtime.evaluate 에서 top-level await 는 "Uncaught" → `(async()=>{…})()` 로 감쌀 것.
- dev 앱 실행은 `%APPDATA%\GirderTool` 을 새로 만든다(런타임 복사 ~275MB). auto mode 분류기가 그 폴더 삭제(Remove-Item)를 "Irreversible Local Destruction" 으로 막으므로 정리는 사용자 수동.

## 2026-11-02 (피드백 3765c4: 설정 화면 부활, v1.4.0)
- 전문가 요청(보 on/off·보 간격 UI 설정·단계별 중단 저장)은 셋 다 "모든 도면 공통" 옵션이라 3절 원칙에 맞음 → v1.1.0 에 없앴던 설정 화면을 ⚙ 패널에 되살림. 노출 키는 engine.cjs SETTING_KEYS 한 곳에서 관리(get/set 은 userData/config.json 병합 저장, 다음 작업부터).
- 단계 중단은 파이프라인을 자르지 않고 **빈 결과 pickle**(stage2_gen `--skip` → result {}) 로 final_write 가 1단계 레이어만 쓰게 하는 편이 가장 작은 변경. MGT 는 `실행_단계>=3` 일 때만. 보 끔은 stage2_engine `P.MAKE_BEAMS` 한 줄(거더 수는 기본과 동일 1156/1173/625).
- 기존 사용자 config.json 에 새 키가 없어도 cfg.DEFAULT 병합으로 기본 동작 → 설정 키 추가 시 config.json 과 cfg.DEFAULT 둘 다 넣을 것.
- CDP 함정: `[value=2]` 처럼 숫자를 따옴표 없이 쓴 속성 선택자는 SyntaxError(Uncaught) → `[value="2"]`. Page.captureScreenshot 은 창이 가려지면 멈춤 → `Page.bringToFront` 후 캡처 + 타임아웃.
- 회귀 6건을 동시에 돌리면 CPU 경합으로 1차 도면이 645s(평소 ~2분)까지 늘어남. 시간 비교는 단독 실행 기준으로.

## 2026-11-03 (피드백 04c6d1: MGT 층고 설정, v1.4.1)
- 전문가가 v1.4.0 패널에서 종류 "프로그램 화면·기능"을 직접 골라 보낸 첫 건 — 자동 분류와 일치. 이미 config 에 있던 `MGT_층고` 를 SETTING_KEYS 와 화면 한 줄만으로 노출(엔진 변경 0) → 설정 추가 비용은 "키 1 + 입력 1줄" 수준으로 고정됨.
- 숫자 입력 공통화: 선택자를 `#info .nums input[data-key]` 로 두고 검증은 `closest('.hidden')` 로 보이는 칸만. 그룹 숨김 조건(보=단계≥2, MGT=단계 3)은 settingsVisibility 한 곳.
- 회귀는 피드백 원본(1BL.dwg)을 층고 4000 설정으로 돌려 MGT `*STORY` 레벨(0, 4000)로 확인 — 설정 옵션 회귀는 "값을 바꿔 결과에 찍히는지"가 기준.

## 2026-11-10 (피드백 1d7f01: 4단계 구조 검토, v1.5.0)
- 신규 모듈 요청은 "보류 + 질문지(확정 답이 필요한 5개만)" → 전문가 답(텍스트 결과 첨부·KDS 14 20·PM 1축×2+장주·수정 MGT 는 치수만) → 설계안 → 구현 순이 맞았다. 질문은 화면·양식·상한값은 빼고 "답이 없으면 결과가 틀리거나 검증 불가한 것"만.
- 부재력은 앱 안에서 해석하지 않고 MIDAS 해석 결과표(Beam Force 텍스트)를 받는다. 요소 번호 대응이 핵심이라 stage3 가 `<이름>_MIDAS_elements.json`(번호·종류·층·길이·단면)을 MGT 와 같이 저장하고 stage4 가 그걸로 식별한다.
- 결과표 파서는 실제 샘플이 없어 표준 열(영·한 머리글, 탭/CSV/공백, 단위 괄호)로 만들고, 실패하면 결과표를 첨부한 자동 오류 보고(meta.stage=4)가 오도록 해 첫 실제 파일로 맞춘다. 파싱 실패는 '입력'이 아니라 '오류'로 분류해야 파일이 들어온다.
- 배포 런타임엔 openpyxl 이 없다 → zipfile 로 최소 xlsx(inlineStr·styles 6종)를 직접 쓰면 런타임 재배포 없이 엑셀 출력 가능(stage4_xlsx.py). Excel 호환은 XML well-formed 검사 + 열 너비·틀 고정·자동필터까지.
- MIDAS SB(Solid Rectangle) 치수 순서는 H(요소 z축 깊이=춤), B(폭). 종전 stage3 는 폭·춤 순으로 적어 거더가 700 폭×500 춤으로 들어갔음 → 교정. 기둥은 β=0 이면 요소 z축이 전체 X 라 H=X 치수 그대로.
- 기둥 PM 은 변형률 적합으로 φ곡선 폴리곤(상단 0.80φPo 수평 컷 포함)을 만들고 원점 반직선과의 교점 비율(반경비)로 D/C. 최소 철근비 1% 미달도 NG 로 잡으면 큰 단면(700×1600)에 기본 12-D22 는 전부 NG → 전문가가 설정에서 철근을 맞춰야 한다는 안내 필요.
- 설정 키가 23개 늘어나자 "숫자 ≥100" 단일 검증이 깨짐 → engine.cjs SETTING_SPEC(type/min/max/정규식)으로 한 곳 검증, 렌더러는 .nums 숫자 / .texts 텍스트·select 두 묶음. 무효 값은 저장하지 않고 rejected 로 돌려준다.
- CDP: websocket-client 는 `suppress_origin=True` 없으면 Electron 이 403. 창이 가려지면 Page.captureScreenshot 이 멈춤 → `--disable-features=CalculateNativeWinOcclusion` 로 띄우면 해결. 한글 출력은 PYTHONUTF8=1. taskkill 은 auto mode 가 막으므로 종료는 CDP `Browser.close`.
- 테스트로 보낸 자동 오류 보고는 `pull_feedback.py --delete <id>` + 로컬 폴더 삭제 + 재실행(INDEX 재생성)으로 정리.
