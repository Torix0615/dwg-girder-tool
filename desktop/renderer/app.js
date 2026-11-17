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
/** 날짜·시간(YYYY-MM-DD HH:mm). ms 숫자와 ISO 문자열 모두 받음 */
function fmtDate(v) {
  if (!v) return '';
  const d = new Date(v);
  return isNaN(d) ? '' : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}
const num = (n) => Number(n || 0).toLocaleString('ko-KR');
const CHECK = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M3 8.5l3.2 3.2L13 4.8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';

/** 바뀐 부분만 다시 그림 — 입력 중인 피드백 글과 커서를 건드리지 않기 위함. 내용이 같으면 false */
const parts = {};
function setPart(sel, html) {
  if (parts[sel] === html) return false;
  parts[sel] = html;
  $(sel).innerHTML = html;
  return true;
}

// ---- 확인 팝업([취소] [확인]). 오른쪽 버튼 = true, 왼쪽 버튼 = false, 바깥을 누르거나 Esc = null(아무것도 하지 않음)
let modalDone = null;
function confirmBox(title, body, opt = {}) {
  if (modalDone) modalDone(null);
  return new Promise((resolve) => {
    $('#modalTitle').textContent = title;
    $('#modalBody').textContent = body || '';
    $('#modalOk').textContent = opt.ok || '확인';
    $('#modalCancel').textContent = opt.cancel || '취소';
    $('#modal').classList.remove('hidden');
    modalDone = (v) => {
      modalDone = null;
      $('#modal').classList.add('hidden');
      resolve(v);
    };
    (opt.focusOk ? $('#modalOk') : $('#modalCancel')).focus();
  });
}
$('#modalOk').addEventListener('click', () => modalDone && modalDone(true));
$('#modalCancel').addEventListener('click', () => modalDone && modalDone(false));
$('#modal').addEventListener('mousedown', (e) => {
  if (e.target === $('#modal') && modalDone) modalDone(null);
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && modalDone) modalDone(null);
});

// ---- 창 버튼
$('#btnHide').addEventListener('click', () => api.hide());
const btnPin = $('#btnPin');
api.getPinned().then((on) => btnPin.classList.toggle('on', on));
btnPin.addEventListener('click', async () => {
  const on = await api.setPinned(!btnPin.classList.contains('on'));
  btnPin.classList.toggle('on', on);
});

// ---- 화면: jobs(작업 목록 + 작업 결과) / cond([+ 골조 모델링] 으로 도면을 고른 뒤: 모델링 조건 입력) / review([+ 구조 검토]: 파일 두 개 넣기) / general([피드백]: 작업 없이 보내는 피드백) / log([피드백 로그]) / settings(⚙)
let view = 'jobs';
const rv = { table: null, msg: null }; // [+ 구조 검토] 화면: 먼저 넣은 결과표(모델이 오면 함께 검토 시작)·안내 글
let state = { jobs: [], running: false };
let selected = null;
const drafts = {}; // jobId → {text, kind} : 작업 결과 화면에서 쓰던 피드백(작업마다 저장 — 다른 곳에 다녀와도 남음)
const progress = {}; // jobId → {progress, message}
const sending = {}; // jobId → true
const fbMsg = {}; // jobId → {text, cls}
const gen = { text: '', kind: 'rule', sending: false, msg: null }; // 작업 없이 보내는 피드백(저장하지 않음 — 다른 곳으로 가면 확인 후 삭제)
let logItems = [];
let logSel = -1;

/** 지금 화면을 떠나도 되는지: 작업 없이 쓰던 피드백 = 삭제 확인 / 저장하지 않은 설정 = 저장할지 확인 / 조건 입력 = 그냥 닫음. 머무르면 false */
async function leaveGeneral() {
  if (view === 'general' && gen.text.trim()) {
    if (!(await confirmBox('작성 중이던 피드백이 삭제됩니다', '다른 화면으로 이동하면 적어 둔 내용이 사라집니다.'))) return false;
    gen.text = '';
  }
  if (view === 'settings' && settingsDirty()) {
    const r = await confirmBox('바꾼 설정을 저장하지 않았습니다', '저장하지 않고 나가면 바꾼 값은 적용되지 않습니다.', { ok: '저장하고 나가기', cancel: '저장하지 않고 나가기', focusOk: true });
    if (r === null) return false;
    if (r === true && !(await saveSettings())) return false;
  }
  if (view === 'settings') settingsSnap = '';
  if (view === 'cond') cd = null;
  return true;
}
async function setView(v) {
  if (v === view) return true;
  if (!(await leaveGeneral())) return false;
  if (v === 'log') {
    logItems = (await api.feedbackLog()) || [];
    logSel = logItems.length - 1;
  }
  if (v === 'general') gen.msg = null;
  view = v;
  render();
  if (v === 'settings') {
    $('#setMsg').textContent = '';
    fillSettings(await api.getSettings());
    const ver = await api.versions();
    $('#verInfo').textContent = `프로그램 v${ver.shell} · 스크립트 v${ver.app} · 런타임 ${ver.runtime} · 데이터 폴더 ${ver.root}`;
  }
  if (v === 'general') $('#gfText')?.focus();
  return true;
}
$('#btnInfo').addEventListener('click', () => setView(view === 'settings' ? 'jobs' : 'settings'));
$('#btnInfoClose').addEventListener('click', () => setView('jobs'));
$('#btnData').addEventListener('click', () => api.openDataFolder());
$('#btnUpdate').addEventListener('click', () => api.updateCheck());

// ---- Nav
$('#btnStart').addEventListener('click', async () => {
  const f = await api.startJob(); // 도면 1개 고르기 → 조건 입력 화면(값을 확인한 뒤 [모델링 시작])
  if (f) takeItems([f]);
});
api.on('open-model', () => $('#btnStart').click());
api.on('open-files', (items) => takeItems(items));
// 구조 검토: 파일 두 개(MIDAS 모델·해석 결과표)를 넣는 화면. 두 파일이 모이면 바로 검토(창에 함께 끌어다 놓아도 같음)
$('#btnS4').addEventListener('click', () => {
  rv.msg = null;
  setView('review');
});
api.on('open-review', () => setView('review'));
$('#btnFeedback').addEventListener('click', () => setView(view === 'general' ? 'jobs' : 'general'));
$('#btnLog').addEventListener('click', () => setView(view === 'log' ? 'jobs' : 'log'));
api.on('open-feedback', () => setView('general'));

// ---- 왼쪽 목록 폭: 가운데 줄을 끌어 조절(최소 170 · 기본 255 · 최대 340), 다음 실행에도 유지
const SIDE = { min: 170, def: 255, max: 340 };
function applySide(w) {
  const n = Math.min(SIDE.max, Math.max(SIDE.min, Math.round(Number(w) || SIDE.def)));
  $('#side').style.width = `${n}px`;
  return n;
}
api.getSideWidth().then(applySide);
const divider = $('#divider');
divider.addEventListener('pointerdown', (e) => {
  e.preventDefault();
  divider.setPointerCapture(e.pointerId);
  divider.classList.add('drag');
  document.body.classList.add('resizing');
  let w = $('#side').getBoundingClientRect().width;
  const move = (ev) => {
    w = applySide(ev.clientX);
  };
  const up = () => {
    divider.removeEventListener('pointermove', move);
    divider.removeEventListener('pointerup', up);
    divider.removeEventListener('pointercancel', up);
    divider.classList.remove('drag');
    document.body.classList.remove('resizing');
    api.setSideWidth(w);
  };
  divider.addEventListener('pointermove', move);
  divider.addEventListener('pointerup', up);
  divider.addEventListener('pointercancel', up);
});

