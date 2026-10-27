# LEARNINGS — DwgRework

## 2026-10-28
- 데스크탑 앱(Electron) 설계: 파이썬 엔진은 그대로 두고 `userData\{app,runtime}` 로 복사해 bat 패키지와 같은 레이아웃을 유지 → run_pipeline.py 수정 0. 임베디드 파이썬은 `._pth` 때문에 PYTHONPATH 가 무시되므로 app 폴더가 runtime 옆(`..\app`)에 있어야 한다(복사 방식을 택한 이유).
- 자동 업데이트 3층: 스크립트(app.zip, 즉시)·런타임(zip, 작업 없을 때)·셸(Setup.exe /S, 창 숨김+작업 없을 때). zip 해제는 런타임 파이썬 `-I -c zipfile` 로(Node 내장 zip 없음, tar 는 폴백).
- 공개 저장소 배포물에 서버 키를 넣는 설계는 auto mode 분류기가 Credential Leakage 로 차단 → 업로드 엔드포인트를 키 없이(IP 제한·zip 검사) 열고 조회·삭제만 키로 보호. 결과적으로 더 깔끔.
- 사용자 원칙: 생성기는 실행 시 AI 를 쓰지 않는 규칙 코드. 설정 옵션은 "모든 도면 공통"인 것만, 한 도면에서만 필요한 값은 옵션이 아니라 자동 판별 로직. 피드백은 공통/파일 전용 판별 후 코드 반영(docs/FEEDBACK_LOOP.md).
- 새 도면 쌍(A31)은 원본이 XREF 의존 → 원본 DWG 만으로는 처리 불가. 인수 시 "XREF 바인딩본 또는 XREF 파일 동봉" 을 요구해야 함.
- 함정 재발: Bash heredoc 으로 한글·백슬래시 문서를 쓰면 `\a`→벨, `\n`→줄바꿈, `\t`→탭 오염(README 깨짐). 문서·코드 패치는 Edit/Write 도구로. MSYS 에서 `taskkill /F` 는 `/F` 가 경로로 변환돼 실패 → PowerShell `Stop-Process`. Electron `minWidth` 는 저장된 bounds 를 키워 주지 않음 → `Math.max` 로 직접 보정.
- 검증 패턴: 앱을 `--remote-debugging-port` 로 띄우고 CDP(Runtime.evaluate `window.girder.*`, Page.captureScreenshot)로 무GUI 조작·스크린샷. 설치본과 dev 앱은 같은 userData·단일 인스턴스 잠금을 쓰므로 둘 중 하나만.
