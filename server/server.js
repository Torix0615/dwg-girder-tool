'use strict';
/**
 * 피드백 수신 서버(Railway, 볼륨 /data). 의존성 없음.
 *  POST   /api/feedback            키 없음(IP당 시간당 10건·용량 제한) · 헤더 x-meta(base64 JSON) · 본문 = zip → {id}
 *  GET    /api/feedback[?all=1]    목록(기본: 아직 가져가지 않은 것)
 *  GET    /api/feedback/<id>.zip   내려받기
 *  POST   /api/feedback/<id>/done  가져감 표시
 *  DELETE /api/feedback/<id>       삭제
 *  GET    /health
 * 환경변수: PORT, FEEDBACK_KEY(필수), DATA_DIR(/data), MAX_MB(600)
 */
const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const PORT = Number(process.env.PORT || 3000);
const KEY = process.env.FEEDBACK_KEY || '';
const DIR = path.join(process.env.DATA_DIR || '/data', 'feedback');
const MAX = Number(process.env.MAX_MB || 600) * 1e6;
const RATE = new Map(); // ip → [timestamps]

fs.mkdirSync(DIR, { recursive: true });
if (!KEY) console.error('FEEDBACK_KEY 가 없습니다 — 조회·다운로드·삭제가 거부됩니다(업로드는 가능)');

function json(res, code, obj) {
  const b = JSON.stringify(obj);
  res.writeHead(code, { 'content-type': 'application/json; charset=utf-8', 'content-length': Buffer.byteLength(b) });
  res.end(b);
}
function authed(req, url) {
  const k = req.headers['x-key'] || url.searchParams.get('key') || '';
  return KEY && k.length === KEY.length && crypto.timingSafeEqual(Buffer.from(k), Buffer.from(KEY));
}
function ratelimited(ip) {
  const now = Date.now();
  const arr = (RATE.get(ip) || []).filter((t) => now - t < 3600e3);
  arr.push(now);
  RATE.set(ip, arr);
  return arr.length > 10;
}
function readMeta(p) {
  try {
    return JSON.parse(fs.readFileSync(p, 'utf8'));
  } catch {
    return null;
  }
}
function list(all) {
  return fs
    .readdirSync(DIR)
    .filter((f) => f.endsWith('.json'))
    .map((f) => readMeta(path.join(DIR, f)))
    .filter((m) => m && (all || !m.done))
    .sort((a, b) => (a.id < b.id ? -1 : 1));
}
function safeId(s) {
  return /^[0-9]{8}_[0-9]{6}_[0-9a-f]{6}$/.test(s) ? s : null;
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://x');
  const ip = (req.headers['x-forwarded-for'] || req.socket.remoteAddress || '').split(',')[0].trim();
  if (url.pathname === '/health') return json(res, 200, { ok: true, count: list(false).length, max_mb: MAX / 1e6 });
  if (!url.pathname.startsWith('/api/feedback')) return json(res, 404, { error: 'not found' });
  const isUpload = req.method === 'POST' && url.pathname === '/api/feedback';
  if (!isUpload && !authed(req, url)) return json(res, 401, { error: 'unauthorized' }); // 업로드만 키 없이(앱 배포물에 비밀값을 넣지 않음)

  if (isUpload) {
    if (ratelimited(ip)) return json(res, 429, { error: 'too many uploads' });
    const len = Number(req.headers['content-length'] || 0);
    if (len > MAX) return json(res, 413, { error: `too large (max ${MAX / 1e6} MB)` });
    let meta = {};
    try {
      meta = JSON.parse(Buffer.from(String(req.headers['x-meta'] || ''), 'base64').toString('utf8') || '{}');
    } catch {
      /* 메타 없음 */
    }
    const d = new Date();
    const stamp = new Date(d.getTime() + 9 * 3600e3).toISOString().replace(/[-:T]/g, '').slice(0, 14).replace(/^(\d{8})(\d{6})$/, '$1_$2'); // KST
    const id = `${stamp}_${crypto.randomBytes(3).toString('hex')}`;
    const dest = path.join(DIR, id + '.zip');
    const part = dest + '.part';
    let got = 0;
    const ws = fs.createWriteStream(part);
    req.on('data', (c) => {
      got += c.length;
      if (got > MAX) {
        req.destroy();
        ws.destroy();
        fs.rm(part, { force: true }, () => {});
      }
    });
    req.pipe(ws);
    ws.on('finish', () => {
      let magic = Buffer.alloc(2);
      try {
        const fd = fs.openSync(part, 'r');
        fs.readSync(fd, magic, 0, 2, 0);
        fs.closeSync(fd);
      } catch {
        /* */
      }
      if (got < 100 || magic.toString('latin1') !== 'PK') {
        fs.rm(part, { force: true }, () => {});
        return json(res, 400, { error: 'not a zip' });
      }
      fs.renameSync(part, dest);
      const info = { id, received_at: d.toISOString(), size: got, ip, done: false, ...meta };
      fs.writeFileSync(path.join(DIR, id + '.json'), JSON.stringify(info, null, 1));
      console.log(`feedback ${id} ${(got / 1e6).toFixed(1)}MB from ${ip} scope=${meta.scope || '-'} job=${meta.job || '-'}`);
      json(res, 200, { id, size: got });
    });
    ws.on('error', (e) => {
      fs.rm(part, { force: true }, () => {});
      json(res, 500, { error: e.message });
    });
    req.on('error', () => fs.rm(part, { force: true }, () => {}));
    return;
  }
  if (req.method === 'GET' && url.pathname === '/api/feedback') return json(res, 200, { items: list(url.searchParams.get('all') === '1') });

  const m = /^\/api\/feedback\/([^/]+?)(\.zip)?(\/done)?$/.exec(url.pathname);
  const id = m && safeId(m[1]);
  if (!id) return json(res, 404, { error: 'not found' });
  const zp = path.join(DIR, id + '.zip');
  const jp = path.join(DIR, id + '.json');
  if (req.method === 'GET' && m[2]) {
    if (!fs.existsSync(zp)) return json(res, 404, { error: 'no file' });
    res.writeHead(200, { 'content-type': 'application/zip', 'content-length': fs.statSync(zp).size, 'content-disposition': `attachment; filename="${id}.zip"` });
    return fs.createReadStream(zp).pipe(res);
  }
  if (req.method === 'POST' && m[3]) {
    const info = readMeta(jp);
    if (!info) return json(res, 404, { error: 'not found' });
    info.done = true;
    info.done_at = new Date().toISOString();
    fs.writeFileSync(jp, JSON.stringify(info, null, 1));
    return json(res, 200, { ok: true });
  }
  if (req.method === 'DELETE') {
    fs.rmSync(zp, { force: true });
    fs.rmSync(jp, { force: true });
    return json(res, 200, { ok: true });
  }
  return json(res, 405, { error: 'method' });
});
server.requestTimeout = 30 * 60e3;
server.headersTimeout = 60e3;
server.listen(PORT, () => console.log(`dwg-feedback-server :${PORT} dir=${DIR} max=${MAX / 1e6}MB`));