// ---- 설정(구조 검토 값만): userData/config.json 에 저장, 다음 검토부터 적용.
//      골조 모델링 값(실행 범위·보 생성·보 수치·층고)은 설정이 아니라 작업마다 조건 입력 화면에서 정한다(1.9.0)
let settingDefaults = {};
let settingsSnap = ''; // 설정 화면을 열었을 때(또는 저장한 직후)의 값 — 저장하지 않고 나가는지 판단
const STAGE_DESC = { 1: '골조·중심선·OPEN 추출 후 DXF 저장', 2: '거더·보 생성 후 DXF 저장', 3: 'MIDAS GEN MGT 까지 생성 (기본)' };
const numInputs = () => [...document.querySelectorAll('#info .nums input[data-key]')];
const textInputs = () => [...document.querySelectorAll('#info .texts input[data-key], #info .texts select[data-key]')];
const rawSettings = () => JSON.stringify([...numInputs(), ...textInputs()].map((i) => [i.dataset.key, String(i.value).trim()]));
const settingsDirty = () => settingsSnap !== '' && rawSettings() !== settingsSnap;
function fillSettings({ values, defaults }) {
  settingDefaults = defaults || {};
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
  settingsSnap = rawSettings();
}
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
function readSettings() {
  const vals = {};
  for (const inp of numInputs()) if (numOk(inp)) vals[inp.dataset.key] = Number(inp.value);
  for (const inp of textInputs()) if (textOk(inp)) vals[inp.dataset.key] = inp.value.trim();
  return vals;
}
/** 숫자 칸: 숫자만 받는다(소수 허용 칸은 점 1개) */
const digitsOnly = (inp) => (inp.dataset.dec ? inp.value.replace(/[^\d.]/g, '').replace(/(\..*)\./g, '$1') : inp.value.replace(/[^\d]/g, ''));
for (const inp of numInputs()) {
  inp.addEventListener('input', () => {
    inp.value = digitsOnly(inp);
    inp.classList.toggle('changed', Number(inp.value) !== Number(settingDefaults[inp.dataset.key]));
  });
}
for (const inp of textInputs()) {
  inp.addEventListener('input', () => {
    inp.classList.toggle('changed', String(inp.value).trim() !== String(settingDefaults[inp.dataset.key] ?? ''));
    inp.classList.toggle('bad', !textOk(inp));
  });
}
/** 설정 저장. 잘못 적은 칸이 있으면 저장하지 않고 false */
async function saveSettings() {
  const m = $('#setMsg');
  const badN = numInputs().filter((i) => isShown(i) && !numOk(i)); // 보이는 칸만 검사
  if (badN.length) {
    const i = badN[0];
    m.textContent = `${i.closest('label').querySelector('span').textContent}: ${i.min}${i.max ? `~${i.max}` : ' 이상'} 숫자를 입력해 주세요`;
    m.className = 'msg err';
    i.focus();
    return false;
  }
  const badT = textInputs().filter((i) => isShown(i) && !textOk(i));
  if (badT.length) {
    const i = badT[0];
    m.textContent = `${i.closest('label').querySelector('span').textContent}: ${TEXT_HINT[i.dataset.re] || '값을 입력해 주세요'}`;
    m.className = 'msg err';
    i.focus();
    return false;
  }
  const r = await api.setSettings(readSettings());
  fillSettings(r);
  m.textContent = r.rejected && r.rejected.length ? `저장됨 — 일부 값은 범위 밖이라 유지됨 (${r.rejected.join(', ')})` : '저장됨 — 다음 검토부터 적용';
  m.className = 'msg ok';
  return true;
}
$('#setSave').addEventListener('click', () => saveSettings());
$('#setReset').addEventListener('click', async () => {
  if (!(await confirmBox('모든 내용을 기본으로 되돌립니다', '설정의 모든 값이 처음 상태로 바뀝니다.'))) return;
  const keys = [...numInputs(), ...textInputs()].map((i) => i.dataset.key); // 이 화면에 있는 값만(골조 모델링 값은 건드리지 않음)
  fillSettings(await api.setSettings(Object.fromEntries(keys.map((k) => [k, settingDefaults[k]]))));
  $('#setMsg').textContent = '기본값으로 되돌림';
  $('#setMsg').className = 'msg ok';
});
function optsLabel(o) {
  if (!o) return '';
  const p = [];
  if (o.stage && o.stage < 3) p.push(`${o.stage}단계까지`);
  if (o.beams === false && o.stage !== 1) p.push('보 없음');
  return p.join(' · ');
}

/** 이 작업에 적용된 모델링 값(진행 중·결과 화면의 칩) */
function condChips(c) {
  const st = Number(c['실행_단계']) || 3;
  const cs = [`${st}단계까지`];
  if (st >= 2) {
    if (c['보_생성']) cs.push('보 생성', `기준 거더 ${c['보_기준_거더길이']}`, `최소 베이 ${c['보_베이폭_최소']}`, `2개 ${c['보_베이폭_2개']}`, `3개 ${c['보_베이폭_3개']}`);
    else cs.push('보 없음');
  }
  if (st >= 3) cs.push(`층고 ${c['MGT_층고']}`);
  return `<div class="chips cond-chips" title="이 작업에 적용된 값">${cs.map((x) => `<span class="chip2">${esc(x)}</span>`).join('')}</div>`;
}

