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
let generalOpen = false;
async function showInfo(on) {
  infoOpen = on;
  if (on) generalOpen = false;
  $('#info').classList.toggle('hidden', !on);
  $('#general').classList.toggle('hidden', !generalOpen);
  render();
  if (on) {
    $('#setMsg').textContent = '';
    fillSettings(await api.getSettings());
    const v = await api.versions();
    $('#verInfo').textContent = `프로그램 v${v.shell} · 스크립트 v${v.app} · 런타임 ${v.runtime} · 데이터 폴더 ${v.root}`;
  }
}
$('#btnInfo').addEventListener('click', () => showInfo(!infoOpen));
$('#btnInfoClose').addEventListener('click', () => showInfo(false));
$('#btnData').addEventListener('click', () => api.openDataFolder());
$('#btnUpdate').addEventListener('click', () => api.updateCheck());

// ---- 설정(실행 범위 / 보 생성 / 보 간격 기준): userData/config.json 에 저장, 다음 작업부터 적용
let settingDefaults = {};
function fillSettings({ values, defaults }) {
  settingDefaults = defaults || {};
  const stage = String(values['실행_단계'] || 3);
  for (const r of document.querySelectorAll('input[name=stage]')) r.checked = r.value === stage;
  $('#optBeams').checked = Boolean(values['보_생성']);
  for (const inp of numInputs()) {
    inp.value = values[inp.dataset.key] ?? '';
    inp.classList.remove('changed');
    inp.closest('label').querySelector('.dflt').textContent = `기본 ${settingDefaults[inp.dataset.key] ?? '-'}`;
  }
  for (const inp of textInputs()) {
    inp.value = values[inp.dataset.key] ?? '';
    inp.classList.remove('changed', 'bad');
    const d = inp.closest('label').querySelector('.dflt');
    const keys = [...inp.closest('label').querySelectorAll('[data-key]')].map((x) => x.dataset.key); // 상부/하부 같은 쌍은 둘 다 표시
    if (d) d.textContent = inp.tagName === 'SELECT' ? '' : `기본 ${keys.map((k) => settingDefaults[k] ?? '-').join(' / ')}`;
  }
  settingsVisibility();
}
const numInputs = () => [...document.querySelectorAll('#info .nums input[data-key]')];
const textInputs = () => [...document.querySelectorAll('#info .texts input[data-key], #info .texts select[data-key]')];
const isShown = (el) => !el.closest('.hidden');
const TEXT_RE = { bars: /^\d{1,2}-D\d{2}$/, stir: /^D\d{2}@\d{2,3}$/, list: /^D\d{2}(\s*,\s*D\d{2})*$/, combo: /^[\d.\s+\-*DLdl;,]+$/ };
const TEXT_HINT = { bars: '개수-직경 (예 4-D22)', stir: '직경@간격 (예 D10@200)', list: 'D13,D16,… 쉼표로', combo: '예 1.4D; 1.2D+1.6L' };
function numOk(i) {
  const n = Number(i.value);
  return i.value !== '' && Number.isFinite(n) && n >= Number(i.min || 0) && (i.max === '' || n <= Number(i.max));
}
function textOk(i) {
  if (i.tagName === 'SELECT') return true;
  const re = TEXT_RE[i.dataset.re];
  const v = i.value.trim();
  return v !== '' && (!re || re.test(v));
}
function settingsVisibility() {
  const stage = Number(document.querySelector('input[name=stage]:checked')?.value || 3);
  $('#setBeamGrp').classList.toggle('hidden', stage < 2); // 1단계까지만이면 보 설정은 의미 없음
  $('#beamNums').classList.toggle('hidden', !$('#optBeams').checked); // 보를 끄면 간격 옵션 숨김
  $('#setMgtGrp').classList.toggle('hidden', stage < 3); // MGT 를 만들지 않으면 층고 설정 숨김
  $('#setChkGrp').classList.toggle('hidden', stage < 3); // 4단계 검토는 MGT(3단계) 결과가 있어야 함
}
function readSettings() {
  const vals = { 실행_단계: Number(document.querySelector('input[name=stage]:checked')?.value || 3), 보_생성: $('#optBeams').checked };
  for (const inp of numInputs()) if (numOk(inp)) vals[inp.dataset.key] = Number(inp.value);
  for (const inp of textInputs()) if (textOk(inp)) vals[inp.dataset.key] = inp.value.trim();
  return vals;
}
$('#setStage').addEventListener('change', settingsVisibility);
$('#optBeams').addEventListener('change', settingsVisibility);
for (const inp of numInputs()) {
  inp.addEventListener('input', () => {
    inp.value = inp.dataset.dec ? inp.value.replace(/[^\d.]/g, '').replace(/(\..*)\./g, '$1') : inp.value.replace(/[^\d]/g, ''); // 숫자만(소수 허용 칸은 점 1개)
    inp.classList.toggle('changed', Number(inp.value) !== Number(settingDefaults[inp.dataset.key]));
  });
}
for (const inp of textInputs()) {
  inp.addEventListener('input', () => {
    inp.classList.toggle('changed', String(inp.value).trim() !== String(settingDefaults[inp.dataset.key] ?? ''));
    inp.classList.toggle('bad', !textOk(inp));
  });
}
$('#setSave').addEventListener('click', async () => {
  const m = $('#setMsg');
  const badN = numInputs().filter((i) => isShown(i) && !numOk(i)); // 보이는 칸만 검사
  if (badN.length) {
    const i = badN[0];
    m.textContent = `${i.closest('label').querySelector('span').textContent}: ${i.min}${i.max ? `~${i.max}` : ' 이상'} 숫자를 입력해 주세요`;
    m.className = 'msg err';
    i.focus();
    return;
  }
  const badT = textInputs().filter((i) => isShown(i) && !textOk(i));
  if (badT.length) {
    const i = badT[0];
    m.textContent = `${i.closest('label').querySelector('span').textContent}: ${TEXT_HINT[i.dataset.re] || '값을 입력해 주세요'}`;
    m.className = 'msg err';
    i.focus();
    return;
  }
  const r = await api.setSettings(readSettings());
  fillSettings(r);
  m.textContent = r.rejected && r.rejected.length ? `저장됨 — 일부 값은 범위 밖이라 유지됨 (${r.rejected.join(', ')})` : '저장됨 — 다음 작업(4단계는 다음 검토)부터 적용';
  m.className = 'msg ok';
});
$('#setReset').addEventListener('click', async () => {
  fillSettings(await api.setSettings({ ...settingDefaults }));
  $('#setMsg').textContent = '기본값으로 되돌림';
  $('#setMsg').className = 'msg ok';
});
function optsLabel(o) {
  if (!o) return '';
  const parts = [];
  if (o.stage && o.stage < 3) parts.push(`${o.stage}단계까지`);
  if (o.beams === false && o.stage !== 1) parts.push('보 없음');
  return parts.join(' · ');
}

