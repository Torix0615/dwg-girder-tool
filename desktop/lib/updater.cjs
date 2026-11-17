'use strict';
/**
 * 자동 업데이트 3층(의존성 없음).
 *  app     : latest.json app_version > app/version.txt → 변경 내용을 띄우고 app.zip 받아 app/ 교체(작업 중이면 끝난 뒤)
 *  runtime : runtime_version 다르면 runtime.zip → runtime/ 교체(작업 중이면 끝난 뒤)
 *  shell   : shell_version > 앱 버전이면 Setup exe 받아 sha256 확인 → 창이 숨겨져 있고 작업이 없을 때 무인 설치(/S) 후 --hidden 재기동
 * 화면 알림(1.9): status.next = 아직 설치되지 않은 새 버전(버튼 줄 위의 설치 줄), status.whatsNew = 설치를 마친 버전의 업데이트 내용(처음 한 번 뜨는 팝업,
 *  [✕] 로 닫으면 getSeen() 이 그 버전이 되어 다시 안 뜸), changelog() = 버전별 내역(app/changelog.json — release.py 가 넣음)
 * 서버 주소: 환경변수 DWG_UPDATE_URL > app/update_source.txt (latest.json 은 GitHub raw: 반영 지연 최대 5분)
 */
const fs = require('fs');
const fsp = require('fs/promises');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const { spawn, spawnSync } = require('child_process');
const { Readable, Transform } = require('stream');
const { pipeline } = require('stream/promises');
const { cmpVer, readText, swapDir } = require('./engine.cjs');

const CHECK_EVERY_MS = 3 * 60 * 60 * 1000;
const FIRST_CHECK_MS = 5 * 1000;

