# 피드백 → 판별 → 코드 갱신 루프

생성기는 실행 시 AI 를 쓰지 않고 미리 작성된 규칙 코드(stage1_select / stage2_model / stage2_gen)로 원본을 처리한다.
따라서 피드백은 **코드(규칙)를 고치는 재료**이며, 특정 도면 하나를 맞추기 위한 땜질은 하지 않는다.

## 1. 가져오기 (개발 PC, 이 채팅에서 "피드백 가져와")
```
python dist_build/pull_feedback.py
```
→ `feedback/<id>/` 에 `피드백.txt`(내용·구분·종류·자동 분류·대상 도면), `files/`(원본 DWG/DXF + 결과 DXF + report), `config.json`, `logs/`, `meta.json`. 목록 `feedback/INDEX.md`.
- 피드백은 두 경로로 들어온다(v1.3.1): **작업 카드**(meta kind=feedback, 원본·결과 첨부) / **도면 작업 없이 보낸 피드백**(앱 사이드바·빈 화면·트레이 "피드백 보내기", meta kind=general, 첨부 없음, 사용자가 종류 `category` 선택: ui=프로그램 화면·기능 / rule=생성 규칙·결과 / unknown).
- 앱과 `pull_feedback.py` 가 같은 키워드로 내용을 자동 분류(`category_auto`: ui/rule/unknown — `desktop/renderer/classify.js` 와 `pull_feedback.py` 두 곳 동시 수정). INDEX 종류 열: `오류보고` / `프로그램(UI·기능)` / `일반(규칙 의견)` / `피드백(UI·기능 의심)` / `피드백`. 자동 분류는 힌트이며 최종은 내용을 읽고 판정한다.

## 2. 판별 (피드백 1건마다 `feedback/<id>/판정.md` 작성, 첫 줄이 판정)
| 판정 | 기준 | 조치 |
|---|---|---|
| **프로그램 변경** | 내용이 도면 생성 규칙이 아니라 **프로그램 화면·기능**에 관한 것: 버튼을 다른 곳으로 옮기고 싶다, 목록·상세 배치(레이아웃)를 바꾸고 싶다, 기능 추가·수정, 설정 옵션 요청 등. INDEX 종류가 `프로그램(UI·기능)`·`피드백(UI·기능 의심)` 이면 1차 후보 | `desktop/`(renderer·main·lib) 수정 → dev 앱(`npm start`, CDP 스크린샷)에서 해당 화면 확인 → `release.py <버전> "…(피드백 id)" --shell`(설치본 재빌드, 사용자 PC 는 창을 닫을 때 무인 설치). 판정.md 첫 줄 `프로그램 변경 → 반영(v…)`. 규칙 회귀 불필요(엔진 미변경) |
| **공통 규칙** | CAD 일반 관행·명령문(1단계: 노랑=골조, 빨강=중심선, OPEN X / 2단계: 기둥 중심, 인접 기둥만, 6m 초과 2등분, 비지지 표시)으로 설명되고, 보유한 **다른 도면들에도 같은 규칙이 성립**(재현 실행으로 확인) | 코드·기본값 수정 → 전체 도면 회귀 비교(정확도 하락 없음) → 배포(CHANGELOG 에 피드백 id) |
| **이 도면 전용** | 그 도면의 특수 레이어명·작도 습관·찌꺼기에 의존 | 코드 미변경. 판정.md 에 사유 기록. 같은 패턴이 3건 이상 쌓이면 "공통 후보"로 재검토 |
| **보류** | 재현 불가·정보 부족 | 사용자에게 추가 질문(어느 층·어느 위치·기대 결과) |

사용자가 고른 구분(모든 도면/이 도면만/모름)은 참고값일 뿐, 최종 판정은 위 기준으로 한다. 사용자는 비전문가일 수 있으므로 "모름"이 기본.