// ---- 골조 모델링 조건 입력: 도면을 고르면(파일 선택·끌어 놓기·[값 바꿔 다시 모델링]) 이 화면에서 값을 확인하고 [모델링 시작].
//      처음 값 = 앞 작업에 쓴 값(없으면 전에 설정에 저장해 둔 값). 처음 값과 달라진 칸은 노란 테두리.
let cd = null; // {file:{path,name}, base, defaults, note, seq, at}
let cdSeq = 0;
const COND_NUMS = [
  ['보_기준_거더길이', '보를 두는 기준 거더 길이'],
  ['보_베이폭_최소', '보를 두는 최소 베이 폭'],
  ['보_베이폭_2개', '보 2개(3등분) 기준 베이 폭'],
  ['보_베이폭_3개', '보 3개(4등분) 기준 베이 폭'],
];
async function openCond(file, fromJob) {
  if (!(await leaveGeneral())) return;
  const d = await api.condDefaults();
  let base = d.values;
  let note = d.from === 'job' ? '앞 작업에 쓴 값으로 채워 두었습니다.' : d.from === 'settings' ? '전에 설정에 저장해 둔 값으로 채워 두었습니다.' : '기본값으로 채워 두었습니다.';
  if (fromJob) {
    const o = fromJob.opts || {};
    base = { ...d.values, ...(fromJob.cond || { 실행_단계: o.stage || 3, 보_생성: o.beams !== false }) };
    note = `${fmtDate(fromJob.ended || fromJob.started).slice(11)} 작업의 값에서 시작합니다. 바꾼 칸은 노란 테두리로 표시됩니다.`;
  }
  cd = { file: { path: file.path, name: file.name }, base, defaults: d.defaults, note, seq: ++cdSeq, at: Date.now() };
  view = 'cond';
  render();
}
function renderCond() {
  const c = cd;
  const b = c.base;
  const numL = (k, label) => `<label><span>${label}</span><input type="number" data-key="${k}" min="100" step="100" inputmode="numeric" value="${esc(b[k])}" /><em>mm</em><i class="dflt">기본 ${esc(c.defaults[k] ?? '-')}</i></label>`;
  const html = `<div data-cond="${c.seq}">
    <h2 class="d-name" title="${esc(c.file.path)}">${esc(c.file.name)}</h2>
    <div class="d-status running">모델링 조건 — 값을 확인하고 [모델링 시작] 을 누르면 실행합니다</div>
    <div class="setgrp"><h4>실행 범위 — 어디까지 진행하고 저장할지</h4><div class="segrow"><div class="seg" id="cdStage">${[1, 2, 3].map((v) => `<button type="button" data-v="${v}">${v}단계까지</button>`).join('')}</div><span class="seg-desc" id="cdStageDesc"></span></div></div>
    <div class="setgrp" id="cdBeamGrp"><h4>보(BEAM)</h4><label class="chk"><input type="checkbox" id="cdBeams"${b['보_생성'] ? ' checked' : ''} /> 2단계에서 보 생성 <span class="hint inline">(끄면 거더만 생성)</span></label>
      <div id="cdBeamNums" class="nums">${COND_NUMS.map(([k, l]) => numL(k, l)).join('')}</div></div>
    <div class="setgrp" id="cdMgtGrp"><h4>MIDAS GEN MGT (3단계)</h4><div class="nums">${numL('MGT_층고', '층고(층 높이)')}</div></div>
    <div class="cond-foot"><button class="btn" data-act="cd-start">모델링 시작</button><button class="btn ghost" data-act="cd-cancel">취소</button><span class="msg" id="cdMsg">${esc(c.note)}</span></div>
  </div>`;
  if (setPart('#dTop', html)) bindCond();
  setPart('#dFb', '');
}
function bindCond() {
  const el = $('#dTop');
  const base = cd.base;
  let stage = [1, 2, 3].includes(Number(base['실행_단계'])) ? Number(base['실행_단계']) : 3;
  const beams = el.querySelector('#cdBeams');
  const sync = () => {
    for (const bt of el.querySelectorAll('#cdStage button')) {
      bt.classList.toggle('on', Number(bt.dataset.v) === stage);
      bt.classList.toggle('changed', Number(bt.dataset.v) === stage && stage !== Number(base['실행_단계']));
    }
    el.querySelector('#cdStageDesc').textContent = STAGE_DESC[stage];
    el.querySelector('#cdBeamGrp').classList.toggle('hidden', stage < 2); // 1단계까지만이면 보 값은 의미 없음
    el.querySelector('#cdBeamNums').classList.toggle('hidden', !beams.checked); // 보를 끄면 수치 숨김
    el.querySelector('#cdMgtGrp').classList.toggle('hidden', stage < 3); // MGT 를 만들지 않으면 층고 숨김
  };
  el.querySelector('#cdStage').addEventListener('click', (e) => {
    const bt = e.target.closest('button[data-v]');
    if (!bt) return;
    stage = Number(bt.dataset.v);
    sync();
  });
  beams.addEventListener('change', sync);
  const say = (t, cls = '') => {
    const m = el.querySelector('#cdMsg');
    m.textContent = t;
    m.className = `msg ${cls}`;
  };
  for (const inp of el.querySelectorAll('.nums input[data-key]')) {
    inp.addEventListener('input', () => {
      inp.value = digitsOnly(inp);
      inp.classList.toggle('changed', Number(inp.value) !== Number(base[inp.dataset.key]));
    });
  }
  el.querySelector('[data-act=cd-cancel]').addEventListener('click', () => {
    cd = null;
    view = 'jobs';
    render();
  });
  el.querySelector('[data-act=cd-start]').addEventListener('click', async (e) => {
    const vals = { 실행_단계: stage, 보_생성: beams.checked };
    for (const inp of el.querySelectorAll('.nums input[data-key]')) {
      if (numOk(inp)) vals[inp.dataset.key] = Number(inp.value);
      else if (isShown(inp)) {
        say(`${inp.closest('label').querySelector('span').textContent}: ${inp.min} 이상 숫자를 입력해 주세요`, 'err');
        inp.focus();
        return;
      } else vals[inp.dataset.key] = base[inp.dataset.key]; // 숨긴 칸은 처음 값 그대로
    }
    e.target.disabled = true;
    const r = await api.run(cd.file.path, vals);
    if (!r.ok) {
      e.target.disabled = false;
      say(r.message || '시작하지 못했습니다', 'err');
      return;
    }
    cd = null;
    view = 'jobs';
    selected = r.id;
    render();
  });
  sync();
}

// ---- 파일 넣기(끌어다 놓기·파일 선택 공통): 도면 = 골조 모델링, MIDAS 모델·해석 결과표 = 구조 검토.
//      종류는 프로그램이 파일 내용으로 가린다(describeFiles). 모델과 결과표를 함께 넣으면 모델을 읽은 뒤 곧바로 검토한다.
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function reviewSay(text) {
  if (!(await setView('review'))) return;
  rv.msg = text;
  render();
}
async function takeItems(items) {
  if (!items || !items.length) return;
  const models = items.filter((i) => i.kind === 'model');
  const tables = items.filter((i) => i.kind === 'table');
  const drawings = items.filter((i) => i.kind === 'drawing');
  if (drawings.length && !models.length && !tables.length) return openCond(drawings[0]);
  if (drawings.length) return reviewSay('도면과 구조 검토 파일을 함께 넣을 수 없습니다. 도면은 [+ 골조 모델링] 으로, MIDAS 모델과 해석 결과표는 여기에 넣어 주세요.');
  if (models.length > 1) return reviewSay('MIDAS 모델은 한 번에 1개만 넣을 수 있습니다.');
  if (tables.length > 1) return reviewSay('해석 결과표는 한 번에 1개만 넣을 수 있습니다.');
  if (models.length) {
    if (!(await leaveGeneral())) return;
    const table = tables[0] || (view === 'review' ? rv.table : null);
    const r = await api.reviewStart(models[0].path, table ? table.path : null);
    if (!r.ok) return reviewSay(r.message);
    rv.table = null;
    rv.msg = null;
    view = 'jobs';
    selected = r.id;
    render();
    return;
  }
  // 결과표만 넣음: 지금 보고 있는 구조 검토 작업에 넣는다. 그런 작업이 없으면 [+ 구조 검토] 화면에 두고 모델을 기다린다
  const cur = () => state.jobs.find((j) => j.id === selected);
  if (view === 'jobs' && cur() && cur().kind === 's4' && cur().state !== 'failed' && cur().state !== 'cancelled') {
    const id = selected;
    for (let i = 0; i < 80 && cur() && cur().id === id && (cur().state === 'queued' || cur().state === 'running' || (cur().stage4 && cur().stage4.state === 'running')); i++) await sleep(250);
    const r = await api.stage4Run(id, tables[0].path);
    if (!r.ok && r.message) {
      const m = document.querySelector('#dTop .s4 .s4-msg');
      if (m) {
        m.textContent = r.message;
        m.className = 's4-msg msg err';
      }
    }
    return;
  }
  if (!(await setView('review'))) return;
  rv.table = tables[0];
  rv.msg = null;
  render();
}
['dragenter', 'dragover', 'dragleave'].forEach((ev) => document.addEventListener(ev, (e) => e.preventDefault()));
document.addEventListener('drop', async (e) => {
  e.preventDefault();
  const paths = [...(e.dataTransfer?.files || [])].map((f) => api.pathOf(f)).filter(Boolean);
  if (paths.length) takeItems(await api.describeFiles(paths));
});

// ---- 상태
api.on('engine-state', (st) => {
  const prevIds = new Set(state.jobs.map((j) => j.id));
  state = st;
  const fresh = st.jobs.find((j) => !prevIds.has(j.id));
  if (fresh) {
    selected = fresh.id;
    const keep = (view === 'general' && gen.text.trim()) || view === 'cond' || (view === 'settings' && settingsDirty());
    if (view !== 'jobs' && !keep) view = 'jobs'; // 새 작업이 생기면 그 작업 화면으로(쓰던 피드백·조건 입력·저장하지 않은 설정이 있으면 그대로 둠)
  }
  render();
});
api.engineState().then((st) => {
  state = st;
  if (!selected && st.jobs.length) selected = st.jobs[st.jobs.length - 1].id;
  render();
});
setInterval(() => {
  if (state.running || state.jobs.some((j) => j.stage4 && j.stage4.state === 'running')) render();
}, 1000);
api.on('install-progress', (msg) => {
  $('#prepBar').textContent = msg || '';
  $('#prepBar').classList.toggle('hidden', !msg);
});
api.on('feedback-progress', (p) => {
  if (p.jobId == null) return;
  progress[p.jobId] = p;
  render();
});

function render() {
  $('#info').classList.toggle('hidden', view !== 'settings');
  $('#work').classList.toggle('hidden', view === 'settings');
  $('#btnInfo').classList.toggle('on', view === 'settings');
  $('#btnFeedback').classList.toggle('on', view === 'general');
  $('#btnLog').classList.toggle('on', view === 'log');
  if (view === 'settings') return;
  if (view === 'log') {
    renderLog();
    return;
  }
  if (view === 'cond' && !cd) view = 'jobs';
  if (state.jobs.length && !state.jobs.some((j) => j.id === selected)) selected = state.jobs[state.jobs.length - 1].id;
  renderList();
  if (view === 'general') renderGeneral();
  else if (view === 'review') renderReview();
  else if (view === 'cond' && cd) renderCond();
  else renderDetail(state.jobs.find((j) => j.id === selected));
}