function createUpdater({ app, root, engine, bundledApp, log, onStatus, isWindowVisible, getSeen = () => '0' }) {
  const dir = path.join(root, 'updates');
  const tmp = path.join(root, 'tmp');
  let status = { state: 'idle', message: '', progress: 0, notes: [], latest: null, next: null, shell: null, canInstall: false, whatsNew: null, current: current() };
  let running = null;
  let runningSince = 0;
  let timer = null;
  let shellReady = null; // {file, version}
  let pendingApply = null; // 작업 중이라 미룬 app/runtime 교체
  let shellNeeded = null; // 서버에 있는 새 프로그램(설치본) 버전 — 설치 전까지 유지
  let appNeeded = null; // 받아 두었지만 아직 교체하지 못한 엔진(app) 버전
  let checkedOk = false; // 이번 실행에서 서버 확인에 성공했는지

  function current() {
    const v = engine.versions();
    return { app: v.app, runtime: v.runtime, shell: app.getVersion() };
  }
  function set(patch) {
    status = { ...status, ...patch, current: current(), next: shellNeeded || appNeeded, shell: shellNeeded, canInstall: Boolean(shellReady && fs.existsSync(shellReady.file)) };
    try {
      onStatus(status);
    } catch {
      /* 렌더러 없음 */
    }
  }
  function sourceUrl() {
    return process.env.DWG_UPDATE_URL || readText(path.join(engine.paths.APP, 'update_source.txt')) || readText(path.join(bundledApp, 'update_source.txt'));
  }

  async function download(url, dest, label, expectedSha) {
    await fsp.mkdir(path.dirname(dest), { recursive: true });
    const part = dest + '.part';
    const res = await fetch(url, { signal: AbortSignal.timeout(10 * 60_000), redirect: 'follow' });
    if (!res.ok || !res.body) throw new Error(`${label} 다운로드 실패 (HTTP ${res.status})`);
    const total = Number(res.headers.get('content-length')) || 0;
    const hash = crypto.createHash('sha256');
    let got = 0;
    let last = 0;
    const counter = new Transform({
      transform(chunk, _enc, cb) {
        hash.update(chunk);
        got += chunk.length;
        const now = Date.now();
        if (now - last > 300) {
          last = now;
          set({ progress: total ? got / total : 0, message: `${label} 내려받는 중 ${(got / 1e6).toFixed(0)}${total ? '/' + (total / 1e6).toFixed(0) : ''} MB` });
        }
        cb(null, chunk);
      },
    });
    try {
      await pipeline(Readable.fromWeb(res.body), counter, fs.createWriteStream(part));
    } catch (e) {
      await fsp.rm(part, { force: true }).catch(() => {});
      throw e;
    }
    const sha = hash.digest('hex');
    if (expectedSha && sha !== expectedSha) {
      await fsp.rm(part, { force: true }).catch(() => {});
      throw new Error(`${label} 파일 해시 불일치`);
    }
    await fsp.rm(dest, { force: true }).catch(() => {});
    await fsp.rename(part, dest);
    return { size: got, sha };
  }

  /** zip 풀기: 런타임 파이썬(표준 zipfile) → 없으면 Windows tar */
  function extract(zip, dst) {
    fs.rmSync(dst, { recursive: true, force: true });
    fs.mkdirSync(dst, { recursive: true });
    const py = engine.paths.PY;
    if (fs.existsSync(py)) {
      const r = spawnSync(py, ['-I', '-c', 'import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])', zip, dst], { windowsHide: true, encoding: 'utf8' });
      if (r.status === 0) return;
      log('python 압축 해제 실패, tar 로 재시도', r.stderr);
    }
    const t = spawnSync('tar', ['-xf', zip, '-C', dst], { windowsHide: true, encoding: 'utf8' });
    if (t.status !== 0) throw new Error(`압축 해제 실패: ${t.stderr || t.error}`);
  }

  /** 버전별 업데이트 내역(최신 먼저). 엔진 폴더의 changelog.json → 설치본에 든 것 → 서버 latest.json 의 notes */
  function changelog() {
    for (const p of [path.join(engine.paths.APP, 'changelog.json'), path.join(bundledApp, 'changelog.json')]) {
      try {
        const list = JSON.parse(fs.readFileSync(p, 'utf8').replace(/^\uFEFF/, ''));
        if (Array.isArray(list) && list.length) return list;
      } catch {
        /* 없음 */
      }
    }
    return (status.latest && status.latest.notes) || [];
  }
  /** 지금 설치된 버전까지의 내역(설정의 [업데이트 내역]) */
  function history() {
    const cur = current().app;
    return changelog().filter((n) => n && n.version && cmpVer(n.version, cur) <= 0).sort((a, b) => cmpVer(b.version, a.version));
  }
  /** 설치를 마친 버전의 업데이트 내용을 한 번 띄울지 정한다. 엔진(app)만 먼저 바뀌고 프로그램(설치본)이 아직이면 설치가 끝난 뒤에 띄운다 */
  function evalNews() {
    const seen = getSeen();
    if (status.whatsNew && cmpVer(status.whatsNew.version, seen) > 0) return; // 떠 있는 팝업은 닫을 때까지 그대로
    const cur = current();
    const settled = cmpVer(cur.app, cur.shell) <= 0 || (checkedOk && !shellNeeded);
    let news = null;
    if (cmpVer(cur.app, seen) > 0 && settled && !pendingApply) news = changelog().find((n) => n && String(n.version) === String(cur.app)) || null;
    if (news || status.whatsNew) set({ whatsNew: news });
  }

  function notesSince(latest, ver) {
    return (latest.notes || []).filter((n) => cmpVer(n.version, ver) > 0);
  }

  async function doCheck() {
    const url = sourceUrl();
    if (!url) {
      set({ state: 'idle', message: '업데이트 서버 주소 없음' });
      return status;
    }
    if (status.state === 'installing') return status;
    set({ state: 'checking', message: '업데이트 확인 중', progress: 0 });
    const res = await fetch(url + (url.includes('?') ? '&' : '?') + 't=' + Date.now(), { signal: AbortSignal.timeout(20_000) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const latest = await res.json();
    const cur = current();
    const notes = notesSince(latest, cur.app);
    const needApp = latest.app_version && cmpVer(latest.app_version, cur.app) > 0;
    const needRt = latest.runtime_version && String(latest.runtime_version) !== String(cur.runtime) && latest.runtime_url;
    const needShell = latest.shell_version && latest.shell_url && cmpVer(latest.shell_version, cur.shell) > 0;
    checkedOk = true;
    shellNeeded = needShell ? String(latest.shell_version) : null;
    appNeeded = needApp ? String(latest.app_version) : null;
    set({ latest, notes });
    if (!needApp && !needRt && !needShell) {
      set({ state: 'uptodate', message: '최신 버전입니다', progress: 0 });
      evalNews();
      return status;
    }
    fs.mkdirSync(tmp, { recursive: true });
    // 1) app / runtime: 받아 두고, 작업 중이 아니면 바로 교체
    const apply = [];
    if (needApp) {
      set({ state: 'downloading', message: `앱 v${latest.app_version} 내려받는 중` });
      const zp = path.join(tmp, 'app.zip');
      await download(latest.app_url, zp, '앱');
      const nd = engine.paths.APP + '_new';
      extract(zp, nd);
      if (readText(path.join(nd, 'version.txt')) !== String(latest.app_version)) throw new Error('받은 앱 파일의 버전이 다름');
      apply.push({ what: 'app', dst: engine.paths.APP, src: nd, ver: latest.app_version });
    }
    if (needRt) {
      set({ state: 'downloading', message: `런타임 ${latest.runtime_version} 내려받는 중 (약 90MB)` });
      const zp = path.join(tmp, 'runtime.zip');
      await download(latest.runtime_url, zp, '런타임');
      const nd = engine.paths.RT + '_new';
      extract(zp, nd);
      if (!fs.existsSync(path.join(nd, 'python.exe'))) throw new Error('받은 런타임에 python.exe 가 없음');
      apply.push({ what: 'runtime', dst: engine.paths.RT, src: nd, ver: latest.runtime_version });
    }
    if (apply.length) {
      pendingApply = apply;
      set({ state: 'ready', message: '업데이트 준비됨', progress: 1 });
      applyPending();
    }
    // 2) shell
    if (needShell) {
      if (shellReady && shellReady.version === latest.shell_version && fs.existsSync(shellReady.file)) {
        set({ state: 'ready', message: `v${latest.shell_version} 설치 준비됨 — 창을 닫으면 설치됩니다`, progress: 1 });
      } else {
        await fsp.mkdir(dir, { recursive: true });
        for (const f of await fsp.readdir(dir)) await fsp.rm(path.join(dir, f), { force: true }).catch(() => {});
        set({ state: 'downloading', message: `프로그램 v${latest.shell_version} 내려받는 중` });
        const file = path.join(dir, `GirderTool-Setup-${latest.shell_version}.exe`);
        await download(latest.shell_url, file, '프로그램', latest.shell_sha256);
        shellReady = { file, version: latest.shell_version };
        log(`프로그램 업데이트 준비됨: ${latest.shell_version}`);
        set({ state: 'ready', message: `v${latest.shell_version} 설치 준비됨 — 창을 닫으면 설치됩니다`, progress: 1 });
      }
      maybeInstall();
    } else if (!apply.length) {
      set({ state: 'uptodate', message: '최신 버전입니다' });
    }
    evalNews();
    return status;
  }

  /** 받아 둔 app/runtime 을 교체(작업 중이면 끝난 뒤 다시 호출됨) */
  function applyPending() {
    if (!pendingApply) return false;
    if (!engine.isIdle()) {
      set({ message: '작업이 끝나면 업데이트를 적용합니다' });
      return false;
    }
    const list = pendingApply;
    pendingApply = null;
    try {
      for (const a of list) {
        swapDir(a.dst, a.src);
        log(`${a.what} 업데이트 적용: ${a.ver}`);
      }
      engine.ensureConfig();
      appNeeded = null;
      const applied = list.map((a) => `${a.what === 'app' ? '앱' : '런타임'} ${a.ver}`).join(', ');
      set({ state: shellReady ? 'ready' : 'updated', message: `업데이트 완료: ${applied}`, progress: 0 });
      evalNews();
      return true;
    } catch (e) {
      log('업데이트 적용 실패', e);
      set({ state: 'error', message: `업데이트 적용 실패: ${e.message}` });
      return false;
    }
  }

  function check() {
    if (running && Date.now() - runningSince < 2 * 60_000) return running;
    runningSince = Date.now();
    running = doCheck()
      .catch((e) => {
        log('업데이트 확인 실패', e);
        set({ state: 'error', message: `업데이트 확인 실패: ${(e && e.message) || e} (오프라인이면 현재 버전으로 계속)` });
        evalNews();
        return status;
      })
      .finally(() => {
        running = null;
      });
    return running;
  }

  function maybeInstall() {
    if (shellReady && !isWindowVisible() && engine.isIdle()) install({ show: false });
  }

  function install({ show = false } = {}) {
    if (!shellReady || !fs.existsSync(shellReady.file)) return false;
    if (!engine.isIdle()) {
      set({ message: '작업이 끝나면 설치합니다' });
      return false;
    }
    if (!app.isPackaged) {
      log('개발 실행: 설치 생략', shellReady.file);
      set({ message: '개발 실행에서는 설치하지 않습니다' });
      return false;
    }
    const exe = process.execPath;
    const script = path.join(os.tmpdir(), `girdertool-update-${Date.now()}.cmd`);
    const lines = [
      '@echo off',
      'chcp 65001 >nul',
      'ping -n 4 127.0.0.1 >nul',
      `start "" /wait "${shellReady.file}" /S`,
      `start "" "${exe}"${show ? '' : ' --hidden'}`,
      '(goto) 2>nul & del "%~f0"',
    ];
    fs.writeFileSync(script, lines.join('\r\n') + '\r\n', 'utf8');
    log(`프로그램 설치 시작: ${shellReady.version} (창 ${show ? '표시' : '숨김'})`);
    set({ state: 'installing', message: `v${shellReady.version} 설치 중 — 잠시 후 다시 실행됩니다` });
    spawn('cmd.exe', ['/d', '/c', script], { detached: true, stdio: 'ignore', windowsHide: true }).unref();
    app.isQuitting = true;
    setTimeout(() => app.quit(), 300);
    return true;
  }

  function cleanup() {
    try {
      for (const f of fs.readdirSync(dir)) {
        const m = /(\d+\.\d+\.\d+)/.exec(f);
        if (!m || cmpVer(m[1], app.getVersion()) <= 0) fs.rmSync(path.join(dir, f), { force: true });
      }
    } catch {
      /* 폴더 없음 */
    }
    try {
      fs.rmSync(tmp, { recursive: true, force: true });
    } catch {
      /* */
    }
  }

  function start() {
    cleanup();
    evalNews(); // 설치 직후 실행: 서버 확인을 기다리지 않고 바로(엔진과 프로그램 버전이 맞을 때)
    setTimeout(() => check(), FIRST_CHECK_MS);
    timer = setInterval(() => check(), CHECK_EVERY_MS);
  }
  function stop() {
    if (timer) clearInterval(timer);
    timer = null;
  }

  return { check, install, maybeInstall, applyPending, start, stop, status: () => status, history, evalNews };
}

module.exports = { createUpdater };