## 3. 설정 옵션 추가 원칙
- 앱 설정 화면에는 **모든 도면에 공통으로 의미 있는 옵션**만 추가한다(예: 거더 분할 기준 길이). 도면마다 바꿔야 하는 값은 옵션이 아니라 자동 판별 로직으로 만든다.
- 현재 노출 옵션(v1.4.0, 피드백 3765c4): `실행_단계`(1/2/3), `보_생성`, `보_기준_거더길이`, `보_베이폭_최소`, `보_베이폭_2개`, `보_베이폭_3개`, `MGT_층고`(v1.4.1), 4단계 `검토_*` 23개(v1.5.0, 피드백 1d7f01: fck·fy·피복·철근·스터럽·하중조합·단위·추천 증분/상한). 노출 키와 검증 규칙(type/min/max/정규식)은 `desktop/lib/engine.cjs` SETTING_SPEC 한 곳, 화면은 `renderer/index.html` #info(.nums 숫자 / .texts 텍스트·select). 새 옵션 = config.json 키 + cfg.DEFAULT + SETTING_SPEC + 화면 입력 1줄.
- 한 도면에서만 필요한 값은 옵션으로 만들지 않는다.

## 4. 회귀 자료
- `data/` 의 도면 쌍(원본·수작업 참조본)으로 compare1 / stage2_run 비교. 새 도면 쌍이 오면 `data/<이름>/` 에 두고 README 의 비교 절차로 정확도를 기록한다.

## 5. 자동 오류 보고(피드백과 별개, v1.2.2)
- 작업 실패 시 `run_pipeline.py` 가 보고서 끝에 `[원인] 입력 — …` 또는 `[원인] 오류 — …` 를 쓴다.
  - 입력: 참조(XREF) 파일 없음(빠진 이름 표시)·노란 골조 선 없음·DWG 변환/DXF 읽기 실패. 카드에 조치 안내만 보이고 전송하지 않는다(사용자가 파일을 갖춰 다시 실행).
  - 오류: 그 외 단계 실패·예외. 앱이 보고서·로그·원본 도면을 서버로 자동 전송(메타 kind=error). 오프라인이면 다음 실행 15초 뒤 재시도.
- 이 PC: `pull_feedback.py` 가 같은 폴더에 받고 INDEX 의 종류 열에 "오류보고"로 표시. 처리 원칙 = 원본으로 재현 → 코드 수정 → 샘플 회귀 → 배포. 판정.md 는 "오류 수정" 한 줄.

## 6. 채팅 명령 "피드백 반영하여 업데이트 해줘" (2026-10-29 지시, 되묻지 않고 끝까지 자동)
이 PC 의 Claude 세션에서 이 명령을 받으면 아래를 질문 없이 순서대로 수행한다(Bash 도구, cwd 이 폴더, `PYTHONUTF8=1`).
1. 가져오기: `python dist_build/pull_feedback.py` → `feedback/<id>/` + INDEX.md. 0건이면 "0건" 보고로 끝.
2. 원인 파악(건마다):
   - 오류보고(meta.json kind=error): `files/` 원본으로 `python run_pipeline.py <원본> --out <임시폴더> --keep` 재현 → report 의 `[원인]` 줄·traceback → 수정.
   - 피드백: 피드백.txt(구분·종류·자동 분류·대상·내용)+결과 DXF·report 를 읽고 2절 기준으로 **공통 규칙 / 이 도면 전용 / 프로그램 변경 / 보류** 판정, `feedback/<id>/판정.md` 첫 줄에 판정과 근거.
   - 프로그램(UI·기능) 요청(INDEX 종류 `프로그램(UI·기능)`·`피드백(UI·기능 의심)`, pull_feedback 가 끝에 "※ … 미판정 N건" 으로 알림): 내용을 읽어 정말 화면·기능 요청이면 **프로그램 변경** 판정 → 요청대로 `desktop/` 를 수정(버튼 위치·레이아웃·목록 배치·기능 추가). 도면 결과 이야기였으면 규칙 판정으로 되돌린다. 요청이 모호하면(어느 버튼·어디로) 보류 + 질문.