// ---- 왼쪽 작업 목록: 날짜·시간 / 파일 이름 / 상태
/** 목록의 상태 글자. 실패(파일 문제) = 빨강, 에러(프로그램 오류) = 노랑 */
function listState(j) {
  const s4k = j.kind === 's4';
  const fb = j.feedback && j.feedback.sent ? ' · 피드백 전송됨' : j.feedback && j.feedback.skipped ? ' · 문제 없음' : '';
  if (j.state === 'queued') return { text: '대기', cls: 'queued' };
  if (j.state === 'running') return { text: s4k ? '모델 읽는 중' : '모델링 중', cls: 'running' };
  if (j.state === 'cancelled') return { text: '취소', cls: 'cancelled' };
  if (j.state === 'failed') return j.failKind === 'input' ? { text: s4k ? '검토 실패' : '모델링 실패', cls: 'failed' } : { text: s4k ? '검토 에러' : '모델링 에러', cls: 'failed error' };
  if (!s4k) return { text: `모델링 완료${fb}`, cls: 'done' };
  const s = j.stage4;
  if (s && s.state === 'running') return { text: '검토 중', cls: 'running' };
  if (s && s.state === 'failed' && s.failKind !== 'input') return { text: '검토 에러', cls: 'failed error' };
  if (s && s.state === 'done' && s.summary) return { text: `검토 완료 · OK ${s.summary.ok} / NG ${s.summary.ng}${fb}`, cls: 'done' };
  return { text: '결과표 넣기 대기', cls: 'done' }; // 넣은 파일이 결과표가 아니었던 경우도 실패가 아니라 다시 넣기를 기다림
}
const jobTime = (j) => (j.stage4 && j.stage4.ended) || j.ended || j.started || j.created || 0;
/** 목록 상태 줄 맨 오른쪽 태그(11-18 사용자 지시): [전송하기]·[건너뛰기] 를 누르지 않은 작업은 서버에 남지 않으므로 눈에 띄게 한다.
 *  끝까지 마친 작업(= [건너뛰기] 가 나오는 작업)에만 붙인다 — 미완료 = 빨강, 전송했거나 건너뛴 작업 = 초록 */
function fbTag(j) {
  const done = Boolean(j.feedback && (j.feedback.sent || j.feedback.skipped));
  if (!done && !canSkip(j)) return '';
  return `<span class="ji-fb ${done ? 'ok' : 'no'}">${done ? '피드백 완료' : '피드백 미완료'}</span>`;
}
function renderList() {
  // 아직 작업이 아닌 조건 입력 화면은 목록 맨 위에 한 줄로 보여 준다.
  // [+ 구조 검토] 를 누른 화면은 목록에 줄을 만들지 않는다(11-18 사용자 지시): 오른쪽 화면만 바뀌고 목록은 아무것도 선택되지 않은 상태
  const pseudo =
    view === 'cond' && cd
      ? `<li class="jobitem running sel pseudo"><div class="ji-date">${esc(fmtDate(cd.at))}</div><div class="ji-name" title="${esc(cd.file.path)}">${esc(cd.file.name)}</div><div class="ji-state">조건 입력 중</div></li>`
      : '';
  if (!state.jobs.length) {
    setPart('#jobList', pseudo || '<li class="none">작업이 없습니다</li>');
    return;
  }
  const html = pseudo + [...state.jobs]
    .reverse()
    .map((j) => {
      const st = listState(j);
      const ol = j.kind === 's4' ? '' : optsLabel(j.opts);
      return `<li class="jobitem ${st.cls}${view === 'jobs' && j.id === selected ? ' sel' : ''}" data-id="${j.id}"><div class="ji-date">${esc(fmtDate(jobTime(j)) || '-')}</div><div class="ji-name" title="${esc(j.src)}">${esc(j.name)}</div><div class="ji-state"><span class="ji-st" title="${esc(st.text)}">${esc(st.text)}${ol ? `<span class="ji-opts">${esc(ol)}</span>` : ''}</span>${fbTag(j)}</div>${j.state !== 'running' ? '<button class="ji-del" title="목록에서 지우기">✕</button>' : ''}</li>`;
    })
    .join('');
  setPart('#jobList', html);
}
$('#jobList').addEventListener('click', async (e) => {
  const li = e.target.closest('li[data-id]');
  if (!li) return;
  const id = Number(li.dataset.id);
  if (view === 'log') {
    logSel = id;
    render();
    return;
  }
  if (e.target.closest('.ji-del')) {
    api.removeJob(id);
    return;
  }
  if (view !== 'jobs') {
    if (!(await leaveGeneral())) return;
    view = 'jobs';
  }
  if (selected !== id) for (const k of Object.keys(dlMsg)) delete dlMsg[k]; // 다른 작업으로 가면 저장 위치 글은 지움
  selected = id;
  render();
});

/** 구조 검토 작업 화면 머리: 읽은 모델 요약(검토 대상·종류별 수·검토 제외 사유) */
function renderModel(j) {
  const m = j.model;
  if (!m) return '';
  const sk = Object.entries(m.skipped || {});
  const exc = sk.filter(([k]) => !/^[A-Z?]+$/.test(k)); // 더미·WG·비직사각형 등(=검토 제외). WALL·PLATE 같은 요소 종류는 애초에 대상이 아님
  const other = sk.filter(([k]) => /^[A-Z?]+$/.test(k));
  const excN = exc.reduce((a, [, v]) => a + v, 0);
  const secs = Object.entries(m.skipped_secs || {}).map(([k, v]) => `${k} ${num(v)}`).join(', ');
  const fck = (m.fck || []).length ? `콘크리트 ${m.fck.map((f) => `C${f}`).join('·')} (모델 재료 등급)` : '콘크리트 강도는 설정값 사용';
  return `<div class="chips"><span class="chip2">검토 대상 ${num(m.elements)}</span><span class="chip2">기둥 ${num(m.col)}</span><span class="chip2">거더 ${num(m.girder)}</span><span class="chip2">보 ${num(m.beam)}</span>${excN ? `<span class="chip2 warn" title="더미·벽 위 가상 보(WG)·직사각형 RC 가 아닌 단면">검토 제외 ${num(excN)}</span>` : ''}</div>
    <p class="hint">단위 ${esc(m.unit || '-')} · 단면 ${num(m.sections)}종 · 층 ${num(m.stories)}개 · ${esc(fck)}${(m.fck_unknown || []).length ? ` · 등급 미상 재료(${esc(m.fck_unknown.join(', '))})는 설정값` : ''}</p>
    ${exc.length ? `<p class="hint">검토 제외 — ${esc(exc.map(([k, v]) => `${k} ${num(v)}개`).join(' · '))}${secs ? ` (단면: ${esc(secs)})` : ''}${other.length ? ` · 그 밖에 기둥·보가 아닌 요소 ${esc(other.map(([k, v]) => `${k} ${num(v)}`).join(', '))}` : ''}</p>` : other.length ? `<p class="hint">기둥·보가 아닌 요소 ${esc(other.map(([k, v]) => `${k} ${num(v)}`).join(', '))} 는 대상이 아닙니다.</p>` : ''}`;
}

