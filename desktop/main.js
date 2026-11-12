'use strict';
const { app, BrowserWindow, Tray, Menu, ipcMain, shell, nativeImage, dialog } = require('electron');
const fs = require('fs');
const path = require('path');
const { createEngine } = require('./lib/engine.cjs');
const { createUpdater } = require('./lib/updater.cjs');

app.setName('GirderTool');
if (!app.isPackaged && process.env.GIRDER_TEST_ROOT) app.setPath('userData', process.env.GIRDER_TEST_ROOT); // 개발 검증용: 실제 데이터 폴더·피드백 서버를 건드리지 않는 격리 폴더(설치본에는 영향 없음)
const START_HIDDEN = process.argv.includes('--hidden');
const ROOT = app.getPath('userData');
const BUNDLED = app.isPackaged ? path.join(process.resourcesPath, 'engine') : path.join(__dirname, '..', 'dist_build', 'pkg');
const SETTINGS = path.join(ROOT, 'settings.json');
const LOG = path.join(ROOT, 'desktop.log');

let mainWindow = null;
let tray = null;
let engine = null;
let updater = null;
let settings = { pinned: false, bounds: null }; // 항상 위(핀)는 기본 해제, 필요할 때 켬

function log(...args) {
  const d = new Date();
  const stamp = new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 19).replace('T', ' ');
  const line = `[${stamp}] ${args.map((a) => (a instanceof Error ? a.stack || a.message : typeof a === 'string' ? a : JSON.stringify(a))).join(' ')}`;
  try {
    fs.mkdirSync(ROOT, { recursive: true });
    fs.appendFileSync(LOG, line + '\n');
    if (fs.statSync(LOG).size > 2e6) fs.writeFileSync(LOG, line + '\n');
  } catch {
    /* */
  }
  if (!app.isPackaged) console.log(line);
}
function loadSettings() {
  try {
    settings = { ...settings, ...JSON.parse(fs.readFileSync(SETTINGS, 'utf8')) };
  } catch {
    /* 첫 실행 */
  }
}
function saveSettings() {
  try {
    fs.writeFileSync(SETTINGS, JSON.stringify(settings, null, 1));
  } catch {
    /* */
  }
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', (_e, argv) => {
    const files = fileArgs(argv);
    if (files.length && engine) engine.enqueue(files.slice(0, 1));
    if (!argv.includes('--hidden')) showWindow();
  });
}

function fileArgs(argv) {
  return argv.slice(1).filter((a) => !a.startsWith('-') && /\.(dwg|dxf|mgt)$/i.test(a) && fs.existsSync(a));
}

function send(channel, data) {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send(channel, data);
}

