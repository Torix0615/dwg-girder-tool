'use strict';
/**
 * 파이썬 파이프라인 실행기.
 * 레이아웃(userData 아래, bat 패키지와 동일): app/ runtime/ config.json logs/ work/ results/<작업>/ jobs.json
 * 첫 실행(또는 설치본이 더 새 버전)이면 resources/engine/{app,runtime} 을 userData 로 복사한다.
 * 결과(최종 DXF·report)는 results/<id>_<이름>/ 에 만들고, 사용자는 '다운로드' 로 최종 DXF 만 받는다.
 */
const fs = require('fs');
const path = require('path');
const { spawn, spawnSync } = require('child_process');

const EXT = ['.dwg', '.dxf'];

function cmpVer(a, b) {
  const pa = String(a || '0').split('.').map((n) => parseInt(n, 10) || 0);
  const pb = String(b || '0').split('.').map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) > (pb[i] || 0) ? 1 : -1;
  }
  return 0;
}

function readText(p, dflt = '') {
  try {
    return fs.readFileSync(p, 'utf8').replace(/^﻿/, '').trim();
  } catch {
    return dflt;
  }
}

/** 폴더 교체(잠김 대비 재시도). src → dst, 기존 dst 는 dst_old 로 옮긴 뒤 삭제 */
function swapDir(dst, src) {
  const old = dst + '_old';
  for (let i = 0; i < 5; i++) {
    try {
      if (fs.existsSync(old)) fs.rmSync(old, { recursive: true, force: true });
      if (fs.existsSync(dst)) fs.renameSync(dst, old);
      fs.renameSync(src, dst);
      fs.rmSync(old, { recursive: true, force: true });
      return;
    } catch (e) {
      if (i === 4) throw e;
      spawnSync('ping', ['-n', '2', '127.0.0.1'], { windowsHide: true });
    }
  }
}

/**
 * @param {{ root: string, bundled: string, log: Function, onState: (s:any)=>void }} opts
 */