// ---- 피드백 패널(도면 작업 없이): 종류 선택 + 내용 + 자동 분류 힌트 + 보낸 내역
const KIND_LABEL = { ui: '프로그램 화면·기능', rule: '생성 규칙·결과', unknown: '모름' };
let gfSending = false;
function autoHint(text, el, chosen) {
  const c = window.classifyFeedback(text);
  let msg = '';
  if (text.trim().length >= 6) {
    if (c.category === 'ui') msg = `자동 분류: 프로그램 화면·기능 요청으로 보입니다 (${c.ui.slice(0, 4).join('·')}) → 프로그램 업데이트 대상`;
    else if (c.category === 'rule') msg = `자동 분류: 생성 규칙·결과 의견으로 보입니다 (${c.rule.slice(0, 4).join('·')})`;
    if (chosen && chosen !== 'unknown' && c.category !== 'unknown' && chosen !== c.category) msg += ` — 선택한 종류(${KIND_LABEL[chosen]})와 다릅니다. 보낸 뒤 개발자가 내용으로 최종 분류합니다.`;
  }
  el.textContent = msg;
  el.classList.toggle('auto-ui', c.category === 'ui');
  return c.category;
}
async function showGeneral(on) {
  generalOpen = on;
  if (on) infoOpen = false;
  $('#general').classList.toggle('hidden', !on);
  $('#info').classList.toggle('hidden', !infoOpen);
  render();
  if (on) {
    renderHistory(await api.feedbackHistory());
    $('#gfText').focus();
  }
}
function renderHistory(items) {
  const h = $('#gfHistory');
  if (!items || !items.length) {
    h.innerHTML = '';
    return;
  }
  h.innerHTML =
    `<h4>보낸 피드백 (최근 ${items.length}건)</h4>` +
    items
      .slice()
      .reverse()
      .map((it) => `<div class="gf-item"><div class="gf-meta"><span class="tag ${esc(it.category)}">${esc(KIND_LABEL[it.category] || it.category)}</span>${esc(fmtDate(it.at))}${it.id ? ' · 서버 접수' : it.file ? ' · 바탕화면 파일' : ''}</div>${esc(it.text)}</div>`)
      .join('');
}
$('#btnFeedback').addEventListener('click', () => showGeneral(true));
$('#btnFeedbackEmpty').addEventListener('click', () => showGeneral(true));
$('#gfClose').addEventListener('click', () => showGeneral(false));
$('#gfText').addEventListener('input', () => autoHint($('#gfText').value, $('#gfAuto'), $('input[name=gkind]:checked')?.value));
$('#gfKind').addEventListener('change', () => autoHint($('#gfText').value, $('#gfAuto'), $('input[name=gkind]:checked')?.value));
$('#gfSend').addEventListener('click', async () => {
  const text = $('#gfText').value;
  const m = $('#gfMsg');
  if (!text.trim()) {
    m.textContent = '내용을 적어 주세요';
    m.className = 'msg err';
    return;
  }
  if (gfSending) return;
  gfSending = true;
  $('#gfSend').disabled = true;
  m.textContent = '전송 중…';
  m.className = 'msg';
  const category = $('input[name=gkind]:checked')?.value || 'unknown';
  const r = await api.sendFeedback({ text, scope: 'general', category, jobId: null });
  gfSending = false;
  $('#gfSend').disabled = false;
  m.textContent = r.message;
  m.className = 'msg ' + (r.ok ? 'ok' : 'err');
  if (r.sent) {
    $('#gfText').value = '';
    $('#gfAuto').textContent = '';
    renderHistory(await api.feedbackHistory());
  }
});
api.on('open-feedback', () => showGeneral(true));

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
  const panel = infoOpen || generalOpen;
  $('#empty').classList.toggle('hidden', has || panel);
  $('#work').classList.toggle('hidden', !has || panel);
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
    const st = j.state === 'queued' ? '대기' : j.state === 'running' ? '진행 중' : j.state === 'done' ? (j.feedback && j.feedback.sent ? '완료 · 피드백 전송됨' : '완료') : j.state === 'failed' ? (j.failKind === 'input' ? '실패 · 도면 문제' : j.errorReport && j.errorReport.sent ? '실패 · 오류 보고됨' : '실패') : '취소';
    const ol = optsLabel(j.opts);
    li.innerHTML = `<div class="ji-name" title="${esc(j.src)}">${esc(j.name)}</div><div class="ji-state">${esc(st)}${ol ? `<span class="ji-opts">${esc(ol)}</span>` : ''}</div>`;
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
    <div class="d-status ${j.state}">${esc(status)}${optsLabel(j.opts) ? `<span class="d-opts" title="이 작업에 적용된 설정">${esc(optsLabel(j.opts))}</span>` : ''}</div>
    ${j.state === 'running' || j.state === 'queued' ? `<div class="bar"><i style="width:${pct}%"></i></div><pre class="d-tail">${esc((j.tail || []).slice(-5).join('\n'))}</pre><div class="row"><button class="btn small danger" data-act="cancel">작업 취소</button></div>` : ''}
    ${
      j.state === 'failed'
        ? `<div class="fail ${j.failKind === 'input' ? 'input' : 'error'}">
            <b>${j.failKind === 'input' ? '도면 문제' : '프로그램 오류'}</b> ${esc(j.failReason || '')}
            <div class="hint">${j.failKind === 'input' ? '안내대로 파일을 갖춘 뒤 다시 작업 시작하면 됩니다.' : esc(j.errorReport ? j.errorReport.message : '오류 보고를 자동으로 보냅니다')}</div>
          </div><pre class="d-tail">${esc((j.tail || []).slice(-8).join('\n'))}</pre>`
        : ''
    }
    ${j.state === 'done' ? `<div class="row gap"><button class="btn" data-act="download">⬇ 결과 DXF</button>${j.mgt ? `<button class="btn" data-act="download-mgt">⬇ MIDAS GEN (MGT)</button>` : ''}<span class="hint">${esc(j.result ? j.result.split(/[\\/]/).pop() : '')}</span></div>` : ''}
    ${j.state === 'done' && j.mgt ? renderStage4(j) : ''}
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
        <p class="hint fb-auto"></p>
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
  // 4단계 구조 검토: 결과표 첨부 → 검토 / 엑셀·수정 MGT 다운로드 / 승인
  const s4msg = (t, cls = '') => {
    const m = el.querySelector('.s4 .s4-msg');
    if (m) {
      m.textContent = t;
      m.className = 's4-msg msg ' + cls;
    }
  };
  el.querySelector('[data-act=s4-pick]')?.addEventListener('click', async (e) => {
    e.target.disabled = true;
    const r = await api.stage4Pick(j.id);
    e.target.disabled = false;
    if (r.message) s4msg(r.message, r.ok ? '' : 'err');
  });
  el.querySelector('[data-act=s4-apply]')?.addEventListener('click', async (e) => {
    e.target.disabled = true;
    const r = await api.stage4Apply(j.id);
    e.target.disabled = false;
    if (r.message) s4msg(r.message, r.ok ? 'ok' : 'err');
  });
  for (const [act, kind] of [['s4-xlsx', 'xlsx'], ['s4-mgt2', 'mgt2']]) {
    el.querySelector(`[data-act=${act}]`)?.addEventListener('click', async (e) => {
      e.target.disabled = true;
      const r = await api.download(j.id, kind);
      e.target.disabled = false;
      if (r.message) s4msg(r.message, r.ok ? 'ok' : 'err');
    });
  }
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
  // 작업 카드 피드백에도 자동 분류 힌트: 프로그램 화면·기능 내용이면 알려 주고 그대로 전송(개발 PC 에서 프로그램 요청으로 표시됨)
  const fbTa = el.querySelector('.fb textarea');
  const fbAuto = el.querySelector('.fb-auto');
  if (fbTa && fbAuto) {
    const upd = () => autoHint(fbTa.value, fbAuto, null);
    upd();
    if (!sent) fbTa.addEventListener('input', upd);
  }
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
    const r = await api.sendFeedback({ text, scope, category: window.classifyFeedback(text).category, jobId: j.id });
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