// ---- 오른쪽: 작업 결과 화면(위 = 상태·결과 파일·구조 검토, 아래 = 피드백)
const dlMsg = {}; // jobId → 저장 결과 글
function topHtml(j) {
  const s4k = j.kind === 's4'; // 구조 검토 작업(모델 MGT)
  const st = listState(j);
  const pct = j.state === 'done' ? 100 : j.state === 'running' ? Math.min(95, Math.round((j.stepIdx / (j.total || 5)) * 100)) : 0;
  const code = /\(코드 [^)]*\)/.exec(j.message || '');
  const status =
    dlMsg[j.id] ||
    (j.state === 'queued'
      ? '대기 중'
      : j.state === 'running'
        ? `${j.step} · ${fmtSec(Date.now() - j.started)}`
        : j.state === 'done'
          ? `${s4k ? j.message : String(j.message || '').replace(/^완료/, '모델링 완료')} · ${fmtDate(j.ended)}`
          : j.state === 'failed'
            ? code ? `${st.text} ${code[0]}` : `${st.text} — ${j.message}`
            : j.message);
  const errKind = j.state === 'failed' && j.failKind !== 'input';
  return `<div data-job="${j.id}">
    <h2 class="d-name" title="${esc(j.src)}">${esc(j.name)}</h2>
    <div class="d-status ${j.state}${errKind ? ' error' : ''}">${esc(status)}${!j.cond && optsLabel(j.opts) ? `<span class="d-opts" title="이 작업에 적용된 설정">${esc(optsLabel(j.opts))}</span>` : ''}</div>
    ${!s4k && j.cond ? condChips(j.cond) : ''}
    ${j.state === 'running' || j.state === 'queued' ? `<div class="bar"><i style="width:${pct}%"></i></div><pre class="d-tail">${esc((j.tail || []).slice(-5).join('\n'))}</pre><div class="row"><button class="btn small danger" data-act="cancel">작업 취소</button></div>` : ''}
    ${
      j.state === 'failed'
        ? `<div class="fail ${errKind ? 'error' : 'input'}">
            <b>${errKind ? '프로그램 오류' : s4k ? '모델 파일 문제' : '도면 문제'}</b> ${esc(j.failReason || '')}
            <div class="hint">${errKind ? esc(j.errorReport ? j.errorReport.message : '오류 보고를 자동으로 보냅니다') : s4k ? 'MIDAS 에서 모델을 MGT 로 다시 저장한 뒤 위의 [+ 구조 검토] 로 다시 선택해 주세요.' : '안내대로 파일을 갖춘 뒤 위의 [+ 골조 모델링] 으로 다시 시작하면 됩니다.'}</div>
          </div><pre class="d-tail">${esc((j.tail || []).slice(-8).join('\n'))}</pre>`
        : ''
    }
    ${j.state === 'done' && s4k ? renderModel(j) : ''}
    ${j.state === 'done' && !s4k ? `<div class="row gap"><button class="btn" data-act="download">⬇ 결과 DXF</button>${j.mgt ? `<button class="btn" data-act="download-mgt">⬇ MIDAS GEN (MGT)</button>` : ''}<button class="btn ghost" data-act="rerun">값 바꿔 다시 모델링</button></div><p class="hint">${esc(j.result ? j.result.split(/[\\/]/).pop() : '')}</p>` : ''}
    ${j.state === 'done' ? renderStage4(j) : ''}
  </div>`;
}

function renderDetail(j) {
  if (!j) {
    setPart('#dTop', '<p class="hint none-main">작업이 없습니다. 위의 [+ 골조 모델링] 또는 [+ 구조 검토] 로 시작하면 결과가 여기에 표시됩니다. 도면(DWG·DXF)이나 MIDAS 모델(.mgt)과 해석 결과표 파일을 이 창에 끌어다 놓아도 됩니다.</p>');
    setPart('#dFb', '');
    return;
  }
  if (setPart('#dTop', topHtml(j))) bindTop(j);
  if (setPart('#dFb', fbHtml(j))) bindFb(j);
  syncFb(j);
}

function bindTop(j) {
  const el = $('#dTop');
  el.querySelector('[data-act=cancel]')?.addEventListener('click', () => api.cancel());
  el.querySelector('[data-act=rerun]')?.addEventListener('click', () => openCond({ path: j.src, name: j.name }, j));
  // 구조 검토: 결과표 첨부 → 검토 / 엑셀·수정 MGT 다운로드 / 승인
  const s4msg = (t, cls = '') => {
    const m = el.querySelector('.s4 .s4-msg');
    if (m) {
      m.textContent = t;
      m.className = 's4-msg msg ' + cls;
    }
  };
  el.querySelectorAll('[data-act=rv-pick]').forEach((b) =>
    b.addEventListener('click', async () => {
      b.disabled = true;
      const items = await api.reviewPick(b.dataset.want);
      b.disabled = false;
      takeItems(items);
    }),
  );
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
  for (const [act, kind] of [['download', 'dxf'], ['download-mgt', 'mgt']]) {
    el.querySelector(`[data-act=${act}]`)?.addEventListener('click', async (e) => {
      e.target.disabled = true;
      const r = await api.download(j.id, kind);
      if (r.message) dlMsg[j.id] = r.message; // 저장 위치를 상태 줄에 표시
      if (!setPart('#dTop', topHtml(j))) e.target.disabled = false;
      else bindTop(j);
    });
  }
}