function createEngine({ root, bundled, log, onState, onError = null }) {
  const APP = path.join(root, 'app');
  const RT = path.join(root, 'runtime');
  const CFG = path.join(root, 'config.json');
  const PY = path.join(RT, 'python.exe');
  const RESULTS = path.join(root, 'results');
  const JOBS = path.join(root, 'jobs.json');

  /** @type {any[]} {id, src, name, state: queued|running|done|failed|cancelled, step, stepIdx, total, started, ended, outdir, result, report, message, feedback:{sent,at,id,text,scope,file}, log:[]} */
  let jobs = [];
  let current = null;
  let proc = null;
  let seq = 0;

  function loadJobs() {
    try {
      jobs = JSON.parse(fs.readFileSync(JOBS, 'utf8')).map((j) => ({ ...j, log: [] }));
      for (const j of jobs) {
        if (j.state === 'running' || j.state === 'queued') {
          j.state = 'failed';
          j.message = '이전 실행이 중단됨';
        }
        if (j.result && !fs.existsSync(j.result)) j.result = null;
        if (j.mgt && !fs.existsSync(j.mgt)) j.mgt = null;
      }
      seq = jobs.reduce((m, j) => Math.max(m, j.id), 0);
    } catch {
      jobs = [];
    }
  }
  function saveJobs() {
    try {
      fs.writeFileSync(JOBS, JSON.stringify(jobs.map(({ log: _l, ...j }) => j), null, 1));
    } catch (e) {
      log('jobs.json 저장 실패', e);
    }
  }
  loadJobs();

  function versions() {
    return {
      app: readText(path.join(APP, 'version.txt'), '-'),
      runtime: readText(path.join(RT, 'runtime_version.txt'), '-'),
      bundledApp: readText(path.join(bundled, 'app', 'version.txt'), '-'),
      bundledRuntime: readText(path.join(bundled, 'runtime', 'runtime_version.txt'), '-'),
    };
  }

  /** 설치본의 엔진을 userData 로 복사(없거나 설치본이 더 새 버전일 때). 런타임 245MB 는 수 초 걸림 */
  function ensureInstalled(onProgress = () => {}) {
    const v = versions();
    if (!fs.existsSync(path.join(bundled, 'app', 'run_pipeline.py'))) {
      throw new Error(`설치본에 엔진이 없음: ${bundled}`);
    }
    if (!fs.existsSync(path.join(APP, 'run_pipeline.py')) || cmpVer(v.bundledApp, v.app) > 0) {
      onProgress(`앱 스크립트 준비 중 (v${v.bundledApp})`);
      const tmp = APP + '_new';
      fs.rmSync(tmp, { recursive: true, force: true });
      fs.cpSync(path.join(bundled, 'app'), tmp, { recursive: true, filter: (p) => !p.includes('__pycache__') });
      swapDir(APP, tmp);
      log(`app 복사: ${v.app} -> ${v.bundledApp}`);
    }
    if (!fs.existsSync(PY) || cmpVer(v.bundledRuntime, v.runtime) > 0) {
      onProgress(`파이썬 런타임 준비 중 (처음 한 번, 약 10초)`);
      const tmp = RT + '_new';
      fs.rmSync(tmp, { recursive: true, force: true });
      fs.cpSync(path.join(bundled, 'runtime'), tmp, { recursive: true, filter: (p) => !p.includes('__pycache__') });
      swapDir(RT, tmp);
      log(`runtime 복사: ${v.runtime} -> ${v.bundledRuntime}`);
    }
    ensureConfig();
    for (const d of ['logs', 'work', 'tmp', 'results']) fs.mkdirSync(path.join(root, d), { recursive: true });
  }

  function ensureConfig() {
    const dflt = path.join(APP, 'config.default.json');
    if (!fs.existsSync(CFG) && fs.existsSync(dflt)) fs.copyFileSync(dflt, CFG);
  }

  function publicJob(j) {
    const { log: _l, ...rest } = j;
    return { ...rest, tail: j.log.slice(-8) };
  }
  function state() {
    return { jobs: jobs.map(publicJob), running: Boolean(current), ready: fs.existsSync(PY) && fs.existsSync(path.join(APP, 'run_pipeline.py')) };
  }
  function emit() {
    try {
      onState(state());
    } catch {
      /* 렌더러 없음 */
    }
  }

  function enqueue(paths) {
    let added = null;
    for (const p of paths || []) {
      if (!p || !EXT.includes(path.extname(p).toLowerCase())) continue;
      if (!fs.existsSync(p)) continue;
      if (jobs.some((j) => j.src === p && (j.state === 'queued' || j.state === 'running'))) continue;
      const id = ++seq;
      const base = path.basename(p, path.extname(p));
      jobs.push({ id, src: p, name: path.basename(p), state: 'queued', step: '', stepIdx: 0, total: 0, started: 0, ended: 0, outdir: path.join(RESULTS, `${id}_${base}`), result: null, report: null, message: '', feedback: null, log: [] });
      added = id;
    }
    saveJobs();
    emit();
    next();
    return added;
  }

  function next() {
    if (current) return;
    const j = jobs.find((x) => x.state === 'queued');
    if (!j) {
      emit();
      return;
    }
    run(j);
  }

  function run(j) {
    current = j;
    j.state = 'running';
    j.started = Date.now();
    j.total = path.extname(j.src).toLowerCase() === '.dwg' ? 8 : 7; // 변환·XREF·전개·1단계·모델·거더보·DXF·MGT
    j.step = '시작';
    fs.mkdirSync(j.outdir, { recursive: true });
    saveJobs();
    emit();
    const args = [path.join(APP, 'run_pipeline.py'), j.src, '--out', j.outdir, '--config', CFG];
    log(`실행: ${j.src}`);
    proc = spawn(PY, args, { cwd: APP, env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' }, windowsHide: true });
    let buf = '';
    const onData = (chunk) => {
      buf += chunk.toString('utf8');
      let i;
      while ((i = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, i).replace(/\r$/, '');
        buf = buf.slice(i + 1);
        if (!line.trim()) continue;
        j.log.push(line);
        if (j.log.length > 400) j.log.splice(0, j.log.length - 400);
        if (line.startsWith('=== ')) {
          j.step = line.slice(4).trim();
          j.stepIdx++;
        } else if (line.startsWith('완료 (')) {
          j.step = '완료';
        }
        emit();
      }
    };
    proc.stdout.on('data', onData);
    proc.stderr.on('data', onData);
    proc.on('error', (e) => {
      j.log.push(`실행 오류: ${e.message}`);
    });
    proc.on('close', (code) => {
      j.ended = Date.now();
      const base = path.basename(j.src, path.extname(j.src));
      const dxf = path.join(j.outdir, `${base}_골조거더보.dxf`);
      const rep = path.join(j.outdir, `${base}_골조거더보_report.txt`);
      const mgt = path.join(j.outdir, `${base}_MIDAS.mgt`);
      j.report = fs.existsSync(rep) ? rep : null;
      j.mgt = fs.existsSync(mgt) ? mgt : null;
      if (j.state === 'cancelled') {
        j.message = '취소됨';
      } else if (code === 0 && fs.existsSync(dxf)) {
        j.state = 'done';
        j.step = '완료';
        j.result = dxf;
        j.message = `완료 (${Math.round((j.ended - j.started) / 1000)}초)`;
      } else {
        j.state = 'failed';
        j.message = `실패 (코드 ${code})`;
        // 보고서의 [원인] 줄: "입력" = 사용자가 고칠 것(참조 파일 없음 등), "오류" = 프로그램 오류(자동 보고)
        const m = /\[원인\]\s*(입력|오류)\s*[—-]\s*(.+)/.exec(readText(rep));
        j.failKind = m ? (m[1] === '입력' ? 'input' : 'error') : 'error';
        j.failReason = m ? m[2].trim() : (j.log.slice(-1)[0] || '');
        j.errorReport = null;
      }
      log(`${j.state}: ${j.name} ${j.message}`);
      proc = null;
      current = null;
      saveJobs();
      emit();
      if (j.state === 'failed' && j.failKind === 'error' && onError) {
        onError(j); // 자동 오류 보고(비동기)
      }
      next();
    });
  }

  function cancel() {
    if (!current || !proc) return false;
    current.state = 'cancelled';
    current.message = '취소 중';
    emit();
    spawnSync('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { windowsHide: true });
    return true;
  }

  function remove(id) {
    const i = jobs.findIndex((j) => j.id === id);
    if (i < 0 || jobs[i].state === 'running') return false;
    const j = jobs[i];
    jobs.splice(i, 1);
    if (j.outdir && j.outdir.startsWith(RESULTS)) fs.rmSync(j.outdir, { recursive: true, force: true });
    saveJobs();
    emit();
    return true;
  }

  function setFeedback(id, fb) {
    const j = jobs.find((x) => x.id === id);
    if (!j) return false;
    j.feedback = fb;
    saveJobs();
    emit();
    return true;
  }

  function setErrorReport(id, er) {
    const j = jobs.find((x) => x.id === id);
    if (!j) return false;
    j.errorReport = er;
    saveJobs();
    emit();
    return true;
  }

  /** 전송 못 한 오류 보고(오프라인 등) 목록 — 시작 때 재시도용 */
  function pendingErrorReports() {
    return jobs.filter((j) => j.state === 'failed' && j.failKind === 'error' && !(j.errorReport && j.errorReport.sent));
  }

  return { enqueue, cancel, remove, setFeedback, setErrorReport, pendingErrorReports, state, versions, ensureInstalled, ensureConfig, isIdle: () => !current, job: (id) => jobs.find((j) => j.id === id) || null, paths: { APP, RT, CFG, PY, RESULTS }, EXT };
}

module.exports = { createEngine, cmpVer, readText, swapDir };
