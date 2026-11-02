'use strict';
/**
 * 피드백 자동 분류(키워드): 도면 생성 규칙·결과(rule) 인지, 프로그램 화면·기능(ui: 버튼 위치·레이아웃·기능 추가) 인지.
 * 렌더러(<script>)와 메인 프로세스(require) 양쪽에서 쓰는 UMD. 같은 규칙이 dist_build/pull_feedback.py 에도 있음(두 곳 동시 수정).
 * 최종 판정은 개발 PC 에서 내용을 읽고 하므로 여기서는 힌트·표시용.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.classifyFeedback = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  const UI_STRONG = ['버튼', '레이아웃', '화면', '메뉴', '탭', '패널', '글꼴', '폰트', '글자', '글씨', '색상', '색깔', '테마', '다크', '단축키', '트레이', '아이콘', 'UI', '디자인', '프로그램', '앱 ', '앱이', '앱을', '앱에', '입력창', '입력란', '스크롤', '진행률', '사용성', '불편', '창이', '창을', '창 ', '카드', '사이드바', '목록에서', '마우스', '키보드'];
  const UI_WEAK = ['위치', '배치', '이동', '옮기', '옮겨', '크기', '목록', '정렬', '기능', '표시', '설정', '옵션', '클릭', '드래그', '저장', '다운로드', '열기', '닫기', '보이게', '숨기', '순서', '알림', '업데이트'];
  const RULE_STRONG = ['거더', 'GIRDER', 'BEAM', '기둥', 'COLUMN', '도곽', '레이어', 'LAYER', '중심선', '벽', '층', 'MGT', 'MIDAS', 'DXF', 'DWG', '도면', '블록', '폴리선', '선종류', 'OPEN', 'XREF', '참조', '간섭', '분할', '단면', '치수', '절점', '요소', '규칙', '추출', '인식', '노랑', '빨강', '경고', '비지지', '지지', 'EXPLODE', '베이', '램프', '옥탑', '지하'];

  function hits(text, words) {
    const t = String(text || '');
    const up = t.toUpperCase();
    return words.filter((w) => (/^[A-Za-z ]+$/.test(w) ? up.includes(w.toUpperCase()) : t.includes(w)));
  }

  /** @returns {{category:'ui'|'rule'|'unknown', ui:string[], rule:string[], score:{ui:number, rule:number}}} */
  function classifyFeedback(text) {
    const us = hits(text, UI_STRONG);
    const uw = hits(text, UI_WEAK);
    const rs = hits(text, RULE_STRONG);
    const ui = us.length * 2 + uw.length;
    const rule = rs.length * 2;
    let category = 'unknown';
    if (ui >= 2 && ui > rule) category = 'ui';
    else if (rule > 0) category = 'rule';
    else if (ui > 0) category = 'ui';
    return { category, ui: [...us, ...uw], rule: rs, score: { ui, rule } };
  }
  classifyFeedback.LABEL = { ui: '프로그램 화면·기능', rule: '생성 규칙·결과', unknown: '모름' };
  return classifyFeedback;
});
