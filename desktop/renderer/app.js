'use strict';
const $ = (s) => document.querySelector(s);
const api = window.girder;

function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}
function fmtSec(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  return s >= 60 ? `${Math.floor(s / 60)}분 ${s % 60}초` : `${s}초`;
}
function fmtDate(iso) {
  const d = new Date(iso);
  return isNaN(d) ? '' : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

// ---- 창 버튼
$('#btnHide').addEventListener('click', () => api.hide());
const btnPin = $('#btnPin');
api.getPinned().then((on) => btnPin.classList.toggle('on', on));
btnPin.addEventListener('click', async () => {
  const on = await api.setPinned(!btnPin.classList.contains('on'));
  btnPin.classList.toggle('on', on);
});
let infoOpen = false;
async function showInfo(on) {
  infoOpen = on;
  $('#info').classList.toggle('hidden', !on);
  render();
  if (on) {
    const v = await api.versions();
    $('#verInfo').textContent = `프로그램 v${v.shell} · 스크립트 v${v.app} · 런타임 ${v.runtime} · 데이터 폴더 ${v.root}`;
  }
}
$('#btnInfo').addEventListener('click', () => showInfo(!infoOpen));
$('#btnInfoClose').addEventListener('click', () => showInfo(false));
$('#btnData').addEventListener('click', () => api.openDataFolder());
$('#btnUpdate').addEventListener('click', () => api.updateCheck());

// ---- 작업 시작 / 드롭(1개)
$('#btnStartEmpty').addEventListener('click', () => api.startJob());
$('#btnStart').addEventListener('click', () => api.startJob());
['dragenter', 'dragover', 'dragleave'].forEach((ev) => document.addEventListener(ev, (e) => e.preventDefault()));
document.addEventListener('drop', async (e) => {
  e.preventDefault();
  const paths = [...(e.dataTransfer?.files || [])].map((f) => api.pathOf(f)).filter(Boolean);
  if (paths.length) {
    const id = await api.run(paths.slice(0, 1));
    if (id) selected = id;
  }
});

// ---- 상태
let state = { jobs: [], running: false };
let selected = null;
const drafts = {}; // jobId → {text, scope}
const progress = {}; // jobId → {progress, message}
const sending = {}; // jobId → true

api.on('engine-state', (st) => {
  const prevIds = new Set(state.jobs.map((j) => j.id));
  state = st;
  const fresh = st.jobs.find((j) => !prevIds.has(j.id));
  if (fresh) selected = fresh.id;
  render();
});
api.engineState().then((st) => {
  state = st;
  if (!selected && st.jobs.length) selected = st.jobs[st.jobs.length - 1].id;
  render();
});
setInterval(() => {
  if (state.running) render();
}, 1000);
api.on('install-progress', (msg) => {
  $('#prepBar').textContent = msg || '';
  $('#prepBar').classList.toggle('hidden', !msg);
});
api.on('feedback-progress', (p) => {
  progress[p.jobId] = p;
  render();
});

function render() {
  const has = state.jobs.length > 0;
  $('#empty').classList.toggle('hidden', has || infoOpen);
  $('#work').classList.toggle('hidden', !has || infoOpen);
  if (!has) return;
  if (!state.jobs.some((j) => j.id === selected)) selected = state.jobs[state.jobs.length - 1].id;
  renderList();
  renderDetail(state.jobs.find((j) => j.id === selected));
}

function renderList() {
  const ul = $('#jobList');
  ul.innerHTML = '';
  for (const j of [...state.jobs].reverse()) {
    const li = document.createElement('li');
    li.className = 'jobitem ' + j.state + (j.id === selected ? ' sel' : '');
    const st = j.state === 'queued' ? '대기' : j.state === 'running' ? '진행 중' : j.state === 'done' ? (j.feedback && j.feedback.sent ? '완료 · 피드백 전송됨' : '완료') : j.state === 'failed' ? '실패' : '취소';
    li.innerHTML = `<div class="ji-name" title="${esc(j.src)}">${esc(j.name)}</div><div class="ji-state">${esc(st)}</div>`;
    if (j.state !== 'running') {
      const x = document.createElement('button');
      x.className = 'ji-del';
      x.title = '목록에서 지우기';
      x.textContent = '✕';
      x.addEventListener('click', (e) => {
        e.stopPropagation();
        api.removeJob(j.id);
      });
      li.appendChild(x);
    }
    li.addEventListener('click', () => {
      selected = j.id;
      render();
    });
    ul.appendChild(li);
  }
}

function renderDetail(j) {
  const el = $('#detail');
  if (!j) {
    el.innerHTML = '';
    return;
  }
  // 입력 중인 피드백 보존
  const ta = el.querySelector('textarea');
  if (ta && Number(el.dataset.job) === j.id) drafts[j.id] = { text: ta.value, scope: el.querySelector('input[name=scope]:checked')?.value || 'unknown' };
  el.dataset.job = j.id;
  const d = j.feedback && j.feedback.sent ? { text: j.feedback.text, scope: j.feedback.scope || 'unknown' } : drafts[j.id] || { text: '', scope: 'unknown' };
  const pct = j.state === 'done' ? 100 : j.state === 'running' ? Math.min(95, Math.round((j.stepIdx / (j.total || 5)) * 100)) : 0;
  const status =
    j.state === 'queued' ? '대기 중' : j.state === 'running' ? `${j.step} · ${fmtSec(Date.now() - j.started)}` : j.state === 'done' ? `${j.message} · ${fmtDate(new Date(j.ended).toISOString())}` : j.message;
  const sent = j.feedback && j.feedback.sent;
  const prog = progress[j.id];
  el.innerHTML = `
    <h2 class="d-name" title="${esc(j.src)}">${esc(j.name)}</h2>
    <div class="d-status ${j.state}">${esc(status)}</div>
    ${j.state === 'running' || j.state === 'queued' ? `<div class="bar"><i style="width:${pct}%"></i></div><pre class="d-tail">${esc((j.tail || []).slice(-5).join('\n'))}</pre><div class="row"><button class="btn small danger" data-act="cancel">작업 취소</button></div>` : ''}
    ${j.state === 'failed' ? `<pre class="d-tail">${esc((j.tail || []).slice(-8).join('\n'))}</pre>${j.report ? `<div class="row"><button class="btn small ghost" data-act="report">보고서 열기</button></div>` : ''}` : ''}
    ${j.state === 'done' ? `<div class="row gap"><button class="btn" data-act="download">⬇ 결과 DXF</button>${j.mgt ? `<button class="btn" data-act="download-mgt">⬇ MIDAS GEN (MGT)</button>` : ''}<span class="hint">${esc(j.result ? j.result.split(/[\\/]/).pop() : '')}</span></div>` : ''}
    ${
      j.state === 'done' || j.state === 'failed'
        ? `<section class="fb">
        <h3>피드백</h3>
        <p class="hint">결과에서 잘못된 점·빠진 것·바라는 점을 적어 주세요. 원본 도면과 결과 DXF가 함께 전송되어 생성 규칙 개선에 쓰입니다.</p>
        <div class="radios">
          <label><input type="radio" name="scope" value="all" ${d.scope === 'all' ? 'checked' : ''} ${sent ? 'disabled' : ''}/> 모든 도면에 공통</label>
          <label><input type="radio" name="scope" value="file" ${d.scope === 'file' ? 'checked' : ''} ${sent ? 'disabled' : ''}/> 이 도면에만 해당</label>
          <label><input type="radio" name="scope" value="unknown" ${d.scope === 'unknown' ? 'checked' : ''} ${sent ? 'disabled' : ''}/> 모름</label>
        </div>
        <textarea rows="6" ${sent ? 'disabled' : ''} placeholder="예) 램프 구간의 곡선 보가 생성되지 않음. 기둥 없는 구역은 벽을 따라 거더가 있어야 함.">${esc(sent ? j.feedback.text : d.text)}</textarea>
        <div class="row gap">
          <button class="btn" data-act="send" ${sent || sending[j.id] ? 'disabled' : ''}>${sent ? '전송 완료' : sending[j.id] ? '전송 중…' : '전송하기'}</button>
          <span class="msg ${sent ? 'ok' : ''}">${esc(sent ? `${fmtDate(j.feedback.at)} 전송됨${j.feedback.file ? ' (바탕화면 파일)' : ''}` : prog ? prog.message : '')}</span>
        </div>
        ${prog && sending[j.id] ? `<div class="bar"><i style="width:${Math.round((prog.progress || 0) * 100)}%"></i></div>` : ''}
      </section>`
        : ''
    }
  `;
  el.querySelector('[data-act=cancel]')?.addEventListener('click', () => api.cancel());
  el.querySelector('[data-act=report]')?.addEventListener('click', () => api.openPath(j.report));
  el.querySelector('[data-act=download-mgt]')?.addEventListener('click', async (e) => {
    e.target.disabled = true;
    const r = await api.download(j.id, 'mgt');
    e.target.disabled = false;
    if (r.message) el.querySelector('.d-status').textContent = r.message;
  });
  el.querySelector('[data-act=download]')?.addEventListener('click', async (e) => {
    e.target.disabled = true;
    const r = await api.download(j.id, 'dxf');
    e.target.disabled = false;
    if (r.message) {
      const s = el.querySelector('.d-status');
      s.textContent = r.message;
    }
  });
  el.querySelector('[data-act=send]')?.addEventListener('click', async () => {
    const text = el.querySelector('textarea').value;
    const scope = el.querySelector('input[name=scope]:checked')?.value || 'unknown';
    if (!text.trim()) {
      el.querySelector('.fb .msg').textContent = '내용을 적어 주세요';
      return;
    }
    drafts[j.id] = { text, scope };
    sending[j.id] = true;
    render();
    const r = await api.sendFeedback({ text, scope, jobId: j.id });
    delete sending[j.id];
    delete progress[j.id];
    if (r.sent) delete drafts[j.id];
    render();
    const m = $('#detail').querySelector('.fb .msg');
    if (m) {
      m.textContent = r.message;
      m.className = 'msg ' + (r.ok ? 'ok' : 'err');
    }
  });
}

// ---- 업데이트 띠
const ub = $('#updateBar');
let notesOpen = false;
$('#ubToggle').addEventListener('click', () => {
  notesOpen = !notesOpen;
  $('#ubNotes').classList.toggle('hidden', !notesOpen);
  $('#ubToggle').textContent = notesOpen ? '▴' : '▾';
});
$('#ubInstall').addEventListener('click', () => api.updateInstall());
function renderUpdate(s) {
  if (!s) return;
  const show = ['downloading', 'ready', 'updated', 'installing', 'error'].includes(s.state);
  ub.classList.toggle('hidden', !show);
  ub.classList.toggle('good', s.state === 'updated');
  ub.classList.toggle('bad', s.state === 'error');
  let msg = s.message || '';
  if (s.state === 'downloading' && s.progress) msg += ` (${Math.round(s.progress * 100)}%)`;
  $('#ubMsg').textContent = msg;
  $('#ubInstall').classList.toggle('hidden', !(s.state === 'ready' && /설치 준비됨/.test(msg)));
  const notes = s.notes || [];
  $('#ubToggle').classList.toggle('hidden', !notes.length);
  $('#ubNotes').innerHTML = notes
    .map((n) => `<h4>v${esc(n.version)} <span class="chip">${esc(n.date || '')}</span></h4><ul>${(n.items || []).map((i) => `<li>${esc(i)}</li>`).join('')}</ul>`)
    .join('');
  if (['downloading', 'updated', 'ready'].includes(s.state) && notes.length && !notesOpen) $('#ubToggle').click();
  $('#updMsg').textContent = s.message || '';
  $('#updMsg').className = 'msg ' + (s.state === 'error' ? 'err' : s.state === 'uptodate' || s.state === 'updated' ? 'ok' : '');
  if (s.current) $('#verChip').textContent = `v${s.current.app}`;
}
api.on('update-status', renderUpdate);
api.updateStatus().then(renderUpdate);
