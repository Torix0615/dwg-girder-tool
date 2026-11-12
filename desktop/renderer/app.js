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

// ---- 확인 팝업([취소] [확인])
let modalDone = null;
function confirmBox(title, body) {
  if (modalDone) modalDone(false);
  return new Promise((resolve) => {
    $('#modalTitle').textContent = title;
    $('#modalBody').textContent = body || '';
    $('#modal').classList.remove('hidden');
    modalDone = (v) => {
      modalDone = null;
      $('#modal').classList.add('hidden');
      resolve(v);
    };
    $('#modalCancel').focus();
  });
}
$('#modalOk').addEventListener('click', () => modalDone && modalDone(true));
$('#modalCancel').addEventListener('click', () => modalDone && modalDone(false));
$('#modal').addEventListener('mousedown', (e) => {
  if (e.target === $('#modal') && modalDone) modalDone(false);
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && modalDone) modalDone(false);
});

// ---- 창 버튼
$('#btnHide').addEventListener('click', () => api.hide());
const btnPin = $('#btnPin');
api.getPinned().then((on) => btnPin.classList.toggle('on', on));
btnPin.addEventListener('click', async () => {
  const on = await api.setPinned(!btnPin.classList.contains('on'));
  btnPin.classList.toggle('on', on);
});

// ---- 화면: jobs(작업 목록 + 작업 결과) / general([피드백]: 작업 없이 보내는 피드백) / log([피드백 로그]) / settings(⚙)
let view = 'jobs';
let state = { jobs: [], running: false };
let selected = null;
const drafts = {}; // jobId → {text, kind} : 작업 결과 화면에서 쓰던 피드백(작업마다 저장 — 다른 곳에 다녀와도 남음)
const progress = {}; // jobId → {progress, message}
const sending = {}; // jobId → true
const fbMsg = {}; // jobId → {text, cls}
const gen = { text: '', kind: 'rule', sending: false, msg: null }; // 작업 없이 보내는 피드백(저장하지 않음 — 다른 곳으로 가면 확인 후 삭제)
let logItems = [];
let logSel = -1;

/** 작업 없이 쓰던 피드백이 있으면 확인 팝업. 취소하면 false */
async function leaveGeneral() {
  if (view !== 'general' || !gen.text.trim()) return true;
  if (!(await confirmBox('작성 중이던 피드백이 삭제됩니다', '다른 화면으로 이동하면 적어 둔 내용이 사라집니다.'))) return false;
  gen.text = '';
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
  if (await setView('jobs')) api.startJob();
});
// 구조 검토: 수작업을 마친 MIDAS 모델(.mgt) 선택 → 모델 읽기 → 오른쪽 화면에서 결과표 첨부(.mgt 를 끌어다 놓아도 같음)
$('#btnS4').addEventListener('click', async () => {
  if (await setView('jobs')) api.startStage4();
});
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