3. 코드 수정: 공통 규칙·오류 수정만(한 도면 땜질 금지, 3절 옵션 원칙). 엔진(.py·config.json)만이면 app.zip, `desktop/` 변경이면 `--shell`, `server/` 변경이면 `server/` 에서 `railway up --detach`.
4. 회귀: 피드백 원본 재실행 성공 + `data/1.dxf`(1차) + `data/a31/bound.dxf`(A31) `run_pipeline.py` 성공. 규칙이 바뀌었으면 compare1 / compare_a31 로 정확도가 떨어지지 않았는지 확인. 프로그램 변경만이면 엔진 회귀 대신 dev 앱 기동(`release.py --dry` 로 pkg/app 갱신 후 `npm start -- --remote-debugging-port=9222`)·CDP 스크린샷으로 바뀐 화면 확인, 테스트 뒤 HKCU Run 의 `electron.app.Electron` 제거.
5. 배포: 버전 = `latest.json` app_version 의 patch +1(규칙 변경은 minor +1). `python dist_build/release.py <버전> "변경 내용(피드백 id)" [--shell]` → Release·latest.json·CHANGELOG·git push 까지 자동.
6. 서버의 피드백은 삭제하지 않는다(가져가면 '가져감' 표시만). 보류 건은 배포에서 제외하고 결과에 전문가에게 물을 질문을 적는다.
7. 보고: 결과표(id·종류·판정·수정 내용·배포 버전) → 꼭 알아야 할 내용 → 수동 지시(있을 때). 배운 점은 `docs/LEARNINGS.md` 에 append.

## 7. 4단계 구조 검토(v1.5.0, 피드백 1d7f01 + 전문가 답변 11-09)
- 흐름: 3단계 MGT 생성에서 작업이 끝남(그대로). 완료 카드의 **4단계 구조 검토** 에서 전문가가 MIDAS 해석 결과표(Beam Force 텍스트/CSV)를 첨부 → `stage4_check.py` 가 요소 대응표(`<이름>_MIDAS_elements.json`, stage3 가 함께 저장)로 부재를 식별해 KDS 14 20 검토 → `check.json` + 엑셀. NG 중 치수 변경이 있으면 **승인 → 수정 MGT**(`stage4_apply.py`: *SECTION 치수만, 철근은 쓰지 않음).
- 결과표 파서는 실제 MIDAS 샘플 없이 표준 열(Elem/Load/Part/Axial/Shear/Torsion/Moment, 한글 머리글 포함, 탭·CSV·공백, 단위 머리글)을 기준으로 만들었다. 파싱 실패는 **자동 오류 보고(meta.stage=4, 결과표 첨부)** 로 들어오므로 `feedback/<id>/files/` 의 결과표로 `python stage4_check.py <elements.json> <결과표> <폴더>` 재현 → 파서 수정 → `stage4_selftest.py` 통과 → app.zip 배포.
- 회귀: `python stage4_selftest.py <elements.json> <mgt> <폴더> [--heavy]` — 가상 결과표 4형식(탭 kN·mm / CSV kN·m / 공백 / 조합 이름)이 같은 OK·NG 수를 내고 승인 MGT 가 만들어지면 PASS. elements.json·mgt 는 `run_pipeline.py data/a31/bound.dxf --out <폴더>` 결과를 쓴다.
- 설정 오류(철근 표기 등)·입력 오류(모델 MGT 를 결과표로 첨부 등)는 입력 문제로 카드에 안내만, 그 외 실패는 오류 보고. 검토값은 참고용이며 엑셀 요약 시트에 그 문구와 적용 설정을 함께 기록한다.
- **첫 실제 MIDAS 샘플(11-10, 1d7f01 답변 5)**: `feedback/20261109_104038_1d7f01/files/답변5_샘플_250930 흑석동 어린이집 Modeling.mgt`(MIDAS Gen 9.7.5, **KN·M**, 148 요소, C1(500x500)/G1(400x600)…/B7(400x600), 더미 재료·단면 9999, *DGN-SECT·*REBAR-BEAM·*DGNCRITERIA·*LOADCOMB gLCB5=1.4D·gLCB6=1.2D+1.6L). 거기서 확인·반영한 것: ① SB 치수 순서 H(춤)·B(폭) 확정 ② `stage4_apply.py` 는 *UNIT 길이 단위로 치수를 쓰고(M 이면 0.6), 새 단면명은 전문가 표기 `G4(500x600)`(폭x춤)이며 기존 번호(G2 등)를 건너뛰고, *DGN-SECT 가 있으면 거기에도 같은 줄을 추가 ③ `stage4_check.py` 는 모델 MGT 가 결과표로 들어오면 `입력 오류` 로 끝냄(engine.cjs failKind=input). 외부 모델은 `python mgt_import.py <모델.mgt> <_elements.json>` 으로 요소 대응표를 만들어 `stage4_selftest.py <_elements.json> <모델.mgt> <폴더> [--heavy]` 회귀에 그대로 쓴다(이 샘플: 128 요소, 기본 OK 124/NG 4, heavy 치수 변경 22, PASS). MIDAS 실제 임포트·해석 결과표는 아직 미수신.

