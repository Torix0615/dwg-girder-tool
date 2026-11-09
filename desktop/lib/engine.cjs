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
        if (j.elements && !fs.existsSync(j.elements)) j.elements = null;
        if (j.stage4) {
          if (j.stage4.state === 'running') {
            j.stage4.state = 'failed';
            j.stage4.failReason = '이전 실행이 중단됨';
            j.stage4.failKind = 'input';
          }
          for (const k of ['xlsx', 'check', 'mgt2', 'resultTxt']) if (j.stage4[k] && !fs.existsSync(j.stage4[k])) j.stage4[k] = null;
          j.stage4.tail = [];
        }
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

  /** 앱 설정 화면에 노출하는 설정 키(모든 도면 공통인 것만, FEEDBACK_LOOP 3절). 값은 userData/config.json 에 저장, 다음 작업(4단계는 다음 검토)부터 적용.
   *  type: enum(values) / bool / int·num(min,max) / text(re: 정규식 이름). 검증에 실패한 값은 저장하지 않고 기존 값을 유지한다. */
  const RE = { bars: /^\d{1,2}-D\d{2}$/, stir: /^D\d{2}@\d{2,3}$/, list: /^D\d{2}(\s*,\s*D\d{2})*$/, combo: /^[\d.\s+\-*DLdl;,]+$/ };
  const SETTING_SPEC = {
    실행_단계: { type: 'enum', values: [1, 2, 3], dflt: 3 },
    보_생성: { type: 'bool', dflt: true },
    보_기준_거더길이: { type: 'int', min: 100, dflt: 4000 },
    보_베이폭_최소: { type: 'int', min: 100, dflt: 3000 },
    보_베이폭_2개: { type: 'int', min: 100, dflt: 8700 },
    보_베이폭_3개: { type: 'int', min: 100, dflt: 14000 },
    MGT_층고: { type: 'int', min: 100, dflt: 5000 },
    // 4단계 구조 검토(stage4_check.py)
    검토_fck_기둥: { type: 'num', min: 18, max: 100, dflt: 35 },
    검토_fck_보: { type: 'num', min: 18, max: 100, dflt: 27 },
    검토_fy: { type: 'num', min: 300, max: 700, dflt: 400 },
    검토_fy_전단: { type: 'num', min: 300, max: 700, dflt: 400 },
    검토_피복_기둥: { type: 'int', min: 20, max: 100, dflt: 40 },
    검토_피복_보: { type: 'int', min: 20, max: 100, dflt: 40 },
    검토_철근_후보: { type: 'text', re: 'list', dflt: 'D13,D16,D19,D22,D25,D29,D32' },
    검토_기둥_주근: { type: 'text', re: 'bars', dflt: '12-D22' },
    검토_기둥_띠철근: { type: 'text', re: 'stir', dflt: 'D10@300' },
    검토_거더_상부: { type: 'text', re: 'bars', dflt: '4-D22' },
    검토_거더_하부: { type: 'text', re: 'bars', dflt: '3-D22' },
    검토_거더_스터럽: { type: 'text', re: 'stir', dflt: 'D10@200' },
    검토_보_상부: { type: 'text', re: 'bars', dflt: '3-D19' },
    검토_보_하부: { type: 'text', re: 'bars', dflt: '3-D19' },
    검토_보_스터럽: { type: 'text', re: 'stir', dflt: 'D10@200' },
    검토_하중조합: { type: 'text', re: 'combo', dflt: '1.4D; 1.2D+1.6L' },
    검토_결과_단위: { type: 'enum', values: ['auto', 'kN,mm', 'kN,m', 'kN,cm', 'N,mm', 'tonf,m', 'tonf,mm'], dflt: 'auto' },
    검토_폭_증분: { type: 'int', min: 10, max: 500, dflt: 50 },
    검토_춤_증분: { type: 'int', min: 10, max: 500, dflt: 50 },
    검토_단면_최대배율: { type: 'int', min: 100, max: 400, dflt: 200 },
    검토_기둥_철근비_최대: { type: 'num', min: 1, max: 8, dflt: 4 },
  };
  const SETTING_KEYS = Object.keys(SETTING_SPEC);
  const SETTING_FALLBACK = Object.fromEntries(SETTING_KEYS.map((k) => [k, SETTING_SPEC[k].dflt]));
  /** 설정값 검증 → 저장할 값 또는 undefined(무효) */
  function validSetting(k, v) {
    const s = SETTING_SPEC[k];
    if (!s) return undefined;
    if (s.type === 'bool') return Boolean(v);
    if (s.type === 'enum') {
      const hit = s.values.find((x) => String(x) === String(v).trim());
      return hit === undefined ? undefined : hit;
    }
    if (s.type === 'int' || s.type === 'num') {
      const n = Number(v);
      if (!Number.isFinite(n) || n < s.min || (s.max !== undefined && n > s.max)) return undefined;
      return s.type === 'int' ? Math.round(n) : Math.round(n * 100) / 100;
    }
    const t = String(v ?? '').trim().replace(/\s+/g, ' ');
    if (!t || t.length > 200 || (s.re && !RE[s.re].test(t))) return undefined;
    return t;
  }
  function readJson(p) {
    try {
      return JSON.parse(fs.readFileSync(p, 'utf8').replace(/^﻿/, ''));
    } catch {
      return null;
    }
  }
  function getSettings() {
    ensureConfig();
    const dflt = { ...SETTING_FALLBACK, ...pick(readJson(path.join(APP, 'config.default.json')) || {}) };
    const cur = { ...dflt, ...pick(readJson(CFG) || {}) };
    return { values: cur, defaults: dflt, spec: SETTING_SPEC };
  }
  function pick(obj) {
    const o = {};
    for (const k of SETTING_KEYS) if (obj[k] !== undefined) o[k] = obj[k];
    return o;
  }
  function setSettings(vals) {
    ensureConfig();
    const cfg = readJson(CFG) || {};
    const rejected = [];
    for (const k of SETTING_KEYS) {
      if (vals[k] === undefined) continue;
      const v = validSetting(k, vals[k]);
      if (v === undefined) rejected.push(k);
      else cfg[k] = v;
    }
    fs.writeFileSync(CFG, JSON.stringify(cfg, null, 2) + '\n');
    log('설정 저장', pick(cfg), rejected.length ? `무효(유지): ${rejected.join(',')}` : '');
    return { ...getSettings(), rejected, spec: SETTING_SPEC };
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
    const st = getSettings().values;
    j.opts = { stage: Number(st['실행_단계']) || 3, beams: Boolean(st['보_생성']) }; // 이 작업에 적용된 실행 범위·보 생성(카드 표시용)
    j.total = (path.extname(j.src).toLowerCase() === '.dwg' ? 1 : 0) + 6 + (j.opts.stage >= 3 ? 1 : 0); // 변환·XREF·전개·1단계·모델·거더보(또는 건너뜀)·DXF·MGT
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
      const elem = path.join(j.outdir, `${base}_MIDAS_elements.json`);
      j.report = fs.existsSync(rep) ? rep : null;
      j.mgt = fs.existsSync(mgt) ? mgt : null;
      j.elements = fs.existsSync(elem) ? elem : null; // 4단계 구조 검토용 요소 대응표
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

  function setErrorReport(id, er, which = 'job') {
    const j = jobs.find((x) => x.id === id);
    if (!j) return false;
    if (which === 'stage4') {
      if (j.stage4) j.stage4.errorReport = er;
    } else j.errorReport = er;
    saveJobs();
    emit();
    return true;
  }

  // ---------------- 4단계 구조 검토(stage4_check.py): MIDAS 해석 결과표 첨부 → 검토 → 엑셀, 승인 → 수정 MGT(stage4_apply.py) ----------------
  let proc4 = null;
  const S4_STEPS = 4; // 요소 대응표 읽기 / 결과표 읽기 / 단면 검토 / 결과 저장
  function runStage4(id, txtPath) {
    const j = jobs.find((x) => x.id === id);
    if (!j || j.state !== 'done') return { ok: false, message: '완료된 작업에서만 검토할 수 있습니다' };
    if (!j.mgt || !j.elements || !fs.existsSync(j.elements)) return { ok: false, message: '3단계 MGT·요소 대응표가 없습니다 (3단계까지 실행한 작업만 가능, 1.5.0 이후 생성분)' };
    if (proc4) return { ok: false, message: '다른 검토가 진행 중입니다' };
    if (!txtPath || !fs.existsSync(txtPath)) return { ok: false, message: '결과표 파일이 없습니다' };
    const dir = path.join(j.outdir, 'stage4');
    fs.rmSync(dir, { recursive: true, force: true });
    fs.mkdirSync(dir, { recursive: true });
    const base = path.basename(j.src, path.extname(j.src));
    const ext = path.extname(txtPath) || '.txt';
    const txt = path.join(dir, `${base}_MIDAS_결과${ext}`);
    fs.copyFileSync(txtPath, txt);
    j.stage4 = { state: 'running', started: Date.now(), ended: 0, resultTxt: txt, resultName: path.basename(txtPath), step: '검토 시작', stepIdx: 0, total: S4_STEPS, tail: [], summary: null, xlsx: null, check: null, mgt2: null, applied: null, errorReport: null };
    saveJobs();
    emit();
    log(`4단계 검토: ${j.name} ← ${txtPath}`);
    proc4 = spawn(PY, [path.join(APP, 'stage4_check.py'), j.elements, txt, dir, '--config', CFG], { cwd: APP, env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' }, windowsHide: true });
    let buf = '';
    let err = '';
    const s = j.stage4;
    proc4.stdout.on('data', (chunk) => {
      buf += chunk.toString('utf8');
      let i;
      while ((i = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, i).replace(/\r$/, '');
        buf = buf.slice(i + 1);
        if (!line.trim()) continue;
        if (line.startsWith('=== ')) {
          s.step = line.slice(4).trim();
          s.stepIdx++;
        } else if (line.startsWith('SUMMARY=')) {
          try {
            s.summary = JSON.parse(line.slice(8));
          } catch {
            /* */
          }
        } else {
          s.tail.push(line);
          if (s.tail.length > 30) s.tail.splice(0, s.tail.length - 30);
        }
        emit();
      }
    });
    proc4.stderr.on('data', (c) => {
      err += c.toString('utf8');
    });
    proc4.on('error', (e) => {
      err += `\n실행 오류: ${e.message}`;
    });
    proc4.on('close', (code) => {
      proc4 = null;
      s.ended = Date.now();
      const xlsx = path.join(dir, 'check.xlsx');
      const check = path.join(dir, 'check.json');
      if (code === 0 && fs.existsSync(xlsx) && fs.existsSync(check) && s.summary) {
        s.state = 'done';
        s.xlsx = xlsx;
        s.check = check;
        s.step = '완료';
        s.message = `검토 완료 (${Math.round((s.ended - s.started) / 1000)}초) — OK ${s.summary.ok} / NG ${s.summary.ng}${s.summary.none ? ` / 결과 없음 ${s.summary.none}` : ''}`;
      } else {
        s.state = 'failed';
        const lines = err.trim().split('\n').filter((l) => l.trim());
        const last = lines.slice(-1)[0] || `종료 코드 ${code}`;
        s.failReason = /^SystemExit: /.test(last) ? last.slice(12) : last;
        // 설정 오류는 사용자가 고칠 것(입력), 그 외(결과표 형식 미인식 포함)는 프로그램 쪽에서 봐야 하므로 자동 오류 보고(첨부: 결과표)
        s.failKind = /설정 오류/.test(s.failReason) ? 'input' : 'error';
        s.message = `검토 실패: ${s.failReason}`;
        try {
          fs.writeFileSync(path.join(dir, 'check_error.txt'), err);
        } catch {
          /* */
        }
      }
      log(`4단계 ${s.state}: ${j.name} ${s.message}`);
      saveJobs();
      emit();
      if (s.state === 'failed' && s.failKind === 'error' && onError) onError(j, 'stage4');
    });
    return { ok: true, message: '검토 시작' };
  }

  /** 승인: 추천 치수대로 *SECTION 만 바꾼 수정 MGT 생성(동기, 수 초) */
  function applyStage4(id) {
    const j = jobs.find((x) => x.id === id);
    const s = j && j.stage4;
    if (!s || s.state !== 'done' || !s.check || !fs.existsSync(s.check)) return { ok: false, message: '검토 결과가 없습니다' };
    if (!j.mgt || !fs.existsSync(j.mgt)) return { ok: false, message: '원본 MGT 가 없습니다' };
    const base = path.basename(j.src, path.extname(j.src));
    const out = path.join(path.dirname(s.check), `${base}_MIDAS_수정.mgt`);
    const r = spawnSync(PY, [path.join(APP, 'stage4_apply.py'), j.mgt, s.check, out], { cwd: APP, env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' }, windowsHide: true, encoding: 'utf8' });
    const o = (r.stdout || '') + (r.stderr || '');
    const m = /SUMMARY=(.+)/.exec(o);
    if (r.status !== 0 || !m || !fs.existsSync(out)) {
      log('4단계 승인 실패', o);
      return { ok: false, message: `수정 MGT 생성 실패: ${o.trim().split('\n').pop()}` };
    }
    try {
      s.applied = { ...JSON.parse(m[1]), at: new Date().toISOString() };
    } catch {
      s.applied = { at: new Date().toISOString() };
    }
    s.mgt2 = out;
    saveJobs();
    emit();
    log(`4단계 승인: ${j.name} → ${out}`);
    return { ok: true, message: `수정 MGT 생성됨 — 단면 교체 ${s.applied.changed ?? '?'}개 요소`, file: out };
  }

  function stage4Busy() {
    return Boolean(proc4);
  }

  /** 전송 못 한 오류 보고(오프라인 등) 목록 — 시작 때 재시도용 */
  function pendingErrorReports() {
    return jobs.filter((j) => j.state === 'failed' && j.failKind === 'error' && !(j.errorReport && j.errorReport.sent));
  }

  return { enqueue, cancel, remove, setFeedback, setErrorReport, pendingErrorReports, state, versions, ensureInstalled, ensureConfig, getSettings, setSettings, runStage4, applyStage4, stage4Busy, isIdle: () => !current && !proc4, job: (id) => jobs.find((j) => j.id === id) || null, paths: { APP, RT, CFG, PY, RESULTS }, EXT };
}

module.exports = { createEngine, cmpVer, readText, swapDir };