// ---- 설정(골조 모델링 실행 범위 / 보 생성 / 보 간격 기준 / 구조 검토): userData/config.json 에 저장, 다음 작업부터 적용
let settingDefaults = {};
let stageSel = 3;
const STAGE_DESC = { 1: '골조·중심선·OPEN 추출 후 DXF 저장', 2: '거더·보 생성 후 DXF 저장', 3: 'MIDAS GEN MGT 까지 생성 (기본)' };
function setStage(v) {
  stageSel = [1, 2, 3].includes(Number(v)) ? Number(v) : 3;
  for (const b of $('#setStage').querySelectorAll('button')) b.classList.toggle('on', Number(b.dataset.v) === stageSel);
  $('#setStageDesc').textContent = STAGE_DESC[stageSel];
  settingsVisibility();
}
function fillSettings({ values, defaults }) {
  settingDefaults = defaults || {};
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
  setStage(values['실행_단계'] || 3);
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
  $('#setBeamGrp').classList.toggle('hidden', stageSel < 2); // 1단계까지만이면 보 설정은 의미 없음
  $('#beamNums').classList.toggle('hidden', !$('#optBeams').checked); // 보를 끄면 간격 옵션 숨김
  $('#setMgtGrp').classList.toggle('hidden', stageSel < 3); // MGT 를 만들지 않으면 층고 설정 숨김
  // 구조 검토 설정은 항상 표시 — 구조 검토는 골조 모델링과 무관하게 모델 MGT 로 단독 실행
}
function readSettings() {
  const vals = { 실행_단계: stageSel, 보_생성: $('#optBeams').checked };
  for (const inp of numInputs()) if (numOk(inp)) vals[inp.dataset.key] = Number(inp.value);
  for (const inp of textInputs()) if (textOk(inp)) vals[inp.dataset.key] = inp.value.trim();
  return vals;
}
$('#setStage').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-v]');
  if (b) setStage(b.dataset.v);
});
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
  m.textContent = r.rejected && r.rejected.length ? `저장됨 — 일부 값은 범위 밖이라 유지됨 (${r.rejected.join(', ')})` : '저장됨 — 다음 작업(구조 검토는 다음 검토)부터 적용';
  m.className = 'msg ok';
});
$('#setReset').addEventListener('click', async () => {
  if (!(await confirmBox('모든 내용을 기본으로 되돌립니다', '설정의 모든 값이 처음 상태로 바뀝니다.'))) return;
  fillSettings(await api.setSettings({ ...settingDefaults }));
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

// ---- 파일 끌어다 놓기(1개): 도면 = 골조 모델링, .mgt = 구조 검토
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
api.on('engine-state', (st) => {
  const prevIds = new Set(state.jobs.map((j) => j.id));
  state = st;
  const fresh = st.jobs.find((j) => !prevIds.has(j.id));
  if (fresh) {
    selected = fresh.id;
    if (view !== 'jobs' && !(view === 'general' && gen.text.trim())) view = 'jobs'; // 새 작업이 생기면 그 작업 화면으로(작업 없이 쓰던 피드백이 있으면 그대로 둠)
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
  if (state.jobs.length && !state.jobs.some((j) => j.id === selected)) selected = state.jobs[state.jobs.length - 1].id;
  renderList();
  if (view === 'general') renderGeneral();
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
  if (s && s.state === 'failed') return s.failKind === 'input' ? { text: '검토 실패', cls: 'failed' } : { text: '검토 에러', cls: 'failed error' };
  if (s && s.state === 'done' && s.summary) return { text: `검토 완료 · OK ${s.summary.ok} / NG ${s.summary.ng}${fb}`, cls: 'done' };
  return { text: '결과표 첨부 대기', cls: 'done' };
}
const jobTime = (j) => (j.stage4 && j.stage4.ended) || j.ended || j.started || j.created || 0;
function renderList() {
  if (!state.jobs.length) {
    setPart('#jobList', '<li class="none">작업이 없습니다</li>');
    return;
  }
  const html = [...state.jobs]
    .reverse()
    .map((j) => {
      const st = listState(j);
      const ol = j.kind === 's4' ? '' : optsLabel(j.opts);
      return `<li class="jobitem ${st.cls}${view === 'jobs' && j.id === selected ? ' sel' : ''}" data-id="${j.id}"><div class="ji-date">${esc(fmtDate(jobTime(j)) || '-')}</div><div class="ji-name" title="${esc(j.src)}">${esc(j.name)}</div><div class="ji-state" title="${esc(st.text)}">${esc(st.text)}${ol ? `<span class="ji-opts">${esc(ol)}</span>` : ''}</div>${j.state !== 'running' ? '<button class="ji-del" title="목록에서 지우기">✕</button>' : ''}</li>`;
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
    <div class="d-status ${j.state}${errKind ? ' error' : ''}">${esc(status)}${optsLabel(j.opts) ? `<span class="d-opts" title="이 작업에 적용된 설정">${esc(optsLabel(j.opts))}</span>` : ''}</div>
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
    ${j.state === 'done' && !s4k ? `<div class="row gap"><button class="btn" data-act="download">⬇ 결과 DXF</button>${j.mgt ? `<button class="btn" data-act="download-mgt">⬇ MIDAS GEN (MGT)</button>` : ''}<span class="hint">${esc(j.result ? j.result.split(/[\\/]/).pop() : '')}</span></div>` : ''}
    ${j.state === 'done' ? renderStage4(j) : ''}
  </div>`;
}

function renderDetail(j) {
  if (!j) {
    setPart('#dTop', '<p class="hint none-main">작업이 없습니다. 위의 [+ 골조 모델링] 또는 [+ 구조 검토] 로 시작하면 결과가 여기에 표시됩니다. 도면(DWG·DXF)이나 MIDAS 모델(.mgt) 파일을 이 창에 끌어다 놓아도 됩니다.</p>');
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
  // 구조 검토: 결과표 첨부 → 검토 / 엑셀·수정 MGT 다운로드 / 승인
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

// ---- 구조 검토 영역: 구조 검토 작업(kind 's4', 모델 MGT)에서 MIDAS 해석 결과표 첨부 → 검토 → 엑셀, 승인 → 수정 MGT.
//      골조 모델링 작업 화면에는 두지 않는다(구조 검토는 수작업 뒤 [+ 구조 검토] 로 따로 시작). 1.5.x 에서 도면 작업으로 검토했던 결과만 내려받을 수 있게 남김.
const KIND_KO = { col: '기둥', girder: '거더', beam: '보' };
function renderStage4(j) {
  const s = j.stage4;
  const s4k = j.kind === 's4';
  if (!s4k && !(s && s.state === 'done' && s.summary)) return '';
  const canRun = s4k && (!s || s.state !== 'running');
  const pickLabel = s && s.state === 'done' ? '📎 다른 결과표로 다시 검토' : '📎 MIDAS 해석 결과표(텍스트·엑셀) 첨부 → 검토 실행';
  let body = '';
  if (s4k && !j.elements) {
    body = `<p class="hint">모델 요소표가 없어 검토할 수 없습니다. 위의 [+ 구조 검토] 로 모델을 다시 선택해 주세요.</p>`;
  } else if (s && s.state === 'running') {
    const pct = Math.min(95, Math.round(((s.stepIdx || 0) / (s.total || 4)) * 100));
    body = `<div class="d-status running">${esc(s.step || '검토 중')} · ${fmtSec(Date.now() - s.started)}</div><div class="bar"><i style="width:${pct}%"></i></div><pre class="d-tail">${esc((s.tail || []).slice(-4).join('\n'))}</pre>`;
  } else if (s && s.state === 'failed') {
    body = `<div class="fail ${s.failKind === 'input' ? 'input' : 'error'}"><b>${s.failKind === 'input' ? '설정·입력 문제' : '프로그램 오류'}</b> ${esc(s.failReason || '')}
      <div class="hint">${s.failKind === 'input' ? '안내대로 설정(⚙) 또는 첨부 파일을 고친 뒤 다시 검토해 주세요.' : esc(s.errorReport ? s.errorReport.message : '결과표를 포함한 오류 보고를 자동으로 보냅니다. 형식을 맞춘 업데이트가 나오면 자동 설치됩니다.')}</div></div>`;
  } else if (s && s.state === 'done' && s.summary) {
    const m = s.summary;
    const kinds = Object.entries(m.by_kind || {}).map(([k, v]) => `${KIND_KO[k] || k} OK ${v.ok}·NG ${v.ng}${v.dims ? `(치수 ${v.dims})` : ''}`).join(' / ');
    body = `<div class="chips"><span class="chip2">검토 ${m.total}</span><span class="chip2 ok">OK ${m.ok}</span><span class="chip2 ${m.ng ? 'ng' : ''}">NG ${m.ng}</span>${m.none ? `<span class="chip2 warn">결과 없음 ${m.none}</span>` : ''}${m.dims_changed ? `<span class="chip2 warn">치수 변경 추천 ${m.dims_changed}</span>` : ''}</div>
      <p class="hint">${esc(kinds)} · 결과표 ${esc(s.resultName || '')} · 하중 ${m.loads}종 ${m.rows}행${m.unknown ? ` · 대응표에 없는 요소 ${m.unknown}개 무시` : ''} · ${esc(fmtDate(s.ended))}</p>
      <div class="row gap"><button class="btn" data-act="s4-xlsx">⬇ 검토 결과 엑셀</button>
      ${m.ng && m.dims_changed ? (s.mgt2 ? `<button class="btn" data-act="s4-mgt2">⬇ 수정 MGT (승인됨)</button>${s4k ? `<button class="btn ghost small" data-act="s4-apply">다시 생성</button>` : ''}` : s4k ? `<button class="btn" data-act="s4-apply">✔ 승인 → 수정 MGT 생성</button>` : '') : ''}</div>
      <p class="hint">${m.ng === 0 ? '모든 부재 OK — MGT 수정이 필요 없습니다.' : m.dims_changed ? '승인하면 치수가 바뀐 부재만 새 단면(C2·G2·B2…)으로 바꾼 MGT 를 만듭니다. 철근은 MGT 에 쓰지 않으며 엑셀의 추천 철근을 참고하십시오.' : 'NG 부재는 철근 보강만으로 해결됩니다(엑셀 추천 철근 참조) — 단면 치수 변경이 없어 MGT 수정은 필요 없습니다.'}${s.applied ? ` 수정 MGT: 요소 ${s.applied.changed}개 단면 교체, 새 단면 ${(s.applied.new_sections || []).map((x) => `${x.name} ${x.H}×${x.B}`).join(', ')}` : ''}</p>`;
  } else {
    body = `<p class="hint">이 모델을 MIDAS GEN 에서 <b>해석</b>한 뒤 Results → Result Tables → Beam → Force 표를 텍스트(.txt)·CSV·엑셀(.xlsx) 중 하나로 내보내 아래 버튼으로 첨부하면 기둥(축력·PM 상관도·장주)·거더·보(휨·전단)를 KDS 14 20 으로 검토하고 NG 부재는 철근 → 폭 → 춤 순으로 추천합니다. 결과표는 <b>이 모델과 같은 요소 번호</b>여야 하므로, 모델을 고쳤다면 모델도 다시 선택해 주세요. 검토 기준값은 ⚙ 설정.</p>`;
  }
  if (!s4k) return `<section class="s4"><h3>구조 검토 <span class="chip">이전 검토 결과</span></h3>${body}<span class="s4-msg msg"></span></section>`;
  return `<section class="s4"><h3>구조 검토 <span class="chip">MIDAS 해석 결과 → KDS 14 20</span></h3>${body}
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

render();