function createWindow() {
  const b = settings.bounds || {};
  mainWindow = new BrowserWindow({
    width: Math.max(900, b.width || 960),
    height: Math.max(600, b.height || 640),
    x: b.x,
    y: b.y,
    minWidth: 900,
    minHeight: 600,
    frame: false,
    alwaysOnTop: Boolean(settings.pinned),
    show: false,
    backgroundColor: '#15171c',
    icon: path.join(__dirname, 'assets', 'icon.png'),
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false, spellcheck: false },
  });
  mainWindow.setMenuBarVisibility(false);
  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  mainWindow.on('close', (e) => {
    if (app.isQuitting) return;
    e.preventDefault();
    mainWindow.hide();
    if (updater) updater.maybeInstall();
  });
  const saveBounds = () => {
    if (!mainWindow.isMinimized()) {
      settings.bounds = mainWindow.getBounds();
      saveSettings();
    }
  };
  mainWindow.on('resize', saveBounds);
  mainWindow.on('move', saveBounds);
  mainWindow.webContents.on('did-finish-load', () => {
    send('engine-state', engine.state());
    send('update-status', updater.status());
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
}

function showWindow() {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}


function buildTrayMenu() {
  return Menu.buildFromTemplate([
    { label: '열기', click: () => showWindow() },
    { label: '골조 모델링…', click: () => startJob() },
    { label: '구조 검토…', click: () => startStage4() },
    {
      label: '피드백…',
      click: () => {
        showWindow();
        send('open-feedback', {});
      },
    },
    { type: 'separator' },
    { label: '항상 위에', type: 'checkbox', checked: Boolean(settings.pinned), click: (m) => setPinned(m.checked) },
    { label: '업데이트 확인', click: () => updater.check() },
    { label: '데이터 폴더 열기', click: () => shell.openPath(ROOT) },
    { type: 'separator' },
    {
      label: '종료',
      click: () => {
        app.isQuitting = true;
        app.quit();
      },
    },
  ]);
}
function createTray() {
  const img = nativeImage.createFromPath(path.join(__dirname, 'assets', 'tray.png'));
  tray = new Tray(img);
  tray.setToolTip('골조·거더·보 생성기');
  tray.on('click', () => (mainWindow && mainWindow.isVisible() ? mainWindow.hide() : showWindow()));
  tray.on('right-click', () => tray.popUpContextMenu(buildTrayMenu()));
  tray.setContextMenu(buildTrayMenu());
}
function setPinned(on) {
  settings.pinned = Boolean(on);
  saveSettings();
  if (mainWindow) mainWindow.setAlwaysOnTop(settings.pinned);
  if (tray) tray.setContextMenu(buildTrayMenu());
}

/** 골조 모델링(1·2·3단계) 시작: 탐색기에서 도면 1개 선택 → 대기열 */
async function startJob() {
  showWindow();
  const r = await dialog.showOpenDialog(mainWindow, { title: '골조 모델링 — 도면 선택 (1개)', filters: [{ name: 'DWG/DXF', extensions: ['dwg', 'dxf'] }], properties: ['openFile'] });
  if (r.canceled || !r.filePaths.length) return null;
  return engine.enqueue(r.filePaths.slice(0, 1));
}

/** 구조 검토(4단계) 시작: 수작업을 마친 MIDAS 모델(.mgt) 1개 선택 → 모델 읽기 작업(골조 모델링 없이 단독) */
async function startStage4() {
  showWindow();
  const r = await dialog.showOpenDialog(mainWindow, { title: '구조 검토 — MIDAS GEN 모델(.mgt) 선택', filters: [{ name: 'MIDAS Gen MGT', extensions: ['mgt'] }], properties: ['openFile'] });
  if (r.canceled || !r.filePaths.length) return null;
  return engine.enqueue(r.filePaths.slice(0, 1));
}

/** 다운로드: 최종 DXF 만 사용자가 고른 위치에 저장 */
async function download(jobId, kind = 'dxf') {
  const j = engine.job(jobId);
  const s4 = (j && j.stage4) || {};
  const pick = { dxf: j && j.result, mgt: j && j.mgt, xlsx: s4.xlsx, mgt2: s4.mgt2 };
  const src = pick[kind];
  if (!j || !src || !fs.existsSync(src)) return { ok: false, message: '결과 파일이 없습니다' };
  const filt = { dxf: [{ name: 'DXF', extensions: ['dxf'] }], mgt: [{ name: 'MIDAS Gen MGT', extensions: ['mgt'] }], mgt2: [{ name: 'MIDAS Gen MGT', extensions: ['mgt'] }], xlsx: [{ name: 'Excel', extensions: ['xlsx'] }] }[kind];
  const title = { dxf: '결과 DXF 저장', mgt: 'MIDAS GEN MGT 저장', mgt2: '수정 MGT(구조 검토 승인) 저장', xlsx: '구조 검토 결과 엑셀 저장' }[kind];
  const base = path.basename(j.src, path.extname(j.src));
  const name = kind === 'xlsx' ? `${base}_구조검토.xlsx` : path.basename(src);
  const r = await dialog.showSaveDialog(mainWindow, { title, defaultPath: path.join(app.getPath('downloads'), name), filters: filt });
  if (r.canceled || !r.filePath) return { ok: false, message: '' };
  fs.copyFileSync(src, r.filePath);
  log('다운로드', r.filePath);
  shell.showItemInFolder(r.filePath);
  return { ok: true, message: `저장됨: ${r.filePath}`, file: r.filePath };
}

/** 프로그램 오류(입력 문제가 아닌 실패) 자동 보고 — 피드백과 별개, 사용자 조작 없음. which='stage4' 면 4단계 검토 실패(결과표 첨부) */
async function reportError(j, which = 'job') {
  try {
    engine.setErrorReport(j.id, { sent: false, at: new Date().toISOString(), message: '오류 보고 전송 중' }, which);
    const r = await require('./lib/feedback.cjs').sendError({ root: ROOT, engine, bundledApp: path.join(BUNDLED, 'app'), appVersion: app.getVersion(), job: j, log, which });
    engine.setErrorReport(j.id, { sent: Boolean(r.ok), id: r.id, at: new Date().toISOString(), message: r.message }, which);
  } catch (e) {
    log('오류 보고 실패', e);
    engine.setErrorReport(j.id, { sent: false, at: new Date().toISOString(), message: `오류 보고 실패: ${e.message}` }, which);
  }
}

/** 문제 없음 표본 전송(백그라운드): [건너뛰기] 로 표시한 작업의 원본·결과를 서버로. 실패하면 다음 실행 때 재시도 */
async function sendSample(j) {
  try {
    const r = await require('./lib/feedback.cjs').sendSample({ root: ROOT, engine, bundledApp: path.join(BUNDLED, 'app'), appVersion: app.getVersion(), job: j, log });
    const cur = engine.job(j.id);
    if (cur && cur.feedback && cur.feedback.skipped) engine.setFeedback(j.id, { ...cur.feedback, sample: { sent: Boolean(r.ok), id: r.id, at: new Date().toISOString() } });
  } catch (e) {
    log('문제 없음 표본 전송 실패', e);
  }
}

/** [건너뛰기]: 결과에 문제가 없어 피드백이 필요 없는 작업 → "문제 없음" 으로 표시하고 표본으로 보냄 */
function skipFeedback(jobId) {
  const j = engine.job(jobId);
  if (!j || j.state !== 'done') return { ok: false, message: '완료된 작업에서만 건너뛸 수 있습니다' };
  if (j.kind === 's4' && !(j.stage4 && j.stage4.state === 'done' && j.stage4.summary)) return { ok: false, message: '검토가 끝난 뒤에 건너뛸 수 있습니다' };
  if (j.feedback && (j.feedback.sent || j.feedback.skipped)) return { ok: false, message: '이미 처리한 작업입니다' };
  engine.setFeedback(jobId, { skipped: true, sent: false, at: new Date().toISOString() });
  engine.setDraft(jobId, null);
  sendSample(engine.job(jobId));
  return { ok: true };
}

/** 피드백 로그(보낸 피드백 전체): 제목 = 작업 뒤 피드백은 파일 이름, 작업 없이 보낸 피드백은 첫 문장(길면 자름) */
function firstSentence(text) {
  const t = String(text || '').trim().split(/\n|(?<=[.!?。])\s/)[0].trim();
  return t.length > 60 ? `${t.slice(0, 60)}…` : t || '(내용 없음)';
}
function addFeedbackLog(entry) {
  settings.feedbackLog = [...(settings.feedbackLog || []), entry].slice(-300);
  saveSettings();
}
/** 1.6.x 이전에 보낸 피드백(작업 목록의 전송 기록 + 작업 없이 보낸 내역)을 로그로 옮김 — 처음 한 번 */
function migrateFeedbackLog() {
  if (Array.isArray(settings.feedbackLog)) return;
  const kindOf = { all: 'rule', file: 'file' };
  const fromJobs = engine
    .state()
    .jobs.filter((j) => j.feedback && j.feedback.sent)
    .map((j) => ({ at: j.feedback.at, source: 'job', title: j.name, kind: kindOf[j.feedback.scope] || 'unknown', text: j.feedback.text || '', id: j.feedback.id, file: j.feedback.file }));
  const fromGeneral = (settings.feedbackHistory || []).map((h) => ({ at: h.at, source: 'general', title: firstSentence(h.text), kind: ['ui', 'rule'].includes(h.category) ? h.category : 'unknown', text: h.text || '', id: h.id, file: h.file }));
  settings.feedbackLog = [...fromJobs, ...fromGeneral].sort((a, b) => String(a.at).localeCompare(String(b.at))).slice(-300);
  saveSettings();
}

/** 구조 검토: MIDAS 해석 결과표(텍스트·엑셀) 선택 → 검토 실행 */
async function pickStage4(jobId) {
  const r = await dialog.showOpenDialog(mainWindow, {
    title: 'MIDAS GEN 해석 결과표(Beam Force 텍스트·엑셀) 선택',
    filters: [{ name: '결과표 (텍스트·엑셀)', extensions: ['txt', 'csv', 'tsv', 'dat', 'out', 'prn', 'xlsx'] }, { name: '모든 파일', extensions: ['*'] }],
    properties: ['openFile'],
  });
  if (r.canceled || !r.filePaths.length) return { ok: false, message: '' };
  return engine.runStage4(jobId, r.filePaths[0]);
}

function registerIpc() {
  ipcMain.handle('start-job', () => startJob());
  ipcMain.handle('start-stage4', () => startStage4());
  ipcMain.handle('run', (_e, paths) => engine.enqueue((paths || []).slice(0, 1)));
  ipcMain.handle('cancel', () => engine.cancel());
  ipcMain.handle('remove-job', (_e, id) => engine.remove(id));
  ipcMain.handle('engine-state', () => engine.state());
  ipcMain.handle('download', (_e, id, kind) => download(id, kind));
  ipcMain.handle('stage4-pick', (_e, id) => pickStage4(id));
  ipcMain.handle('stage4-run', (_e, id, p) => engine.runStage4(id, p));
  ipcMain.handle('stage4-apply', (_e, id) => engine.applyStage4(id));
  ipcMain.handle('open-path', (_e, p) => shell.openPath(p));
  ipcMain.handle('show-in-folder', (_e, p) => shell.showItemInFolder(p));
  // 피드백: jobId 가 있으면 작업 결과 화면의 피드백(원본·결과 첨부), 없으면 작업 없이 보내는 피드백(scope=general, 첨부 없음). 보낸 것은 모두 피드백 로그에 남김
  ipcMain.handle('send-feedback', async (_e, { text, scope, category, jobId }) => {
    const job = jobId == null ? null : engine.job(jobId);
    const r = await require('./lib/feedback.cjs').send({
      root: ROOT, engine, bundledApp: path.join(BUNDLED, 'app'), appVersion: app.getVersion(), text, scope, category, job, log,
      onProgress: (p) => send('feedback-progress', { jobId, ...p }),
    });
    if (r.sent && r.ok) {
      addFeedbackLog({
        at: new Date().toISOString(), source: job ? 'job' : 'general', title: job ? job.name : firstSentence(text),
        kind: job ? (scope === 'file' ? 'file' : 'rule') : category === 'ui' ? 'ui' : 'rule', text: String(text).slice(0, 2000), id: r.id, file: r.file,
      });
    }
    return r;
  });
  ipcMain.handle('skip-feedback', (_e, id) => skipFeedback(id));
  ipcMain.handle('set-draft', (_e, id, draft) => engine.setDraft(id, draft));
  ipcMain.handle('feedback-log', () => settings.feedbackLog || []);
  ipcMain.handle('get-side-width', () => settings.sideWidth || 255);
  ipcMain.handle('set-side-width', (_e, w) => {
    const n = Math.round(Number(w));
    if (Number.isFinite(n)) {
      settings.sideWidth = Math.min(340, Math.max(170, n)); // 왼쪽 목록 폭: 최소 170 · 기본 255 · 최대 340
      saveSettings();
    }
    return settings.sideWidth || 255;
  });
  ipcMain.handle('get-settings', () => engine.getSettings());
  ipcMain.handle('set-settings', (_e, vals) => engine.setSettings(vals || {}));
  ipcMain.handle('open-data-folder', () => shell.openPath(ROOT));
  ipcMain.handle('update-check', () => updater.check());
  ipcMain.handle('update-status', () => updater.status());
  ipcMain.handle('update-install', () => updater.install({ show: Boolean(mainWindow && mainWindow.isVisible()) }));
  ipcMain.handle('versions', () => ({ ...engine.versions(), shell: app.getVersion(), root: ROOT }));
  ipcMain.handle('get-pinned', () => Boolean(settings.pinned));
  ipcMain.handle('set-pinned', (_e, on) => {
    setPinned(on);
    return settings.pinned;
  });
  ipcMain.handle('hide-window', () => {
    if (mainWindow) mainWindow.hide();
    if (updater) updater.maybeInstall();
  });
}

app.whenReady().then(() => {
  loadSettings();
  log(`시작 v${app.getVersion()} packaged=${app.isPackaged} root=${ROOT}`);
  engine = createEngine({
    root: ROOT,
    bundled: BUNDLED,
    log,
    onError: (j, which) => reportError(j, which),
    onState: (s) => {
      send('engine-state', s);
      if (!s.running && updater) {
        updater.applyPending();
        updater.maybeInstall();
      }
    },
  });
  updater = createUpdater({
    app,
    root: ROOT,
    engine,
    bundledApp: path.join(BUNDLED, 'app'),
    log,
    onStatus: (s) => send('update-status', s),
    isWindowVisible: () => Boolean(mainWindow && mainWindow.isVisible() && !mainWindow.isMinimized()),
  });
  migrateFeedbackLog();
  registerIpc();
  createWindow();
  createTray();
  mainWindow.webContents.once('did-finish-load', () => {
    try {
      engine.ensureInstalled((msg) => send('install-progress', msg));
      send('install-progress', '');
    } catch (e) {
      log('엔진 준비 실패', e);
      send('install-progress', `엔진 준비 실패: ${e.message}`);
    }
    send('engine-state', engine.state());
    updater.start();
    setTimeout(() => {
      for (const j of engine.pendingErrorReports()) reportError(j); // 지난 실행에서 못 보낸 오류 보고 재시도
      for (const j of engine.pendingSamples()) sendSample(j); // 못 보낸 문제 없음 표본 재시도
    }, 15000);
    const files = fileArgs(process.argv);
    if (files.length) engine.enqueue(files.slice(0, 1));
  });
  if (!START_HIDDEN) mainWindow.once('ready-to-show', () => showWindow());
});

app.on('window-all-closed', (e) => e.preventDefault());
app.on('before-quit', () => {
  app.isQuitting = true;
  if (updater) updater.stop();
});
