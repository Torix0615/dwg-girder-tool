'use strict';
/**
 * 작업별 피드백: 내용 + 종류(공통 규칙/이 파일에만 해당) + 원본·결과 DXF·report·config·로그를 zip 으로 묶어(app/feedback.py)
 * 서버(app/feedback_server.txt: 주소 1줄, 키 없음 — 업로드는 공개 엔드포인트)로 전송(진행률). 서버가 없거나 실패하면 바탕화면 zip 으로 폴백.
 */
const fs = require('fs');
const path = require('path');
const os = require('os');
const { spawnSync } = require('child_process');
const { Readable, Transform } = require('stream');
const { readText } = require('./engine.cjs');
const classify = require('../renderer/classify.js'); // 프로그램 화면·기능 / 생성 규칙 자동 분류(렌더러와 공용)

const SCOPE_LABEL = { file: '이 파일에만 해당', all: '공통 규칙', unknown: '모름', error: '자동 오류 보고', general: '작업 없이 보낸 피드백', sample: '문제 없음 표본([건너뛰기])' };
const KIND_LABEL = classify.LABEL; // ui / rule / unknown

function desktopDir() {
  const r = spawnSync('powershell', ['-NoProfile', '-Command', '[Environment]::GetFolderPath("Desktop")'], { windowsHide: true, encoding: 'utf8' });
  const p = (r.stdout || '').trim();
  return p && fs.existsSync(p) ? p : path.join(os.homedir(), 'Desktop');
}

function serverInfo(engine, bundledApp) {
  const txt = readText(path.join(engine.paths.APP, 'feedback_server.txt')) || readText(path.join(bundledApp, 'feedback_server.txt'));
  const url = txt.split(/\r?\n/)[0].trim(); // 주소만. 키는 두지 않음(업로드는 공개 엔드포인트, 앱 배포물에 비밀값 없음)
  return /^https?:\/\//.test(url) ? { url: url.replace(/\/+$/, '') } : null;
}