- **4단계 단독 실행(v1.6.0, 11-11)**: 실제 업무 순서는 1·2·3단계 → 캐드·MIDAS 수작업 → 4단계다. 4단계는 도면 작업과 분리된 작업 종류(`kind: 's4'`)로, 모델 MGT 를 `mgt_import.py` 가 읽어 요소 대응표를 만들고(결과 폴더에 모델 사본 고정) 그 카드에서 결과표 첨부 → 검토 → 승인한다. 도면 작업 카드에서는 `runStage4` 를 거부한다(수작업 후 요소 번호 불일치 방지). 모델 읽기 실패는 `[원인] 입력 — …`(MGT 아님, 검토할 요소 없음) = 카드 안내만, 그 외 = 자동 오류 보고(모델 첨부). 회귀 = `mgt_import.py <모델> <elements.json>` → `stage4_selftest.py <elements.json> <모델> <폴더> [--heavy]`(수정 MGT 가 원본 줄·한글을 보존하는지도 검사) + 엔진 Node 테스트. 회귀 모델 = `feedback/20261109_104038_1d7f01/files/` 의 답변5_샘플·수작업샘플 3종.
- **실제 MIDAS 결과표 형식(11-11, 전문가 화면으로 확인)과 읽기 규칙(v1.6.1)**: 표 위 제목 줄, 앞 두 열 빔, 열 23개(Member·Elem·Load·Stage·Step·Step Order·Part·Part Order·Component·Axial·Shear-y·Shear-z·Torsion·Moment-y·Moment-z·Bi-Moment·T-Moment·W-Moment·Load Order·Compo Order·Stress), 머리글 칸 안에 줄바꿈, 단위 (kN)·(kN·m), 하중 "RC ENV_STR(all)", 위치 I[39]·J[87]. CSV 는 따옴표 안 줄바꿈 때문에 줄 단위 읽기 금지 → `csv.reader` 로 파일 전체를 읽은 줄 목록과 비교해 머리글 열을 더 많이 찾는 쪽을 쓴다. 엑셀(.xlsx)은 `xlsx_sheets()`(표준 라이브러리). 부재력 열을 못 찾거나 값이 전부 0 이면 결과를 만들지 않는다 — "조용히 전 부재 OK" 는 가장 위험한 실패. selftest 의 MIDAS 형태 CSV·엑셀(`MIDAS_HDR`)이 이 형식의 회귀.