// ---- 피드백 칸(작업 결과 화면 아래). 종류 = [공통 규칙] [이 파일에만 해당], 내용이 있으면 [전송하기] 가 켜짐, [건너뛰기] = 결과에 문제 없음
const JOB_KINDS = [['rule', '공통 규칙', '여러 파일에서 같은 문제가 나올 때'], ['file', '이 파일에만 해당', '이 파일의 특수한 경우일 때']];
const GEN_KINDS = [['rule', '공통 규칙', '여러 파일에 공통인 생성·검토 규칙 의견'], ['ui', '프로그램 화면·기능', '버튼 위치·화면 배치·기능 추가 의견']];
const KIND_LABEL = { rule: '공통 규칙', file: '이 파일에만 해당', ui: '프로그램 화면·기능', unknown: '모름' };
const SCOPE_KIND = { all: 'rule', file: 'file' };
function kindRow(kinds, sel, dis) {
  const cur = kinds.find((k) => k[0] === sel) || kinds[0];
  return `<div class="fb-kind"><div class="lb">종류</div><div class="ct"><div class="seg" data-seg="kind">${kinds.map(([v, l]) => `<button type="button" data-v="${v}" class="${v === cur[0] ? 'on' : ''}" ${dis ? 'disabled' : ''}>${esc(l)}</button>`).join('')}</div><span class="seg-desc">${esc(cur[2])}</span></div></div>`;
}
function draftOf(j) {
  if (!drafts[j.id]) drafts[j.id] = { text: (j.draft && j.draft.text) || '', kind: j.draft && j.draft.kind === 'file' ? 'file' : 'rule' };
  return drafts[j.id];
}
const draftTimers = {};
function saveDraftSoon(id) {
  clearTimeout(draftTimers[id]);
  draftTimers[id] = setTimeout(() => {
    const d = drafts[id];
    api.setDraft(id, d && (d.text.trim() || d.kind !== 'rule') ? { text: d.text, kind: d.kind } : null);
  }, 500);
}
/** [건너뛰기] 는 끝까지 마친 작업에서만(구조 검토 작업은 검토가 끝난 뒤) */
const canSkip = (j) => j.state === 'done' && (j.kind !== 's4' || Boolean(j.stage4 && j.stage4.state === 'done' && j.stage4.summary));
function fbHtml(j) {
  if (j.state !== 'done' && j.state !== 'failed') return '';
  const s4k = j.kind === 's4';
  const f = j.feedback;
  if (f && f.skipped) {
    return `<section class="fb card slim" data-job="${j.id}"><div class="fb-head"><h3>피드백</h3><span class="fb-ok">${CHECK}문제 없음으로 표시했습니다.</span></div></section>`;
  }
  if (f && f.sent) {
    return `<section class="fb card" data-job="${j.id}">
      <div class="fb-head between"><h3>피드백</h3><span class="fb-ok">${CHECK}전송 완료 ${esc(fmtDate(f.at))}</span></div>
      <div class="fb-kind"><div class="lb">종류</div><div class="ct chipct"><span class="fb-chip">${esc(KIND_LABEL[SCOPE_KIND[f.scope] || 'unknown'])}</span></div></div>
      <div class="fb-text">${esc(f.text)}</div>
      <div class="fb-note">${f.file ? `서버로 보내지 못해 바탕화면에 파일로 저장했습니다 (${esc(String(f.file).split(/[\\/]/).pop())}). 카카오톡·메일로 보내 주세요. ` : '반영되면 자동 업데이트로 알려 드립니다. '}같은 작업에는 한 번만 보낼 수 있습니다.</div>
    </section>`;
  }
  const d = draftOf(j);
  const busy = Boolean(sending[j.id]);
  const prog = progress[j.id];
  return `<section class="fb card" data-job="${j.id}">
    <div class="fb-head"><h3>피드백</h3><span class="desc">${s4k ? '검토 결과에서 잘못된 점, 빠진 것, 바라는 점을 적어 주세요.' : '결과에서 잘못된 점, 빠진 것, 바라는 점을 적어 주세요.'}</span></div>
    ${kindRow(JOB_KINDS, d.kind, busy)}
    <textarea rows="4" ${busy ? 'disabled' : ''} placeholder="${s4k ? '예) 단면 RB1 이 거더로 분류됨. WG 단면도 검토 대상에 넣어야 함.' : '예) 램프 구간의 곡선 보가 생성되지 않음. 기둥 없는 구역은 벽을 따라 거더가 있어야 함.'}"></textarea>
    ${busy && prog ? `<div class="bar"><i style="width:${Math.round((prog.progress || 0) * 100)}%"></i></div>` : ''}
    <div class="fb-foot"><span class="fb-hint">${busy ? esc(prog ? prog.message : '전송 중…') : ''}</span><span class="acts">${canSkip(j) ? `<button class="btn ghost" data-act="skip" ${busy ? 'disabled' : ''}>건너뛰기</button>` : ''}<button class="btn" data-act="send" disabled>${busy ? '전송 중…' : '전송하기'}</button></span></div>
  </section>`;
}
function bindFb(j) {
  const sec = $('#dFb .fb');
  const ta = sec && sec.querySelector('textarea');
  if (!ta) return;
  const d = draftOf(j);
  ta.value = d.text;
  ta.addEventListener('input', () => {
    d.text = ta.value;
    delete fbMsg[j.id];
    saveDraftSoon(j.id);
    syncFb(j);
  });
  sec.querySelector('[data-seg=kind]').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-v]');
    if (!b || b.disabled) return;
    d.kind = b.dataset.v;
    saveDraftSoon(j.id);
    render();
  });
  sec.querySelector('[data-act=send]').addEventListener('click', () => sendJobFb(j));
  sec.querySelector('[data-act=skip]')?.addEventListener('click', () => skipJobFb(j));
}
/** 전송 버튼 켜짐 여부와 아래 안내 글(다시 그리지 않고 글자만 바꿈) */
function syncFb(j) {
  const sec = $('#dFb .fb');
  const ta = sec && sec.querySelector('textarea');
  if (!ta) return;
  const busy = Boolean(sending[j.id]);
  const has = Boolean(ta.value.trim());
  sec.querySelector('[data-act=send]').disabled = busy || !has;
  if (busy) return;
  const hint = sec.querySelector('.fb-hint');
  const msg = fbMsg[j.id];
  const c = has ? window.classifyFeedback(ta.value) : null;
  hint.className = 'fb-hint' + (msg ? ` ${msg.cls}` : '');
  hint.textContent = msg
    ? msg.text
    : c && c.category === 'ui'
      ? `프로그램 화면·기능 의견으로 보입니다 (${c.ui.slice(0, 4).join('·')}). 그대로 전송하면 됩니다.`
      : canSkip(j)
        ? '결과에 문제가 없으면 건너뛰기, 있으면 내용을 적어 전송해 주세요.'
        : '내용을 적어 전송해 주세요.';
}
async function sendJobFb(j) {
  const d = draftOf(j);
  if (!d.text.trim() || sending[j.id]) return;
  sending[j.id] = true;
  delete fbMsg[j.id];
  render();
  const r = await api.sendFeedback({ text: d.text, scope: d.kind === 'file' ? 'file' : 'all', category: window.classifyFeedback(d.text).category, jobId: j.id });
  delete sending[j.id];
  delete progress[j.id];
  if (r.sent) {
    clearTimeout(draftTimers[j.id]);
    delete drafts[j.id];
    api.setDraft(j.id, null);
  } else fbMsg[j.id] = { text: r.message || '전송하지 못했습니다', cls: 'err' };
  render();
}
async function skipJobFb(j) {
  const d = draftOf(j);
  if (d.text.trim() && !(await confirmBox('적어 둔 피드백을 보내지 않습니다', '건너뛰기를 하면 적어 둔 내용은 사라지고, 이 작업은 문제 없음으로 표시됩니다.'))) return;
  const r = await api.skipFeedback(j.id);
  if (r && r.ok) {
    clearTimeout(draftTimers[j.id]);
    delete drafts[j.id];
  } else fbMsg[j.id] = { text: (r && r.message) || '표시하지 못했습니다', cls: 'err' };
  render();
}

// ---- [피드백]: 왼쪽 작업 목록은 그대로, 오른쪽만 작업 없이 보내는 피드백 화면. 종류 = [공통 규칙] [프로그램 화면·기능]
function renderGeneral() {
  setPart('#dTop', '');
  const html = `<section class="fb card top" data-general="1">
    <div class="fb-head"><h3>피드백</h3><span class="desc">작업과 상관없이 규칙이나 프로그램 화면·기능에 대한 의견을 적어 주세요.</span></div>
    ${kindRow(GEN_KINDS, gen.kind, gen.sending)}
    <textarea id="gfText" rows="6" ${gen.sending ? 'disabled' : ''} placeholder="예) 보 분할 기준 길이를 설정에서 바꿀 수 있게 해 달라.&#10;예) 결과 DXF 다운로드 버튼을 목록 위쪽으로 옮기고 싶다."></textarea>
    <div class="fb-foot"><span class="fb-hint" id="gfMsg"></span><span class="acts"><button class="btn" id="gfSend" disabled>${gen.sending ? '전송 중…' : '전송하기'}</button></span></div>
  </section>`;
  if (setPart('#dFb', html)) {
    const ta = $('#gfText');
    ta.value = gen.text;
    ta.addEventListener('input', () => {
      gen.text = ta.value;
      gen.msg = null;
      syncGeneral();
    });
    $('#dFb [data-seg=kind]').addEventListener('click', (e) => {
      const b = e.target.closest('button[data-v]');
      if (!b || b.disabled) return;
      gen.kind = b.dataset.v;
      render();
      $('#gfText')?.focus();
    });
    $('#gfSend').addEventListener('click', sendGeneral);
  }
  syncGeneral();
}
function syncGeneral() {
  const ta = $('#gfText');
  if (!ta) return;
  $('#gfSend').disabled = gen.sending || !ta.value.trim();
  const m = $('#gfMsg');
  m.className = 'fb-hint' + (gen.msg ? ` ${gen.msg.cls}` : '');
  m.textContent = gen.sending ? '전송 중…' : gen.msg ? gen.msg.text : '';
}
async function sendGeneral() {
  const text = gen.text;
  if (!text.trim() || gen.sending) return;
  gen.sending = true;
  gen.msg = null;
  render();
  const r = await api.sendFeedback({ text, scope: 'general', category: gen.kind === 'ui' ? 'ui' : 'rule', jobId: null });
  gen.sending = false;
  if (r.sent) gen.text = gen.text === text ? '' : gen.text;
  gen.msg = { text: r.message || (r.sent ? '전송 완료' : '전송하지 못했습니다'), cls: r.ok ? 'ok' : 'err' };
  render();
}

