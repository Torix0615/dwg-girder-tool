'use strict';
/**
 * 작업별 피드백: 내용 + 구분(이 도면만/모든 도면/모름) + 원본·결과 DXF·report·config·로그를 zip 으로 묶어(app/feedback.py)
 * 서버(app/feedback_server.txt: 주소 1줄, 키 없음 — 업로드는 공개 엔드포인트)로 전송(진행률). 서버가 없거나 실패하면 바탕화면 zip 으로 폴백.
 */
const fs = require('fs');
const path = require('path');
const os = require('os');
const { spawnSync } = require('child_process');
const { Readable, Transform } = require('stream');
const { readText } = require('./engine.cjs');

const SCOPE_LABEL = { file: '이 도면에만 해당', all: '모든 도면에 공통', unknown: '모름', error: '자동 오류 보고' };

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

function buildZip({ root, engine, text, scope, job, log, out }) {
  const tmp = path.join(root, 'tmp');
  fs.mkdirSync(tmp, { recursive: true });
  const head = [`구분: ${SCOPE_LABEL[scope] || scope || '-'}`, `대상 도면: ${job.src}`, `결과: ${job.result ? path.basename(job.result) : '(실패)'} / ${job.message}`];
  const attach = [job.src, job.result, job.mgt, job.report].filter((p) => p && fs.existsSync(p));
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
async function send({ root, engine, bundledApp, appVersion, text, scope, job, log, onProgress = () => {} }) {
  if (!job) return { ok: false, sent: false, message: '작업을 찾을 수 없습니다' };
  if (job.feedback && job.feedback.sent) return { ok: false, sent: true, message: '이미 전송한 작업입니다' };
  if (!String(text || '').trim()) return { ok: false, sent: false, message: '내용이 비어 있습니다' };
  const stamp = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().replace(/[-:T]/g, '').slice(0, 13).replace(/(\d{8})(\d{4})/, '$1_$2');
  const name = `골조거더보_피드백_${stamp}.zip`;
  const srv = serverInfo(engine, bundledApp);
  onProgress({ progress: 0, message: '파일 묶는 중…' });
  const zip = buildZip({ root, engine, text, scope, job, log, out: path.join(root, 'tmp', name) });
  const size = fs.statSync(zip).size;
  const at = new Date().toISOString();
  const base = { text: String(text).slice(0, 2000), scope, at };
  if (srv) {
    const meta = { version: appVersion, app: engine.versions().app, scope, job: path.basename(job.src), pc: os.hostname(), text: String(text).slice(0, 2000) };
    try {
      onProgress({ progress: 0, message: `전송 중 (${(size / 1e6).toFixed(1)} MB)` });
      const r = await upload({ srv, file: zip, meta, onProgress: (p) => onProgress({ progress: p, message: `전송 중 ${((p * size) / 1e6).toFixed(1)}/${(size / 1e6).toFixed(1)} MB` }) });
      fs.rmSync(zip, { force: true });
      log('피드백 전송 완료', r.id, size);
      engine.setFeedback(job.id, { ...base, sent: true, id: r.id });
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
  engine.setFeedback(job.id, { ...base, sent: true, file: out });
  return { ok: true, sent: true, file: out, message: `서버 전송이 안 되어 바탕화면에 저장했습니다: ${name} — 카카오톡·메일로 보내 주세요` };
}

/** 프로그램 오류 자동 보고(피드백과 별개): 보고서·로그·원본 도면을 서버로. 서버가 없거나 실패하면 false(다음 실행 때 재시도) */
async function sendError({ root, engine, bundledApp, appVersion, job, log }) {
  const srv = serverInfo(engine, bundledApp);
  if (!srv) return { ok: false, message: '서버 주소 없음' };
  const text = `[자동 오류 보고]\n실패: ${job.message}\n원인: ${job.failReason || '-'}\n도면: ${path.basename(job.src)}`;
  const stamp = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().replace(/[-:T]/g, '').slice(0, 13).replace(/(\d{8})(\d{4})/, '$1_$2');
  const zip = buildZip({ root, engine, text, scope: 'error', job, log, out: path.join(root, 'tmp', `오류보고_${stamp}.zip`) });
  const size = fs.statSync(zip).size;
  const meta = { kind: 'error', version: appVersion, app: engine.versions().app, scope: 'error', job: path.basename(job.src), pc: os.hostname(), text: text.slice(0, 2000) };
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

module.exports = { send, sendError };