// ---- 4단계 구조 검토 카드(3단계 MGT 가 있는 완료 작업): MIDAS 해석 결과표 첨부 → 검토 → 엑셀, 승인 → 수정 MGT
const KIND_KO = { col: '기둥', girder: '거더', beam: '보' };
function renderStage4(j) {
  const s = j.stage4;
  const canRun = !s || s.state !== 'running';
  const pickLabel = s && s.state === 'done' ? '📎 다른 결과표로 다시 검토' : '📎 MIDAS 해석 결과표(텍스트) 첨부 → 검토 실행';
  let body = '';
  if (!j.elements) {
    body = `<p class="hint">이 작업은 요소 대응표가 없어(1.5.0 이전 생성) 검토할 수 없습니다. 도면을 다시 작업한 뒤 이용해 주세요.</p>`;
  } else if (s && s.state === 'running') {
    const pct = Math.min(95, Math.round(((s.stepIdx || 0) / (s.total || 4)) * 100));
    body = `<div class="d-status running">${esc(s.step || '검토 중')} · ${fmtSec(Date.now() - s.started)}</div><div class="bar"><i style="width:${pct}%"></i></div><pre class="d-tail">${esc((s.tail || []).slice(-4).join('\n'))}</pre>`;
  } else if (s && s.state === 'failed') {
    body = `<div class="fail ${s.failKind === 'input' ? 'input' : 'error'}"><b>${s.failKind === 'input' ? '설정·입력 문제' : '검토 실패'}</b> ${esc(s.failReason || '')}
      <div class="hint">${s.failKind === 'input' ? '설정(⚙)을 고친 뒤 다시 검토해 주세요.' : esc(s.errorReport ? s.errorReport.message : '결과표를 포함한 오류 보고를 자동으로 보냅니다. 형식을 맞춘 업데이트가 나오면 자동 설치됩니다.')}</div></div>`;
  } else if (s && s.state === 'done' && s.summary) {
    const m = s.summary;
    const kinds = Object.entries(m.by_kind || {}).map(([k, v]) => `${KIND_KO[k] || k} OK ${v.ok}·NG ${v.ng}${v.dims ? `(치수 ${v.dims})` : ''}`).join(' / ');
    body = `<div class="chips"><span class="chip2">검토 ${m.total}</span><span class="chip2 ok">OK ${m.ok}</span><span class="chip2 ${m.ng ? 'ng' : ''}">NG ${m.ng}</span>${m.none ? `<span class="chip2 warn">결과 없음 ${m.none}</span>` : ''}${m.dims_changed ? `<span class="chip2 warn">치수 변경 추천 ${m.dims_changed}</span>` : ''}</div>
      <p class="hint">${esc(kinds)} · 결과표 ${esc(s.resultName || '')} · 하중 ${m.loads}종 ${m.rows}행${m.unknown ? ` · 대응표에 없는 요소 ${m.unknown}개 무시` : ''} · ${esc(fmtDate(new Date(s.ended).toISOString()))}</p>
      <div class="row gap"><button class="btn" data-act="s4-xlsx">⬇ 검토 결과 엑셀</button>
      ${m.ng && m.dims_changed ? (s.mgt2 ? `<button class="btn" data-act="s4-mgt2">⬇ 수정 MGT (승인됨)</button><button class="btn ghost small" data-act="s4-apply">다시 생성</button>` : `<button class="btn" data-act="s4-apply">✔ 승인 → 수정 MGT 생성</button>`) : ''}</div>
      <p class="hint">${m.ng === 0 ? '모든 부재 OK — MGT 수정이 필요 없습니다.' : m.dims_changed ? '승인하면 치수가 바뀐 부재만 새 단면(C2·G2·B2…)으로 바꾼 MGT 를 만듭니다. 철근은 MGT 에 쓰지 않으며 엑셀의 추천 철근을 참고하십시오.' : 'NG 부재는 철근 보강만으로 해결됩니다(엑셀 추천 철근 참조) — 단면 치수 변경이 없어 MGT 수정은 필요 없습니다.'}${s.applied ? ` 수정 MGT: 요소 ${s.applied.changed}개 단면 교체, 새 단면 ${(s.applied.new_sections || []).map((x) => `${x.name} ${x.H}×${x.B}`).join(', ')}` : ''}</p>`;
  } else {
    body = `<p class="hint">3단계 MGT 를 MIDAS GEN 에서 열어 <b>하중·하중조합을 정의하고 해석</b>한 뒤, 결과 테이블(Beam Force) 을 텍스트(.txt/.csv)로 저장해 첨부하면 기둥(축력·PM 상관도·장주)·거더·보(휨·전단)를 KDS 14 20 으로 검토하고 NG 부재는 철근 → 폭 → 춤 순으로 추천합니다. 검토 기준값은 ⚙ 설정.</p>`;
  }
  return `<section class="s4"><h3>4단계 구조 검토 <span class="chip">MIDAS 해석 결과 → KDS 14 20</span></h3>${body}
    ${j.elements && canRun ? `<div class="row gap"><button class="btn ${s && s.state === 'done' ? 'ghost small' : ''}" data-act="s4-pick">${pickLabel}</button><span class="s4-msg msg"></span></div>` : '<span class="s4-msg msg"></span>'}</section>`;
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