// ---- [피드백 로그]: 왼쪽 = 지금까지 보낸 피드백(날짜·시간 + 제목), 오른쪽 = 고른 피드백의 내용
function renderLog() {
  if (!logItems.length) {
    setPart('#jobList', '<li class="none">보낸 피드백이 없습니다</li>');
    setPart('#dTop', '<p class="hint none-main">보낸 피드백이 없습니다. 작업 결과 화면 아래의 피드백이나 위의 [피드백] 으로 보내면 여기에 쌓입니다.</p>');
    setPart('#dFb', '');
    return;
  }
  if (!logItems[logSel]) logSel = logItems.length - 1;
  setPart(
    '#jobList',
    logItems
      .map((it, i) => `<li class="jobitem logitem${i === logSel ? ' sel' : ''}" data-id="${i}"><div class="ji-date">${esc(fmtDate(it.at))}</div><div class="ji-name" title="${esc(it.title)}">${esc(it.title)}</div></li>`)
      .reverse()
      .join(''),
  );
  const it = logItems[logSel];
  setPart('#dTop', '');
  setPart(
    '#dFb',
    `<section class="fb card top" data-log="${logSel}">
      <div class="fb-head between"><h3 class="long" title="${esc(it.title)}">${esc(it.title)}</h3><span class="fb-ok">${CHECK}전송 완료 ${esc(fmtDate(it.at))}</span></div>
      <div class="fb-kind"><div class="lb">종류</div><div class="ct chipct"><span class="fb-chip">${esc(KIND_LABEL[it.kind] || KIND_LABEL.unknown)}</span></div></div>
      <div class="fb-text">${esc(it.text)}</div>
      ${it.file ? `<div class="fb-note">서버로 보내지 못해 바탕화면에 파일로 저장했습니다 (${esc(String(it.file).split(/[\\/]/).pop())}). 카카오톡·메일로 보내 주세요.</div>` : ''}
    </section>`,
  );
}

/** 파일 두 칸(MIDAS 모델·해석 결과표). model/table = {name, mtime} 또는 null, note = 결과표 칸에 적을 안내 {name, text} */
const TABLE_DESC = 'Results → Result Tables → Beam → Force 표에서 Export to Excel 로 저장한 파일 (.xls · .xlsx · .txt · .csv)';
function slotsHtml({ model, table, note, hint }) {
  const filled = (f) => `${esc(f.name)}${f.mtime ? ` · ${esc(fmtDate(f.mtime))} 저장` : ''}`;
  return `<div class="drop">
    <div class="slot${model ? ' filled' : ''}"><div class="slot-lb">MIDAS 모델</div><div class="slot-desc">${model ? filled(model) : 'File → Export → MGT 로 저장한 파일 (.mgt)'}</div><button class="btn ghost small" data-act="rv-pick" data-want="model">${model ? '다른 파일' : '파일 선택'}</button></div>
    <div class="slot${table ? ' filled' : note ? ' bad' : ''}"><div class="slot-lb">해석 결과표 (Beam Force)</div><div class="slot-desc">${table ? filled(table) : note ? `<b>${esc(note.name || '넣은 파일')}</b> — ${esc(note.text)}` : TABLE_DESC}</div><button class="btn ${model && !table ? '' : 'ghost '}small" data-act="rv-pick" data-want="table">${table ? '다른 파일' : '파일 선택'}</button></div>
    <p class="drop-hint">${esc(hint)}</p>
  </div>`;
}

// ---- [+ 구조 검토] 를 눌렀을 때: 파일 두 개 넣기. 모델이 들어오면 작업이 만들어지고(왼쪽 목록), 결과표까지 있으면 곧바로 검토한다
function renderReview() {
  const html = `<div data-review>
    <h2 class="d-name">구조 검토</h2>
    <div class="d-status">MIDAS 에서 내보낸 파일 두 개를 넣으면 바로 검토합니다.</div>
    ${slotsHtml({ model: null, table: rv.table, note: null, hint: rv.table ? 'MIDAS 모델을 넣으면 바로 검토합니다. 이 창에 끌어 놓아도 됩니다.' : '두 파일을 이 창에 함께 끌어 놓아도 됩니다. 종류는 자동으로 구분합니다.' })}
    ${rv.msg ? `<p class="msg err rv-msg">${esc(rv.msg)}</p>` : ''}
    <p class="hint rv-foot">결과표는 <b>이 모델과 같은 요소 번호</b>여야 합니다. 검토 기준값은 ⚙ 설정.</p>
  </div>`;
  if (setPart('#dTop', html)) {
    document.querySelectorAll('#dTop [data-act=rv-pick]').forEach((b) =>
      b.addEventListener('click', async () => {
        b.disabled = true;
        const items = await api.reviewPick(b.dataset.want);
        b.disabled = false;
        takeItems(items);
      }),
    );
  }
  setPart('#dFb', '');
}

// ---- 구조 검토 영역: 구조 검토 작업(kind 's4', 모델 MGT)에서 MIDAS 해석 결과표 넣기 → 검토 → 엑셀, 승인 → 수정 MGT.
//      골조 모델링 작업 화면에는 두지 않는다(구조 검토는 수작업 뒤 [+ 구조 검토] 로 따로 시작). 1.5.x 에서 도면 작업으로 검토했던 결과만 내려받을 수 있게 남김.
//      넣은 파일이 결과표가 아니면(모델·해석 기록·다른 모델의 표) 검토 실패로 남기지 않고 결과표 칸에 이유를 적어 다시 넣기를 기다린다(1.8.0).
const KIND_KO = { col: '기둥', girder: '거더', beam: '보' };
function renderStage4(j) {
  let s = j.stage4;
  const s4k = j.kind === 's4';
  if (!s4k && !(s && s.state === 'done' && s.summary)) return '';
  let note = s4k ? j.tableNote || null : null;
  if (s4k && s && s.state === 'failed' && s.failKind === 'input') {
    note = { name: s.resultName, text: String(s.failReason || '').replace(/^(입력|설정) 오류:\s*/, '') }; // 1.7.x 에서 남은 "검토 실패" 기록
    s = null;
  }
  const slots = () => slotsHtml({ model: { name: j.name, mtime: j.srcMtime }, table: null, note, hint: '결과표를 넣으면 바로 검토합니다. 이 창에 끌어 놓아도 됩니다.' });
  let body = '';
  if (s4k && !j.elements) {
    body = `<p class="hint">모델 요소표가 없어 검토할 수 없습니다. 위의 [+ 구조 검토] 로 모델을 다시 선택해 주세요.</p>`;
  } else if (s && s.state === 'running') {
    const pct = Math.min(95, Math.round(((s.stepIdx || 0) / (s.total || 4)) * 100));
    body = `<div class="d-status running">${esc(s.step || '검토 중')} · ${fmtSec(Date.now() - s.started)}</div><div class="bar"><i style="width:${pct}%"></i></div><pre class="d-tail">${esc((s.tail || []).slice(-4).join('\n'))}</pre>`;
  } else if (s && s.state === 'failed') {
    body = `<div class="fail error"><b>프로그램 오류</b> ${esc(s.failReason || '')}
      <div class="hint">${esc(s.errorReport ? s.errorReport.message : '결과표를 포함한 오류 보고를 자동으로 보냅니다. 형식을 맞춘 업데이트가 나오면 자동 설치됩니다.')}</div></div>${slots()}`;
  } else if (s && s.state === 'done' && s.summary) {
    const m = s.summary;
    const kinds = Object.entries(m.by_kind || {}).map(([k, v]) => `${KIND_KO[k] || k} OK ${v.ok}·NG ${v.ng}${v.dims ? `(치수 ${v.dims})` : ''}`).join(' / ');
    body = `${note ? `<p class="msg err s4-note"><b>${esc(note.name || '넣은 파일')}</b> — ${esc(note.text)} 아래는 앞서 검토한 결과입니다.</p>` : ''}
      <div class="chips"><span class="chip2">검토 ${m.total}</span><span class="chip2 ok">OK ${m.ok}</span><span class="chip2 ${m.ng ? 'ng' : ''}">NG ${m.ng}</span>${m.none ? `<span class="chip2 warn">결과 없음 ${m.none}</span>` : ''}${m.dims_changed ? `<span class="chip2 warn">치수 변경 추천 ${m.dims_changed}</span>` : ''}</div>
      <p class="hint">${esc(kinds)} · 결과표 ${esc(s.resultName || '')} · 하중 ${m.loads}종 ${m.rows}행${m.unknown ? ` · 대응표에 없는 요소 ${m.unknown}개 무시` : ''} · ${esc(fmtDate(s.ended))}</p>
      <div class="row gap"><button class="btn" data-act="s4-xlsx">⬇ 검토 결과 엑셀</button>
      ${m.ng && m.dims_changed ? (s.mgt2 ? `<button class="btn" data-act="s4-mgt2">⬇ 수정 MGT (승인됨)</button>${s4k ? `<button class="btn ghost small" data-act="s4-apply">다시 생성</button>` : ''}` : s4k ? `<button class="btn" data-act="s4-apply">✔ 승인 → 수정 MGT 생성</button>` : '') : ''}
      ${s4k && j.elements ? `<button class="btn ghost small" data-act="rv-pick" data-want="table">다른 파일로 검토</button>` : ''}</div>
      <p class="hint">${m.ng === 0 ? '모든 부재 OK — MGT 수정이 필요 없습니다.' : m.dims_changed ? '승인하면 치수가 바뀐 부재만 새 단면(C2·G2·B2…)으로 바꾼 MGT 를 만듭니다. 철근은 MGT 에 쓰지 않으며 엑셀의 추천 철근을 참고하십시오.' : 'NG 부재는 철근 보강만으로 해결됩니다(엑셀 추천 철근 참조) — 단면 치수 변경이 없어 MGT 수정은 필요 없습니다.'}${s.applied ? ` 수정 MGT: 요소 ${s.applied.changed}개 단면 교체, 새 단면 ${(s.applied.new_sections || []).map((x) => `${x.name} ${x.H}×${x.B}`).join(', ')}` : ''}</p>`;
  } else {
    body = `${slots()}<p class="hint rv-foot">결과표는 <b>이 모델과 같은 요소 번호</b>여야 합니다. 모델을 고쳤다면 모델과 결과표를 함께 다시 넣어 주세요. 검토 기준값은 ⚙ 설정${note && note.settings ? ' — 안내대로 설정을 고친 뒤 결과표를 다시 넣어 주세요' : ''}.</p>`;
  }
  if (!s4k) return `<section class="s4"><h3>구조 검토 <span class="chip">이전 검토 결과</span></h3>${body}<span class="s4-msg msg"></span></section>`;
  return `<section class="s4"><h3>구조 검토 <span class="chip">MIDAS 해석 결과 → KDS 14 20</span></h3>${body}<span class="s4-msg msg"></span></section>`;
}

