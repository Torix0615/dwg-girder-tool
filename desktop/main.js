'use strict';
const { app, BrowserWindow, Tray, Menu, ipcMain, shell, nativeImage, dialog } = require('electron');
const fs = require('fs');
const path = require('path');
const { createEngine } = require('./lib/engine.cjs');
const { createUpdater } = require('./lib/updater.cjs');

app.setName('GirderTool');
const START_HIDDEN = process.argv.includes('--hidden');
const ROOT = app.getPath('userData');
const BUNDLED = app.isPackaged ? path.join(process.resourcesPath, 'engine') : path.join(__dirname, '..', 'dist_build', 'pkg');
const SETTINGS = path.join(ROOT, 'settings.json');
const LOG = path.join(ROOT, 'desktop.log');

let mainWindow = null;
let tray = null;
let engine = null;
let updater = null;
let settings = { pinned: true, bounds: null };

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
  return argv.slice(1).filter((a) => !a.startsWith('-') && /\.(dwg|dxf)$/i.test(a) && fs.existsSync(a));
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
    { label: '작업 시작…', click: () => startJob() },
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

/** 작업 시작: 탐색기에서 도면 1개 선택 → 대기열 */
async function startJob() {
  showWindow();
  const r = await dialog.showOpenDialog(mainWindow, { title: '도면 선택 (1개)', filters: [{ name: 'DWG/DXF', extensions: ['dwg', 'dxf'] }], properties: ['openFile'] });
  if (r.canceled || !r.filePaths.length) return null;
  return engine.enqueue(r.filePaths.slice(0, 1));
}

/** 다운로드: 최종 DXF 만 사용자가 고른 위치에 저장 */
async function download(jobId) {
  const j = engine.job(jobId);
  if (!j || !j.result || !fs.existsSync(j.result)) return { ok: false, message: '결과 파일이 없습니다' };
  const r = await dialog.showSaveDialog(mainWindow, { title: '결과 DXF 저장', defaultPath: path.join(app.getPath('downloads'), path.basename(j.result)), filters: [{ name: 'DXF', extensions: ['dxf'] }] });
  if (r.canceled || !r.filePath) return { ok: false, message: '' };
  fs.copyFileSync(j.result, r.filePath);
  log('다운로드', r.filePath);
  shell.showItemInFolder(r.filePath);
  return { ok: true, message: `저장됨: ${r.filePath}`, file: r.filePath };
}

function registerIpc() {
  ipcMain.handle('start-job', () => startJob());
  ipcMain.handle('run', (_e, paths) => engine.enqueue((paths || []).slice(0, 1)));
  ipcMain.handle('cancel', () => engine.cancel());
  ipcMain.handle('remove-job', (_e, id) => engine.remove(id));
  ipcMain.handle('engine-state', () => engine.state());
  ipcMain.handle('download', (_e, id) => download(id));
  ipcMain.handle('open-path', (_e, p) => shell.openPath(p));
  ipcMain.handle('show-in-folder', (_e, p) => shell.showItemInFolder(p));
  ipcMain.handle('send-feedback', (_e, { text, scope, jobId }) =>
    require('./lib/feedback.cjs').send({
      root: ROOT, engine, bundledApp: path.join(BUNDLED, 'app'), appVersion: app.getVersion(), text, scope, job: engine.job(jobId), log,
      onProgress: (p) => send('feedback-progress', { jobId, ...p }),
    })
  );
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
