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
const MGT_EXT = '.mgt'; // 4단계 단독 실행: 수작업을 마친 MIDAS 모델(.mgt)을 바로 받아 구조 검토(1.6.0)

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
            if (j.kind === 's4') {
              // 구조 검토 작업: 실패로 남기지 않고 결과표를 다시 넣기를 기다린다
              j.tableNote = { name: j.stage4.resultName || '', text: '검토하던 중에 프로그램이 꺼졌습니다. 결과표를 다시 넣어 주세요.', at: Date.now() };
              j.stage4 = null;
              continue;
            }
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

  /** 골조 모델링 값(작업마다 정함, 1.9.0): 실행 범위·보 생성·보 수치 4개·층고. 설정 화면이 아니라 도면을 고른 뒤 조건 입력 화면에서 받는다 */
  const COND_KEYS = ['실행_단계', '보_생성', '보_기준_거더길이', '보_베이폭_최소', '보_베이폭_2개', '보_베이폭_3개', 'MGT_층고'];
  const condOf = (obj) => Object.fromEntries(COND_KEYS.filter((k) => obj && obj[k] !== undefined).map((k) => [k, obj[k]]));
  /** 조건 입력 화면에 채워 둘 값 = 항상 기본값(11-18 사용자 지시 — 1.9.0 은 앞 작업에 쓴 값·예전에 설정에 저장해 둔 값을 가져왔으나 없앰).
   *  [값 바꿔 다시 모델링] 만 그 작업의 값에서 시작한다(화면 쪽 openCond) */
  function condDefaults() {
    const defaults = condOf(getSettings().defaults);
    return { values: { ...defaults }, defaults, from: 'default' };
  }
  /** 조건 검증 → {cond} 또는 {bad:[키]}. 빠진 값은 채워 둘 값으로 메운다 */
  function checkCond(vals) {
    const base = condDefaults().values;
    const cond = {};
    const bad = [];
    for (const k of COND_KEYS) {
      if (!vals || vals[k] === undefined) {
        cond[k] = base[k];
        continue;
      }
      const v = validSetting(k, vals[k]);
      if (v === undefined) bad.push(k);
      else cond[k] = v;
    }
    return bad.length ? { bad } : { cond };
  }
  /** 골조 모델링 시작: 도면 1개 + 이 작업에 쓸 값 */
  function startModel(file, vals) {
    if (sniff(file) !== 'drawing') return { ok: false, message: '도면(DWG·DXF) 파일을 찾을 수 없습니다. 파일을 옮겼거나 지웠다면 [+ 골조 모델링] 으로 다시 골라 주세요' };
    const c = checkCond(vals);
    if (c.bad) return { ok: false, message: `값을 확인해 주세요: ${c.bad.join(', ')}`, bad: c.bad };
    const id = enqueue([file], { cond: c.cond });
    return id ? { ok: true, id } : { ok: false, message: '같은 도면을 이미 모델링하고 있습니다' };
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

  /** 파일 종류를 확장자가 아니라 내용으로 가린다(1.8.0): 'drawing'(도면) | 'model'(MIDAS 모델 MGT) | 'table'(해석 결과표로 넣은 파일) | null(없는 파일).
   *  모델과 결과표를 어느 칸에 넣든, 함께 끌어 놓든 알아서 나누기 위한 것 — 결과표가 맞는지는 검토 스크립트가 판단한다 */
  function sniff(p) {
    let head;
    try {
      if (!fs.statSync(p).isFile()) return null;
      const fd = fs.openSync(p, 'r');
      const b = Buffer.alloc(65536);
      const n = fs.readSync(fd, b, 0, b.length, 0);
      fs.closeSync(fd);
      head = b.subarray(0, n);
    } catch {
      return null;
    }
    const ext = path.extname(p).toLowerCase();
    if (EXT.includes(ext)) return 'drawing';
    if (head.length >= 4 && (head.readUInt32LE(0) === 0xe011cfd0 || head.readUInt32LE(0) === 0x04034b50)) return 'table'; // 엑셀 .xls(OLE2)·.xlsx(zip)
    if (/^\s*\*(VERSION|UNIT|NODE|ELEMENT)\b/m.test(head.toString('latin1').toUpperCase())) return 'model';
    return ext === MGT_EXT ? 'model' : 'table';
  }

  /** 넣은 파일 목록 → [{path, name, kind, mtime}] (없는 파일은 뺌) */
  function describe(paths) {
    const out = [];
    for (const p of paths || []) {
      const kind = p ? sniff(p) : null;
      if (kind) out.push({ path: p, name: path.basename(p), kind, mtime: fs.statSync(p).mtimeMs });
    }
    return out;
  }

  /** 구조 검토 시작: 모델(필수) + 결과표(있으면 모델을 읽은 뒤 곧바로 검토) */
  function startReview(modelPath, tablePath) {
    if (sniff(modelPath) !== 'model') return { ok: false, message: 'MIDAS 모델(.mgt) 파일이 아닙니다' };
    const id = enqueue([modelPath], { table: tablePath && sniff(tablePath) ? tablePath : null });
    return id ? { ok: true, id } : { ok: false, message: '같은 모델을 이미 읽고 있습니다' };
  }

  function enqueue(paths, opts = {}) {
    let added = null;
    for (const p of paths || []) {
      const kind = p ? sniff(p) : null;
      const s4 = kind === 'model'; // MIDAS 모델 = 구조 검토 작업(모델 읽기 → 결과표 → 검토)
      if (!s4 && kind !== 'drawing') continue;
      if (jobs.some((j) => j.src === p && (j.state === 'queued' || j.state === 'running'))) continue;
      const id = ++seq;
      const base = path.basename(p, path.extname(p));
      const job = { id, src: p, name: path.basename(p), state: 'queued', step: '', stepIdx: 0, total: 0, created: Date.now(), started: 0, ended: 0, outdir: path.join(RESULTS, `${id}_${base}`), result: null, report: null, message: '', feedback: null, log: [] };
      if (!s4) job.cond = opts.cond || condDefaults().values; // 이 작업에 쓸 모델링 값(조건 입력 화면에서 받은 값)
      if (s4) {
        job.kind = 's4';
        job.srcMtime = fs.statSync(p).mtimeMs;
        if (opts.table) job.pendingTable = opts.table; // 함께 넣은 결과표: 모델을 다 읽으면 바로 검토
      }
      jobs.push(job);
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

  /** 4단계 단독 작업: 모델 MGT 를 결과 폴더로 복사(검토 시점의 모델을 고정)하고 mgt_import.py 로 요소 대응표를 만든다. 끝나면 done → 카드에서 결과표 첨부 */
  function runImport(j) {
    current = j;
    j.state = 'running';
    j.started = Date.now();
    j.total = 1;
    j.stepIdx = 0;
    j.step = '모델 읽기';
    j.model = null;
    fs.mkdirSync(j.outdir, { recursive: true });
    saveJobs();
    emit();
    const base = path.basename(j.src, path.extname(j.src));
    const model = path.join(j.outdir, `${base}.mgt`);
    const elem = path.join(j.outdir, `${base}_elements.json`);
    let err = '';
    const finish = (code) => {
      j.ended = Date.now();
      if (j.state === 'cancelled') {
        j.message = '취소됨';
      } else if (code === 0 && fs.existsSync(elem) && j.model) {
        j.state = 'done';
        j.step = '완료';
        j.mgt = model;
        j.elements = elem;
        j.message = `모델 읽기 완료 — 검토 대상 ${j.model.elements}개`;
      } else {
        j.state = 'failed';
        j.message = `모델 읽기 실패 (코드 ${code})`;
        const lines = err.trim().split('\n').filter((l) => l.trim());
        const last = lines.slice(-1)[0] || j.log.slice(-1)[0] || '';
        const m = /\[원인\]\s*(입력|오류)\s*[—-]\s*(.+)/.exec(last);
        j.failKind = m ? (m[1] === '입력' ? 'input' : 'error') : 'error';
        j.failReason = m ? m[2].trim() : last.trim();
        j.errorReport = null;
        if (err.trim()) j.log.push(...lines.slice(-6));
      }
      log(`${j.state}: ${j.name} ${j.message}`);
      proc = null;
      current = null;
      const table = j.pendingTable;
      delete j.pendingTable;
      saveJobs();
      emit();
      if (j.state === 'failed' && j.failKind === 'error' && onError) onError(j);
      if (j.state === 'done' && table) {
        const r = runStage4(j.id, table);
        if (!r.ok) {
          j.tableNote = { name: path.basename(table), text: r.message, at: Date.now() };
          saveJobs();
          emit();
        }
      }
      next();
    };
    try {
      fs.copyFileSync(j.src, model);
    } catch (e) {
      err = `[원인] 입력 — 모델 파일을 읽을 수 없음: ${e.message}`;
      finish(1);
      return;
    }
    log(`4단계 모델 읽기: ${j.src}`);
    proc = spawn(PY, [path.join(APP, 'mgt_import.py'), model, elem], { cwd: APP, env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' }, windowsHide: true });
    let buf = '';
    let closed = false;
    proc.stdout.on('data', (chunk) => {
      buf += chunk.toString('utf8');
      let i;
      while ((i = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, i).replace(/\r$/, '');
        buf = buf.slice(i + 1);
        if (!line.trim()) continue;
        if (line.startsWith('SUMMARY=')) {
          try {
            j.model = JSON.parse(line.slice(8));
          } catch {
            /* */
          }
        } else {
          j.log.push(line.length > 600 ? line.slice(0, 600) + ' …' : line);
        }
      }
    });
    proc.stderr.on('data', (c) => {
      err += c.toString('utf8');
    });
    proc.on('error', (e) => {
      err += `\n실행 오류: ${e.message}`;
      if (!closed) {
        closed = true;
        finish(-1);
      }
    });
    proc.on('close', (code) => {
      if (closed) return;
      closed = true;
      finish(code);
    });
  }

  function run(j) {
    if (j.kind === 's4') return runImport(j);
    current = j;
    j.state = 'running';
    j.started = Date.now();
    if (!j.cond) j.cond = condDefaults().values;
    const st = j.cond;
    j.opts = { stage: Number(st['실행_단계']) || 3, beams: Boolean(st['보_생성']) }; // 이 작업에 적용된 실행 범위·보 생성(목록 표시용)
    j.total = (path.extname(j.src).toLowerCase() === '.dwg' ? 1 : 0) + 6 + (j.opts.stage >= 3 ? 1 : 0); // 변환·XREF·전개·1단계·모델·거더보(또는 건너뜀)·DXF·MGT
    j.step = '시작';
    fs.mkdirSync(j.outdir, { recursive: true });
    saveJobs();
    emit();
    // 작업별 값: 공통 config.json 에 이 작업의 모델링 값을 덮어쓴 사본을 결과 폴더에 두고 그 파일로 실행한다
    const jobCfg = path.join(j.outdir, 'job_config.json');
    fs.writeFileSync(jobCfg, JSON.stringify({ ...(readJson(CFG) || {}), ...j.cond }, null, 2) + '\n');
    const args = [path.join(APP, 'run_pipeline.py'), j.src, '--out', j.outdir, '--config', jobCfg];
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

  /** 작업 결과 화면에서 쓰던 피드백(종류·내용)을 작업마다 저장 — 다른 화면에 다녀오거나 프로그램을 다시 켜도 남음. null = 지움. 화면을 다시 그리지 않도록 emit 하지 않는다 */
  function setDraft(id, draft) {
    const j = jobs.find((x) => x.id === id);
    if (!j) return false;
    if (draft && typeof draft.text === 'string') j.draft = { text: draft.text.slice(0, 5000), kind: draft.kind === 'file' ? 'file' : 'rule' };
    else delete j.draft;
    saveJobs();
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
    // 1.6.0: 4단계는 수작업(MIDAS 수정·해석)을 마친 모델 MGT 로만 검토한다. 3단계가 만든 MGT 를 고치면 요소 번호가 달라져
    // 도면 작업의 대응표로는 엉뚱한 요소를 검토하게 되므로 도면 작업 카드에서는 실행하지 않는다.
    if (j.kind !== 's4') return { ok: false, message: '구조 검토는 수작업을 마친 MIDAS 모델(.mgt)로 시작합니다 — 위의 [+ 구조 검토] 를 눌러 모델을 선택해 주세요' };
    if (!j.mgt || !j.elements || !fs.existsSync(j.elements)) return { ok: false, message: '모델 MGT·요소 대응표가 없습니다 — 모델을 다시 선택해 주세요' };
    if (proc4) return { ok: false, message: '다른 검토가 진행 중입니다' };
    if (!txtPath || !fs.existsSync(txtPath)) return { ok: false, message: '결과표 파일이 없습니다' };
    if (sniff(txtPath) === 'model') return { ok: false, message: '넣은 파일은 MIDAS 모델(.mgt)입니다. 여기에는 해석 결과표(Beam Force)를 넣어 주세요' };
    // 새 폴더(stage4_new)에서 검토하고 끝난 뒤에 바꿔 넣는다 — 결과표가 아닌 파일을 넣어도 앞서 끝낸 검토 결과가 지워지지 않게(1.8.0)
    const final = path.join(j.outdir, 'stage4');
    const dir = path.join(j.outdir, 'stage4_new');
    const prev = j.stage4 && j.stage4.state === 'done' ? j.stage4 : null;
    const prevFb = j.feedback;
    fs.rmSync(dir, { recursive: true, force: true });
    fs.mkdirSync(dir, { recursive: true });
    const base = path.basename(j.src, path.extname(j.src));
    const ext = path.extname(txtPath) || '.txt';
    const txtName = j.kind === 's4' ? `${base}_결과표${ext}` : `${base}_MIDAS_결과${ext}`;
    const txt = path.join(dir, txtName);
    fs.copyFileSync(txtPath, txt);
    if (j.feedback && j.feedback.skipped) j.feedback = null; // 다시 검토하면 결과가 달라지므로 "문제 없음" 표시는 지움(새 결과로 다시 판단)
    delete j.tableNote;
    j.stage4 = { state: 'running', started: Date.now(), ended: 0, resultTxt: txt, resultName: path.basename(txtPath), tableSrc: txtPath, tableMtime: fs.statSync(txtPath).mtimeMs, step: '검토 시작', stepIdx: 0, total: S4_STEPS, tail: [], summary: null, xlsx: null, check: null, mgt2: null, applied: null, errorReport: null };
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
      const ok = code === 0 && fs.existsSync(path.join(dir, 'check.xlsx')) && fs.existsSync(path.join(dir, 'check.json')) && s.summary;
      let report = null; // 자동 오류 보고에 쓸 작업 정보
      if (ok) {
        s.state = 'done';
        s.step = '완료';
        s.message = `검토 완료 (${Math.round((s.ended - s.started) / 1000)}초) — OK ${s.summary.ok} / NG ${s.summary.ng}${s.summary.none ? ` / 결과 없음 ${s.summary.none}` : ''}`;
      } else {
        s.state = 'failed';
        const lines = err.trim().split('\n').filter((l) => l.trim());
        const last = lines.slice(-1)[0] || `종료 코드 ${code}`;
        s.failReason = /^SystemExit: /.test(last) ? last.slice(12) : last;
        // 입력 오류·설정 오류 = 사용자가 고칠 것. 머리글을 못 찾은 파일 = 결과표가 아닌 파일(해석 기록 .OUT 등)이거나 아직 모르는 표 형식
        const notTable = /머리글을 찾지 못함/.test(s.failReason);
        s.failKind = /설정 오류|입력 오류/.test(s.failReason) || notTable ? 'input' : 'error';
        s.message = `검토 실패: ${s.failReason}`;
        try {
          fs.writeFileSync(path.join(dir, 'check_error.txt'), err);
        } catch {
          /* */
        }
        if (s.failKind === 'input' && j.kind === 's4') {
          // 넣은 파일 문제는 검토 실패로 남기지 않는다: 결과표 칸에 이유만 적고 다시 넣기를 기다린다(앞서 끝낸 검토 결과·"문제 없음" 표시는 그대로).
          // 결과표가 아닌 것으로 본 파일은 모르는 표 형식일 수 있어 그 파일을 붙여 자동 보고만 조용히 보낸다.
          const rej = path.join(j.outdir, 'stage4_rejected');
          try {
            fs.rmSync(rej, { recursive: true, force: true });
            fs.renameSync(dir, rej);
          } catch {
            /* */
          }
          const why = notTable ? '이 파일에서 Beam Force 표를 찾지 못했습니다. MIDAS 의 Results → Result Tables → Beam → Force 표에서 Export to Excel 로 저장한 파일을 넣어 주세요.' : String(s.failReason).replace(/^(입력|설정) 오류:\s*/, '');
          j.tableNote = { name: s.resultName, text: why, at: s.ended, settings: /설정 오류/.test(s.failReason) };
          if (notTable) report = { ...j, stage4: { ...s, resultTxt: path.join(rej, txtName) } };
          j.stage4 = prev;
          j.feedback = prevFb;
          log(`4단계 결과표 다시 넣기 대기: ${j.name} ${s.message}`);
          saveJobs();
          emit();
          if (report && onError) onError(report, 'stage4');
          return;
        }
        if (s.failKind === 'error') report = j;
      }
      // 검토를 마쳤거나 프로그램 오류: 새 폴더를 stage4 로 바꿔 넣는다
      try {
        fs.rmSync(final, { recursive: true, force: true });
        fs.renameSync(dir, final);
        s.resultTxt = path.join(final, txtName);
        if (ok) {
          s.xlsx = path.join(final, 'check.xlsx');
          s.check = path.join(final, 'check.json');
        }
      } catch (e) {
        log('4단계 결과 폴더 교체 실패', e);
        if (ok) {
          s.xlsx = path.join(dir, 'check.xlsx');
          s.check = path.join(dir, 'check.json');
        }
      }
      log(`4단계 ${s.state}: ${j.name} ${s.message}`);
      saveJobs();
      emit();
      if (report && onError) onError(report, 'stage4');
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
    const out = path.join(path.dirname(s.check), j.kind === 's4' ? `${base}_수정.mgt` : `${base}_MIDAS_수정.mgt`);
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

  /** [건너뛰기](결과에 문제 없음)로 표시했지만 표본을 아직 서버로 못 보낸 작업 — 시작 때 재시도용 */
  function pendingSamples() {
    return jobs.filter((j) => j.state === 'done' && j.feedback && j.feedback.skipped && !(j.feedback.sample && j.feedback.sample.sent));
  }

  return { enqueue, describe, startReview, startModel, condDefaults, cancel, remove, setFeedback, setDraft, setErrorReport, pendingErrorReports, pendingSamples, state, versions, ensureInstalled, ensureConfig, getSettings, setSettings, runStage4, applyStage4, stage4Busy, isIdle: () => !current && !proc4, job: (id) => jobs.find((j) => j.id === id) || null, paths: { APP, RT, CFG, PY, RESULTS }, EXT, MGT_EXT };
}

module.exports = { createEngine, cmpVer, readText, swapDir };