// ---- 업데이트: 버튼 줄 위 설치 줄(왼쪽 끝 = 다음 버전, 오른쪽 끝 = [설치]) · 설치 후 처음 한 번 뜨는 업데이트 내용 팝업 · 설정의 [업데이트 내역]
const ub = $('#updateBar');
let lastUpd = null;
$('#ubInstall').addEventListener('click', () => api.updateInstall());
function renderUpdate(s) {
  if (!s) return;
  lastUpd = s;
  const err = s.state === 'error' && !s.next;
  ub.classList.toggle('hidden', !(s.next || err));
  ub.classList.toggle('bad', s.state === 'error');
  $('#ubVer').textContent = s.next ? `새 버전 v${s.next}` : '';
  let msg = '';
  if (s.state === 'downloading') msg = `내려받는 중${s.progress ? ` (${Math.round(s.progress * 100)}%)` : ''}`;
  else if (s.state === 'installing') msg = '설치 중 — 잠시 후 다시 실행됩니다';
  else if (s.state === 'error' || /작업이 끝나면|개발 실행/.test(s.message || '')) msg = s.message || '';
  $('#ubMsg').textContent = msg;
  $('#ubMsg').title = msg;
  // [설치] 는 새 프로그램(설치본)이 있을 때만. 다 내려받기 전과 설치 중에는 누를 수 없다
  $('#ubInstall').classList.toggle('hidden', !s.shell);
  $('#ubInstall').disabled = !s.canInstall || s.state === 'installing';
  $('#updMsg').textContent = s.message || '';
  $('#updMsg').className = 'msg ' + (s.state === 'error' ? 'err' : s.state === 'uptodate' || s.state === 'updated' ? 'ok' : '');
  if (s.current) $('#verChip').textContent = `v${s.current.app}`;
  if (s.whatsNew && !nm) openNews(s.whatsNew);
}

/** 업데이트 내용 팝업·업데이트 내역 창. nm = { mode: 'news', entry } | { mode: 'history', list, open: Set } | null */
let nm = null;
const noteItems = (n) => `<ul>${(n.items || []).map((i) => `<li>${esc(i)}</li>`).join('')}</ul>`;
function openNews(entry) {
  nm = { mode: 'news', entry };
  $('#nmBox').classList.remove('wide');
  $('#nmTitle').textContent = '업데이트 내용';
  $('#nmVer').textContent = `v${entry.version}`;
  $('#nmVer').classList.remove('hidden');
  $('#nmSub').textContent = entry.date || '';
  $('#nmBody').className = 'nm-body';
  $('#nmBody').innerHTML = noteItems(entry);
  $('#nmFoot').textContent = '지난 버전의 내용은 설정(⚙)의 [업데이트 내역] 에서 볼 수 있습니다.';
  $('#nmFoot').classList.remove('hidden');
  $('#notesModal').classList.remove('hidden');
  $('#nmClose').focus();
}
function renderHistory() {
  const cur = lastUpd && lastUpd.current ? String(lastUpd.current.app) : '';
  $('#nmBody').innerHTML = nm.list.length
    ? nm.list
        .map((n) => {
          const on = nm.open.has(n.version);
          return `<div class="nm-row"><button class="nm-rh" data-ver="${esc(n.version)}" aria-expanded="${on}"><span class="tw">${on ? '▾' : '▸'}</span><b>v${esc(n.version)}</b><span class="nm-sub">${esc(n.date || '')}</span>${String(n.version) === cur ? '<span class="cur">현재 버전</span>' : ''}<span class="nav-sp"></span><span class="n">${(n.items || []).length}건</span></button>${on ? `<div class="nm-rb">${noteItems(n)}</div>` : ''}</div>`;
        })
        .join('')
    : '<p class="hint" style="padding:14px 18px">업데이트 내역이 없습니다.</p>';
}
async function openHistory() {
  const list = (await api.updateHistory()) || [];
  nm = { mode: 'history', list, open: new Set(list.length ? [list[0].version] : []) };
  $('#nmBox').classList.add('wide');
  $('#nmTitle').textContent = '업데이트 내역';
  $('#nmVer').classList.add('hidden');
  $('#nmSub').textContent = '버전을 누르면 내용이 펼쳐집니다';
  $('#nmBody').className = 'nm-body list';
  $('#nmFoot').classList.add('hidden');
  renderHistory();
  $('#notesModal').classList.remove('hidden');
  $('#nmClose').focus();
}
async function closeNotes() {
  const was = nm;
  nm = null;
  $('#notesModal').classList.add('hidden');
  if (was && was.mode === 'news') await api.newsSeen(was.entry.version); // [✕] 로 닫으면 이 버전은 다시 띄우지 않는다
  else if (lastUpd && lastUpd.whatsNew) openNews(lastUpd.whatsNew); // 내역을 보는 동안 미뤄 둔 업데이트 내용
}
$('#nmClose').addEventListener('click', closeNotes);
$('#nmBody').addEventListener('click', (e) => {
  const b = e.target.closest('.nm-rh');
  if (!b || !nm || nm.mode !== 'history') return;
  const v = b.dataset.ver;
  if (nm.open.has(v)) nm.open.delete(v);
  else nm.open.add(v);
  const top = $('#nmBody').scrollTop;
  renderHistory();
  $('#nmBody').scrollTop = top;
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && nm && nm.mode === 'history') closeNotes(); // 업데이트 내용 팝업은 [✕] 로만 닫는다
});
$('#btnHistory').addEventListener('click', openHistory);
api.on('update-status', renderUpdate);
api.updateStatus().then(renderUpdate);

render();
