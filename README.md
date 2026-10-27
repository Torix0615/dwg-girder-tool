# 지하주차장 평면도 DWG → 골조 추출(1단계) → 거더·보 생성(2단계) 재작업 (2026-10-27)

입력 3개(Downloads): 1번=원본 평면도, 2번=1단계 수작업 결과(back), 3번=2단계 수작업 결과(S-711).
DWG→DXF 변환: `..\libredwg\dwg2dxf.exe -y -o data\N.dxf <dwg>` (1번 4초, 2번 90MB 25초).

## 한 번에 실행(매크로) — 새 원본 DWG/DXF 용
- 바탕화면 `골조_거더보_생성.bat` 위에 DWG/DXF 를 끌어다 놓으면 `<이름>_골조거더보.dxf` + `_report.txt` + 층별 도면 HTML 2개가 원본 옆에 생김(여러 파일 동시 가능, 17MB DWG 기준 약 3분).
- 명령: `python run_pipeline.py <원본> [--out 폴더] [--config config.json] [--html] [--keep]` (--keep 이면 work\<이름>\ 중간 피클 보존 → compare1/stage2_run 으로 참조 비교 가능).
- 규칙값은 `config.json` 에서 수정(레이어명·층 블록 정규식·거더/보 파라미터·출력 폭·레이어명). `_` 로 시작하는 키는 설명. 층 블록을 못 찾으면 1단계에서 멈추며 메시지로 알려줌.
- 진단(10-27 저녁 보강): `<이름>_골조거더보_report.txt` 는 시작 직후 생성되어 단계마다 갱신되고, 어느 단계에서든 실패하면 원인(오류 출력·예외)을 기록. report 가 아예 없으면 run_pipeline 이 시작조차 못 한 것(bat 창 메시지 확인). bat 는 ASCII+CRLF, python 은 `C:\Python314\python.exe` 절대 경로(없으면 PATH 의 python).
- 결과 DXF 는 원본 미포함·블록 7개(B1~B6_골조·1F_골조)·GROUP 이라 CAD 에서 블록 편집 또는 EXPLODE 후 수정 가능. 원본 위에 겹쳐 보려면 결과를 XREF/INSERT(0,0).