function buildZip({ root, engine, text, scope, category, job, log, out }) {
  const tmp = path.join(root, 'tmp');
  fs.mkdirSync(tmp, { recursive: true });
  const auto = classify(text);
  const head = [`구분: ${SCOPE_LABEL[scope] || scope || '-'}`];
  if (category) head.push(`종류(사용자 선택): ${KIND_LABEL[category] || category}`);
  head.push(`자동 분류: ${KIND_LABEL[auto.category]} (UI: ${auto.ui.join('·') || '-'} / 규칙: ${auto.rule.join('·') || '-'})`);
  const isS4 = Boolean(job && job.kind === 's4'); // 4단계 단독 작업: 원본 = 모델 MGT(결과 폴더 사본이 있으면 사본만 첨부 — 같은 파일 이름 중복 방지)
  if (isS4) head.push(`대상 모델(구조 검토): ${job.src}`, `모델 읽기: ${job.message}${job.model ? ` / 기둥 ${job.model.col}·거더 ${job.model.girder}·보 ${job.model.beam} / 제외 ${JSON.stringify(job.model.skipped || {})}` : ''}`);
  else if (job) head.push(`대상 도면: ${job.src}`, `결과: ${job.result ? path.basename(job.result) : '(실패)'} / ${job.message}`);
  else head.push('대상 도면: (없음 — 작업 없이 보낸 피드백)');
  const s4 = job && job.stage4;
  if (s4) head.push(`구조 검토: ${s4.state} / ${s4.message || ''} / 결과표 ${s4.resultName || '-'}`);
  const s4dir = s4 && s4.resultTxt ? path.dirname(s4.resultTxt) : null;
  const attach = job
    ? [isS4 && job.mgt && fs.existsSync(job.mgt) ? null : job.src, job.result, job.mgt, job.report, s4 && s4.resultTxt, s4 && s4.xlsx, s4 && s4.mgt2, s4dir && path.join(s4dir, 'check_log.txt'), s4dir && path.join(s4dir, 'check_error.txt')].filter((p) => p && fs.existsSync(p))
    : [];
  const tf = path.join(tmp, 'feedback.txt');
  fs.writeFileSync(tf, head.join('\n') + '\n\n' + String(text || '').trim() + '\n', 'utf8');
  const extra = ['데스크탑 로그 최근 50줄:'];
  try {
    extra.push(...fs.readFileSync(path.join(root, 'desktop.log'), 'utf8').trim().split('\n').slice(-50));
  } catch {
    /* */
  }
  const ef = path.join(tmp, 'feedback_extra.txt');
  fs.writeFileSync(ef, extra.join('\n'), 'utf8');
  const args = [path.join(engine.paths.APP, 'feedback.py'), '--text', tf, '--extra', ef, '--out', out];
  for (const a of attach) args.push('--attach', a);
  const r = spawnSync(engine.paths.PY, args, { cwd: engine.paths.APP, env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' }, windowsHide: true, encoding: 'utf8' });
  const o = (r.stdout || '') + (r.stderr || '');
  const m = /OUT=(.+)/.exec(o);
  if (r.status !== 0 || !m) {
    log('피드백 zip 생성 실패', o);
    throw new Error(`피드백 파일 생성 실패: ${o.trim().split('\n').pop()}`);
  }
  return m[1].trim();
}

async function upload({ srv, file, meta, onProgress }) {
  const size = fs.statSync(file).size;
  let sent = 0;
  let last = 0;
  const counter = new Transform({
    transform(chunk, _e, cb) {
      sent += chunk.length;
      if (Date.now() - last > 200) {
        last = Date.now();
        onProgress(sent / size);
      }
      cb(null, chunk);
    },
  });
  const body = Readable.toWeb(fs.createReadStream(file).pipe(counter));
  const res = await fetch(srv.url + '/api/feedback', {
    method: 'POST',
    headers: { 'x-meta': Buffer.from(JSON.stringify(meta), 'utf8').toString('base64'), 'content-type': 'application/zip', 'content-length': String(size) },
    body,
    duplex: 'half',
    signal: AbortSignal.timeout(30 * 60e3),
  });
  const j = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(j.error || `HTTP ${res.status}`);
  onProgress(1);
  return j;
}

/** @returns {Promise<{ok:boolean, message:string, file?:string, id?:string, sent:boolean}>} */
/**
 * job 이 있으면 작업 카드 피드백(원본·결과 첨부), scope='general' 이면 도면 작업 없이 보내는 피드백(첨부 없음).
 * category(ui/rule/unknown) = 사용자 선택(일반 패널) 또는 앱의 자동 분류(작업 카드). 메타에 category_auto 도 함께 보내 개발 PC 가 "프로그램(UI·기능)" 요청을 가려낸다.
 */
async function send({ root, engine, bundledApp, appVersion, text, scope, category, job, log, onProgress = () => {} }) {
  if (!job && scope !== 'general') return { ok: false, sent: false, message: '작업을 찾을 수 없습니다' };
  if (job && job.feedback && job.feedback.sent) return { ok: false, sent: true, message: '이미 전송한 작업입니다' };
  if (job && job.feedback && job.feedback.skipped) return { ok: false, sent: false, message: '문제 없음으로 표시한 작업입니다' };
  if (!String(text || '').trim()) return { ok: false, sent: false, message: '내용이 비어 있습니다' };
  const stamp = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().replace(/[-:T]/g, '').slice(0, 13).replace(/(\d{8})(\d{4})/, '$1_$2');
  const name = `골조거더보_피드백_${stamp}.zip`;
  const srv = serverInfo(engine, bundledApp);
  onProgress({ progress: 0, message: '파일 묶는 중…' });
  const zip = buildZip({ root, engine, text, scope, category, job, log, out: path.join(root, 'tmp', name) });
  const size = fs.statSync(zip).size;
  const at = new Date().toISOString();
  const base = { text: String(text).slice(0, 2000), scope, at };
  if (srv) {
    const meta = {
      kind: job ? 'feedback' : 'general', version: appVersion, app: engine.versions().app, scope, category: category || 'unknown', category_auto: classify(text).category,
      job: job ? path.basename(job.src) : '-', pc: os.hostname(), text: String(text).slice(0, 2000),
    };
    try {
      onProgress({ progress: 0, message: `전송 중 (${(size / 1e6).toFixed(1)} MB)` });
      const r = await upload({ srv, file: zip, meta, onProgress: (p) => onProgress({ progress: p, message: `전송 중 ${((p * size) / 1e6).toFixed(1)}/${(size / 1e6).toFixed(1)} MB` }) });
      fs.rmSync(zip, { force: true });
      log('피드백 전송 완료', r.id, size, job ? '' : '(일반)');
      if (job) engine.setFeedback(job.id, { ...base, sent: true, id: r.id });
      return { ok: true, sent: true, id: r.id, message: `전송 완료 (${(size / 1e6).toFixed(1)} MB). 반영되면 자동 업데이트됩니다.` };
    } catch (e) {
      log('피드백 전송 실패', e);
    }
  } else {
    log('feedback_server.txt 없음 → 파일로 저장');
  }
  const out = path.join(desktopDir(), name);
  try {
    fs.copyFileSync(zip, out);
    fs.rmSync(zip, { force: true });
  } catch (e) {
    return { ok: false, sent: false, message: `전송 실패, 파일 저장도 실패: ${e.message}` };
  }
  if (job) engine.setFeedback(job.id, { ...base, sent: true, file: out });
  return { ok: true, sent: true, file: out, message: `서버 전송이 안 되어 바탕화면에 저장했습니다: ${name} — 카카오톡·메일로 보내 주세요` };
}

/** 프로그램 오류 자동 보고(피드백과 별개): 보고서·로그·원본 도면을 서버로. 서버가 없거나 실패하면 false(다음 실행 때 재시도) */
async function sendError({ root, engine, bundledApp, appVersion, job, log, which = 'job' }) {
  const srv = serverInfo(engine, bundledApp);
  if (!srv) return { ok: false, message: '서버 주소 없음' };
  const s4 = job.stage4 || {};
  const text =
    which === 'stage4'
      ? `[자동 오류 보고 — 구조 검토]\n실패: ${s4.message || '-'}\n원인: ${s4.failReason || '-'}\n결과표: ${s4.resultName || '-'} (첨부)\n도면: ${path.basename(job.src)}`
      : `[자동 오류 보고${job.kind === 's4' ? ' — 구조 검토 모델 읽기' : ''}]\n실패: ${job.message}\n원인: ${job.failReason || '-'}\n${job.kind === 's4' ? '모델' : '도면'}: ${path.basename(job.src)}`;
  const stamp = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().replace(/[-:T]/g, '').slice(0, 13).replace(/(\d{8})(\d{4})/, '$1_$2');
  const zip = buildZip({ root, engine, text, scope: 'error', job, log, out: path.join(root, 'tmp', `오류보고_${stamp}.zip`) });
  const size = fs.statSync(zip).size;
  const meta = { kind: 'error', version: appVersion, app: engine.versions().app, scope: 'error', stage: which === 'stage4' ? 4 : 0, job: path.basename(job.src), pc: os.hostname(), text: text.slice(0, 2000) };
  try {
    const r = await upload({ srv, file: zip, meta, onProgress: () => {} });
    fs.rmSync(zip, { force: true });
    log('오류 보고 전송 완료', r.id, size);
    return { ok: true, id: r.id, message: `오류 보고 자동 전송됨 (${(size / 1e6).toFixed(1)} MB)` };
  } catch (e) {
    fs.rmSync(zip, { force: true });
    log('오류 보고 전송 실패', e);
    return { ok: false, message: `오류 보고 전송 실패(${e.message}) — 다음 실행 때 다시 시도` };
  }
}

/**
 * [건너뛰기] = 결과에 문제가 없다고 표시한 작업을 표본으로 서버에 보냄(원본·결과 첨부). 피드백·오류 보고와 별개(kind 'sample').
 * 피드백이 들어온 파일·오류가 난 파일과 견주는 기준 자료로 쓴다. 서버가 없거나 실패하면 false(다음 실행 때 재시도).
 */
async function sendSample({ root, engine, bundledApp, appVersion, job, log }) {
  const srv = serverInfo(engine, bundledApp);
  if (!srv) return { ok: false, message: '서버 주소 없음' };
  const s4 = job.stage4 || {};
  const text =
    job.kind === 's4'
      ? `[문제 없음 표본 — 구조 검토]\n사용자가 [건너뛰기] 로 결과에 문제가 없다고 표시한 작업\n모델: ${path.basename(job.src)}\n결과: ${s4.message || job.message}`
      : `[문제 없음 표본 — 골조 모델링]\n사용자가 [건너뛰기] 로 결과에 문제가 없다고 표시한 작업\n도면: ${path.basename(job.src)}\n결과: ${job.result ? path.basename(job.result) : '-'} / ${job.message}`;
  const stamp = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().replace(/[-:T]/g, '').slice(0, 13).replace(/(\d{8})(\d{4})/, '$1_$2');
  const zip = buildZip({ root, engine, text, scope: 'sample', job, log, out: path.join(root, 'tmp', `문제없음표본_${stamp}.zip`) });
  const size = fs.statSync(zip).size;
  const meta = { kind: 'sample', version: appVersion, app: engine.versions().app, scope: 'sample', stage: job.kind === 's4' ? 4 : 0, job: path.basename(job.src), pc: os.hostname(), text: text.slice(0, 2000) };
  try {
    const r = await upload({ srv, file: zip, meta, onProgress: () => {} });
    fs.rmSync(zip, { force: true });
    log('문제 없음 표본 전송 완료', r.id, size);
    return { ok: true, id: r.id };
  } catch (e) {
    fs.rmSync(zip, { force: true });
    log('문제 없음 표본 전송 실패', e);
    return { ok: false, message: e.message };
  }
}

module.exports = { send, sendError, sendSample };