## 배포(다른 사람에게 주기) + 자동 업데이트 + 피드백 — desktop\ · dist_build\ · server\
**상대에게 주는 것 = 설치본 1개** `GirderTool-Setup-<버전>.exe`(Releases, 런타임 포함 ~170MB). 더블클릭 설치 → 트레이 상주 앱(항상 위 창, 최소 900×600).
- 앱(desktop\, Electron 33 + electron-builder NSIS, 바닐라 HTML/JS): 빈 화면 "작업 시작" → 탐색기에서 도면 1개 → 왼쪽 작업 목록 / 오른쪽 진행률·"결과 DXF 다운로드"(최종 DXF 만) · 피드백(모든 도면 공통/이 도면만/모름 + 내용 → 전송, 전송 후 잠금). 설정 화면 없음(규칙값은 모든 도면 공통 내부 기본값, 전문가 피드백에 따라 옵션 추가). ⚙=업데이트 확인·버전·데이터 폴더.
- 데이터 폴더 `%APPDATA%\GirderTool\` = app\(스크립트, 첫 실행 때 설치본 resources\engine 에서 복사) · runtime\(임베디드 Python+dwg2dxf, `python314._pth` 에 `..\app` 필수) · results\<작업>\(최종 DXF·report) · jobs.json · desktop.log · config.json.
- 자동 업데이트 3층(lib/updater.cjs, 시작 5초 후·3시간마다, `latest.json` = GitHub raw, 반영 지연 최대 5분): app.zip(스크립트, 32KB) → 변경 내용 띄우고 즉시 교체(작업 중이면 끝난 뒤) / runtime.zip(드묾) / 셸 Setup.exe(shell_version·sha256) → 받아 두고 창이 숨겨지고 작업이 없을 때 무인 설치(/S) 후 `--hidden` 재기동(SyncNote 방식).
- 피드백 서버(server\server.js, 의존성 0, Railway 프로젝트 `dwg-feedback` 볼륨 /data, 주소 `https://dwg-feedback-production.up.railway.app`): 업로드 `POST /api/feedback` 는 키 없음(IP당 시간당 10건·600MB 제한, 앱 배포물에 비밀값을 넣지 않기 위함), 목록·다운로드·삭제는 `x-key`(Railway 변수 FEEDBACK_KEY = `dist_build/secrets.json` feedback_key, git 제외). zip 내용 = 피드백.txt(구분·대상·내용) + files\(원본 DWG/DXF·결과 DXF·report) + config.json + logs + desktop_log.txt.
- 이 PC 에서 가져오기: `python dist_build\pull_feedback.py` → `feedback\<id>\` + `feedback\INDEX.md`. 판별(공통 규칙 → 코드 반영 / 이 도면 전용 / 보류)·코드 갱신 절차는 `docs\FEEDBACK_LOOP.md`.
- 새 버전 내기(이 PC, gh 로그인, Bash 도구에서 — PowerShell 은 한글 인자가 깨짐): 스크립트만 고치면 `python dist_build/release.py 1.1.1 "변경 내용"`(32KB, 상대는 다음 실행 때 자동), desktop\ 코드를 고치면 `--shell`(electron-builder 빌드 수 분, Setup.exe 첨부, 상대 PC 는 창 숨김 때 무인 설치), 런타임 바뀌면 build_runtime.py 후 `--runtime`, bat 패키지 전체 zip 은 `--full`, `--dry` 는 파일만.
- 서버 배포: `server\` 에서 `railway up --detach`(이 폴더가 dwg-feedback 프로젝트에 링크됨). 변수 변경 후엔 redeploy.
- 개발 실행·무GUI 검증: `desktop\node_modules\.bin\electron.cmd . --remote-debugging-port=9333` 후 CDP(Runtime.evaluate `window.girder.*`, Page.captureScreenshot). 설치본과 같은 userData 를 쓰므로 설치본 테스트 전엔 dev 앱 종료.
- (구) bat 패키지 `골조거더보\`(dist_build\template, `--full` zip)도 유지: updater.py·feedback.py 는 앱과 공용.

## 실행 순서(PowerShell, 폴더 `C:\Users\taeju\Tools\DwgRework`, `$env:PYTHONUTF8=1`)
```
python dump.py data/1.dxf out/d1.pkl --msp                                  # 원본 전개(1.5M 프리미티브, 26초)
python dump.py data/2.dxf out/d2.pkl --blocks "^(지[0-9]|지하 ?[0-9]|wl3)" --msp-layers "구조\)"   # 참조 1단계(80초)
python dump.py data/3.dxf out/d3.pkl --blocks "^(지|b[0-9] [fb]|wl3|rrr)" --msp-layers "구조\)|^CEN|^OPEN"  # 참조 2단계
python stage1_select.py out/d1.pkl out/s1_cand.pkl        # 층별·범주별 후보
python compare1.py out/s1_cand.pkl out/d2.pkl --variants --report out/cmp1_v1.txt
python stage1_write.py data/1.dxf out/s1_cand.pkl out/1_1단계.dxf
python stage2_model.py out/s1_cand.pkl out/s2_model.pkl   # 기둥·벽(두께)·동 폴리곤
python stage2_ref.py out/d3.pkl out/s2_model.pkl out/s2_ref.pkl   # 참조 거더·보 → 원본 좌표·중심선
python stage2_run.py out/s2_model.pkl out/s2_ref.pkl out/s2_result.pkl --split 4000 --bwall 250 --report out/cmp2_final.txt
python stage2_write.py out/1_1단계.dxf out/s2_model.pkl out/s2_result.pkl out/1_2단계.dxf
python stage2_diff.py 2 [x0 x1 y0 y1]                      # 불일치 렌더(out/s2_diff_B2_*.png)
python final_write.py out/s1_cand.pkl out/s2_model.pkl out/s2_result.pkl out/최종.dxf   # CAD용 최종(원본 미포함, R2010, 29MB, audit 0)
python render_html.py out/최종.dxf out/html                 # 층별 전체 도면 HTML 2개(1단계/2단계, PNG 6400px 내장)
python compare_html.py out/html/비교_기존완성본_vs_자동생성.html   # 참조(2번·3번) vs 내 결과: 층별 나란히+겹침 차이+정확도 표(74MB)
```

## 산출물(바탕화면 = C:\Users\taeju\OneDrive\바탕 화면)
- `지하주차장_골조_거더보_최종.dxf` — final_write.py 결과(원본 제외, 블록 B1~B6_골조·1F_골조, 좌표=원본 그대로, 층 라벨 TEXT). 원본 포함판은 `out\1_2단계_원본포함.dxf`(122MB, LibreDWG 변환본 기반이라 CAD 호환 미검증).
- `1단계_골조추출_층별도면.html`, `2단계_거더보_층별도면.html` — 층별 PNG(6400px) 내장, 클릭하면 원본 크기 스크롤. Playwright msedge 로 로드·이미지 검증 완료. 렌더 범위는 골조 레이어 bbox(멀리 떨어진 중심선 때문에 세로 28k px 가 되던 문제 해결).

## 확정 규칙
1단계(참조 대비 F1 골조 99.6 / 중심선 99.3 / OPEN 100 %)
- 층 분할: `지하N층 주차장 평면도` 블록 INSERT y(상단) 기준 474,635 간격 띠. 세대 블록(84A-확장… msp 직접 삽입)은 y 띠로 배정.
- 골조 = 유효색 2(노랑)·레이어색 2 이고 레이어 CON·COL 만 (2CONTINUOUS·CO-FIN·AREA-전용 제외: 참조에 0%).
- 중심선 = CEN·CEN-1·CEN-PARK 전체(참조는 벽·기둥 중심선만 고르지 않고 전부 복사).
- OPEN = OPEN 레이어 전체 + 'OPEN' 문자.
- 출력: 층별 블록 `B{N}_골조`(레이어 `----- (구조) 골조/중심선/OPEN`) 를 (−1,000,000, 0) 에 삽입 + GROUP, 나머지 370 레이어 off.
- 참조 2번 파일의 블록 좌표계: 블록 로컬 + INSERT = 원본 좌표 −2,726,199(x). 비교는 수직선 x·수평선 y 차이 최빈값으로 자동 정렬.

2단계(참조 대비 중심선 F1 거더 68 / 보 39 %)
- N층 도면의 거더는 **아래층(N+1) 기둥** 위에 그린다(참조 3번 파일 검증: B2 도면 끝점 65% 가 B3 기둥, B2 기둥은 30%). B6 도면 없음, 1층 바닥(1F)=B1 기둥.
- 참조 거더·보는 2중선: X방향 거더 폭 400, Y방향 500, 보 400. 끝은 기둥 면. 비교는 2중선→중심선 변환 후 길이 커버리지(허용 100mm).
- 기둥 = COL 레이어 닫힌 4점 폴리라인(B1·B2 183, B3 398, B5 537). 축은 사각형 변 방향(7° 회전 구역 다수).
- 인접: 기둥 4축 방향 ±8°(횡 700 허용) 최근접 기둥, 사이에 가로지르는 CON 벽이 있으면 벽 면까지. 기둥 없으면 벽 면, 벽도 없으면 기존 거더에 T 접합.
- 보: 길이 > SPLIT(4000) 거더 옆 띠에서 반대편 경계(거더/구조벽≥250/기둥)까지 D 를 5점 표본으로 재고 D/2 에 평행 보(D≥8.7m 는 2개). X 방향 우선, 교차하는 Y 보 제거. 얇은 벽(200)은 보 경계에서 제외(참조가 무시).
- 동(아파트) 구역 = `DEF-기준층 벽체` 레이어(12m 이하 선)를 1.2m 버퍼→concave_hull(0.3)→−1.2m, 150m² 이상 → 29개(참조 동 Hatch 30개와 면적 93% 겹침). 구역 안 기둥은 주차장 거더에서 제외, `out/dong/동_B{k}_{i}.dxf` 로 분리 저장(같은 규칙 적용).

## 남은 한계(참조와의 차이 원인)
- 참조에는 벽을 따라가는 거더, 기둥이 없는 구간(세대 하부 MIDAS 동 기둥·커뮤니티 시설)의 거더, 곡선 램프 방사형 보가 있어 규칙으로 재현 불가 → 거더 재현 71%.
- 보 재현 38%: 거더가 빠진 베이는 보도 못 만듦(상한=거더 재현), 참조 8.4m 베이 중 22% 는 3등분(2개) 인데 구분 기준 없음, 참조 보 12% 는 Y 방향.
- B5 참조(지하 5 열)는 부분 작성(거더 736개)이라 B5 점수는 참고용.
