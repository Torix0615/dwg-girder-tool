"""기존 완성본(2번·3번) vs 자동 생성 결과 비교 HTML.
층별로 [참조 | 내 결과] 나란히 + 겹침 차이(참조만/내것만 강조) + 정확도 표.
python compare_html.py out/비교_기존완성본_vs_자동생성.html
"""
import sys, io, base64, pickle, re, time
import numpy as np
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt; plt.rcParams["font.family"] = "Malgun Gothic"
from matplotlib.collections import LineCollection
from scipy.spatial import cKDTree
import ezdxf
from geom import to_segments, sample_points, norm_segs, bulge_points, arc_points

out_html = sys.argv[1]
t0 = time.time()
C = pickle.load(open("out/s1_cand.pkl", "rb")); cand, FY, H = C["cand"], C["FY"], C["H"]
cmp1 = pickle.load(open("out/s1_cand_cmp.pkl", "rb"))
d2 = pickle.load(open("out/d2.pkl", "rb"))
M = pickle.load(open("out/s2_model.pkl", "rb")); model = M["model"]
ref2 = pickle.load(open("out/s2_ref.pkl", "rb"))
res2 = pickle.load(open("out/s2_result.pkl", "rb"))["result"]
doc = ezdxf.readfile("out/최종.dxf")
print(f"loaded {time.time()-t0:.0f}s", flush=True)
REF_NAME = {1: "지1", 2: "지2", 3: "지하3", 4: "지하4", 5: "지하 5", 6: "지하 6"}
L_G, L_B = "GIRDER", "BEAM"


def blk_lines(blk, layers):
    segs = {ly: [] for ly in layers}
    for e in blk:
        ly = e.dxf.layer
        if ly not in segs:
            continue
        if e.dxftype() == "LINE":
            segs[ly].append([e.dxf.start.x, e.dxf.start.y, e.dxf.end.x, e.dxf.end.y])
    return {k: (np.array(v) if v else np.zeros((0, 4))) for k, v in segs.items()}


def split_match(A, B, tol=1.5, cover_tol=15.0, step=20.0, by_cover=False):
    """A 의 선분을 B 와 일치/불일치로 분리"""
    if len(A) == 0:
        return A, A
    if len(B) == 0:
        return np.zeros((0, 4)), A
    if not by_cover:
        d, _ = cKDTree(norm_segs(B)).query(norm_segs(A), distance_upper_bound=tol)
        ok = np.isfinite(d)
        return A[ok], A[~ok]
    t = cKDTree(sample_points(B, step)); ok = np.zeros(len(A), bool)
    for i, s in enumerate(A):
        p = sample_points(s[None, :], step); d, _ = t.query(p, distance_upper_bound=cover_tol)
        ok[i] = np.isfinite(d).mean() >= 0.5
    return A[ok], A[~ok]


def render(layers, bbox, width_px=4200):
    """layers: [(segs, color, lw)]"""
    x0, y0, x1, y1 = bbox
    pad = 0.01 * max(x1 - x0, y1 - y0); x0 -= pad; x1 += pad; y0 -= pad; y1 += pad
    dpi = 100
    fig = plt.figure(figsize=(width_px / dpi, width_px * (y1 - y0) / (x1 - x0) / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    for S, c, lw in layers:
        if len(S):
            ax.add_collection(LineCollection(S.reshape(-1, 2, 2), colors=c, linewidths=lw))
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect("equal"); ax.axis("off")
    buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=dpi, facecolor="white"); plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def bbox_of(*arrs):
    xs = np.concatenate([a[:, [0, 2]].ravel() for a in arrs if len(a)]); ys = np.concatenate([a[:, [1, 3]].ravel() for a in arrs if len(a)])
    return xs.min(), ys.min(), xs.max(), ys.max()


sections1 = []
for n in range(1, 7):
    ref = d2["blocks"][REF_NAME[n]]
    off = np.array([cmp1[n]["dx"], cmp1[n]["dy"]] * 2)
    r_golf = to_segments([p for p in ref if p["layer"] == "----- (구조) 골조"]) + off
    r_cen = to_segments([p for p in ref if re.search(r"^CEN", p["layer"])]) + off
    r_open = to_segments([p for p in ref if p["layer"] == "OPEN"]) + off
    c = cand[n]
    m_golf = to_segments([p for p in c["golf"] if p["layer"] in ("CON", "COL")])
    m_cen = to_segments([p for p in c["cen"] if p["layer"] in ("CEN", "CEN-1", "CEN-PARK")])
    m_open = to_segments(c["open"])
    bb = bbox_of(m_golf)
    img_ref = render([(r_cen, "#c00000", 0.6), (r_open, "#303030", 0.9), (r_golf, "#8a6d00", 1.3)], bb)
    img_my = render([(m_cen, "#c00000", 0.6), (m_open, "#303030", 0.9), (m_golf, "#8a6d00", 1.3)], bb)
    rg_ok, rg_no = split_match(r_golf, m_golf); mg_ok, mg_no = split_match(m_golf, r_golf)
    rc_ok, rc_no = split_match(r_cen, m_cen); mc_ok, mc_no = split_match(m_cen, r_cen)
    ro_ok, ro_no = split_match(r_open, m_open); mo_ok, mo_no = split_match(m_open, r_open)
    img_diff = render([(rg_ok, "#d9c89a", 0.8), (rc_ok, "#f0b0b0", 0.4), (ro_ok, "#bbbbbb", 0.6),
                       (rg_no, "#00a000", 2.2), (rc_no, "#00a000", 1.6), (ro_no, "#00a000", 1.6),
                       (mg_no, "#ff0000", 2.2), (mc_no, "#ff0000", 1.6), (mo_no, "#ff0000", 1.6)], bb)
    t = cmp1[n]
    sections1.append({"name": f"B{n}", "ref": img_ref, "my": img_my, "diff": img_diff,
                      "stats": {"골조": t["golf"], "중심선": t["cen"], "OPEN": t["open"]},
                      "counts": f"참조만(미재현) 골조 {len(rg_no)}·중심선 {len(rc_no)}·OPEN {len(ro_no)} / 내것만(초과) 골조 {len(mg_no)}·중심선 {len(mc_no)}·OPEN {len(mo_no)}"})
    print(f"1단계 B{n} {time.time()-t0:.0f}s", flush=True)

sections2 = []
for N in (0, 1, 2, 3, 4, 5):
    r = ref2[N]; R = res2[N]; k = R["support"]; sh = R["shift"]
    con = model[k]["con"] + np.array([0, sh, 0, sh])
    cols = np.vstack([np.array([[c["poly"][i][0], c["poly"][i][1] + sh, c["poly"][(i + 1) % 4][0], c["poly"][(i + 1) % 4][1] + sh] for i in range(4)]) for c in model[k]["cols"]])
    bname = f"B{N}_골조" if N else "1F_골조"
    mine = blk_lines(doc.blocks[bname], [L_G, L_B])
    mg, mb = mine[L_G], mine[L_B]
    if N == 0:  # 1F 블록은 B1 띠 위(+H) 에 그려짐 → 참조 좌표(B1 띠)로 내림
        mg = mg - np.array([0, H, 0, H]); mb = mb - np.array([0, H, 0, H])
    bb = bbox_of(r["girder_lines"], mg, con)
    bg = [(con, "#c8c8c8", 0.35), (cols, "#555555", 0.8)]
    img_ref = render(bg + [(r["beam_lines"], "#0060e0", 1.1), (r["girder_lines"], "#107010", 1.4)], bb)
    img_my = render(bg + [(mb, "#0060e0", 1.1), (mg, "#107010", 1.4)], bb)
    rg_ok, rg_no = split_match(r["girder_cl"], R["G"], by_cover=True, cover_tol=100, step=50)
    mg_ok, mg_no = split_match(R["G"], r["girder_cl"], by_cover=True, cover_tol=100, step=50)
    rb_ok, rb_no = split_match(r["beam_cl"], R["B"], by_cover=True, cover_tol=100, step=50)
    mb_ok, mb_no = split_match(R["B"], r["beam_cl"], by_cover=True, cover_tol=100, step=50)
    img_diff = render(bg + [(rg_ok, "#a8d8a8", 1.6), (rb_ok, "#b0c8f0", 1.2),
                            (rg_no, "#00a000", 2.4), (rb_no, "#0040ff", 1.8), (mg_no, "#ff0000", 2.4), (mb_no, "#ff8800", 1.8)], bb)
    sections2.append({"name": f"B{N}" if N else "1F", "ref": img_ref, "my": img_my, "diff": img_diff,
                      "stats": {"거더": R["mg"], "보": R["mb"]},
                      "counts": f"지지층 B{k} 기둥 기준 · 참조만(미재현) 거더 {len(rg_no)}·보 {len(rb_no)} / 내것만(초과) 거더 {len(mg_no)}·보 {len(mb_no)} (중심선 기준)"})
    print(f"2단계 {sections2[-1]['name']} {time.time()-t0:.0f}s", flush=True)

CSS = """
*{box-sizing:border-box} body{margin:0;font-family:'Malgun Gothic',sans-serif;background:#f3f4f6;color:#222}
header{position:sticky;top:0;background:#1f2937;color:#fff;padding:10px 16px;z-index:5;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
header h1{font-size:17px;margin:0 10px 0 0} header a{color:#fff;text-decoration:none;background:#374151;padding:4px 9px;border-radius:4px;font-size:13px} header a:hover{background:#4b5563}
.sep{width:1px;height:20px;background:#6b7280;margin:0 4px}
main{padding:12px 16px} h2.stage{font-size:18px;margin:18px 0 8px;border-left:5px solid #1f2937;padding-left:8px}
table{border-collapse:collapse;background:#fff;font-size:13px;margin-bottom:10px} th,td{border:1px solid #d1d5db;padding:4px 10px;text-align:right} th{background:#e5e7eb} td:first-child,th:first-child{text-align:left}
section{background:#fff;border:1px solid #d1d5db;border-radius:6px;padding:10px 12px;margin:10px 0}
section h3{margin:0 0 4px;font-size:16px} .meta{font-size:12px;color:#555;margin-bottom:6px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px} .cell{border:1px solid #e5e7eb} .cell .cap{font-size:13px;font-weight:bold;padding:4px 8px;background:#f9fafb;border-bottom:1px solid #e5e7eb}
.wrap{overflow:auto;max-height:80vh;cursor:zoom-in} .wrap img{display:block;width:100%;height:auto} .wrap.zoom{cursor:zoom-out} .wrap.zoom img{width:auto;max-width:none}
.diff{margin-top:10px} .legend{font-size:12px;color:#444;display:flex;gap:12px;flex-wrap:wrap;margin:4px 0} .legend i{display:inline-block;width:16px;height:3px;margin-right:4px;vertical-align:middle}
.note{font-size:12px;color:#666;padding:10px 0 30px}
"""
JS = "document.querySelectorAll('.wrap').forEach(w=>w.addEventListener('click',()=>w.classList.toggle('zoom')));"


def stat_row(name, st, keys):
    return f"<tr><td>{name}</td>" + "".join(f"<td>{st[k]['len_recall']:.1f}</td><td>{st[k]['len_prec']:.1f}</td><td><b>{st[k]['f1']:.1f}</b></td>" for k in keys) + "</tr>"


def table(secs, keys, note):
    head = "<tr><th rowspan=2>층</th>" + "".join(f"<th colspan=3>{k}</th>" for k in keys) + "</tr><tr>" + "".join("<th>재현</th><th>정밀</th><th>F1</th>" for _ in keys) + "</tr>"
    rows = "".join(stat_row(s["name"], s["stats"], keys) for s in secs)
    avg = {k: {m: np.mean([s["stats"][k][m] for s in secs]) for m in ("len_recall", "len_prec", "f1")} for k in keys}
    rows += stat_row("평균", avg, keys)
    return f'<div class="meta">{note}</div><table>{head}{rows}</table>'


def section(prefix, s, leg_diff):
    sid = f"{prefix}-{s['name']}"
    return (f'<section id="{sid}"><h3>{s["name"]}</h3><div class="meta">' +
            " · ".join(f"{k}: 재현 {v['len_recall']:.1f}% / 정밀 {v['len_prec']:.1f}% / F1 {v['f1']:.1f}%" for k, v in s["stats"].items()) +
            f'<br>{s["counts"]}</div><div class="grid">'
            f'<div class="cell"><div class="cap">기존 완성본(참조)</div><div class="wrap"><img src="data:image/png;base64,{s["ref"]}"></div></div>'
            f'<div class="cell"><div class="cap">자동 생성(내 결과)</div><div class="wrap"><img src="data:image/png;base64,{s["my"]}"></div></div></div>'
            f'<div class="cell diff"><div class="cap">겹침 차이</div><div class="legend">{leg_diff}</div><div class="wrap"><img src="data:image/png;base64,{s["diff"]}"></div></div></section>')


leg1 = '<span><i style="background:#00a000"></i>참조에만 있음(미재현)</span><span><i style="background:#ff0000"></i>내 결과에만 있음(초과)</span><span><i style="background:#d9c89a"></i>일치(연한색)</span>'
leg2 = '<span><i style="background:#00a000"></i>참조에만 있는 거더</span><span><i style="background:#0040ff"></i>참조에만 있는 보</span><span><i style="background:#ff0000"></i>내게만 있는 거더</span><span><i style="background:#ff8800"></i>내게만 있는 보</span><span><i style="background:#a8d8a8"></i>일치 거더</span><span><i style="background:#b0c8f0"></i>일치 보</span><span><i style="background:#555555"></i>지지층 기둥·벽</span>'
nav = '<a href="#stage1">1단계</a>' + "".join(f'<a href="#s1-{s["name"]}">{s["name"]}</a>' for s in sections1) + '<span class="sep"></span><a href="#stage2">2단계</a>' + "".join(f'<a href="#s2-{s["name"]}">{s["name"]}</a>' for s in sections2)
html = (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>기존 완성본 vs 자동 생성 비교</title><style>{CSS}</style></head><body>'
        f'<header><h1>기존 완성본 vs 자동 생성 비교</h1>{nav}</header><main>'
        f'<h2 class="stage" id="stage1">1단계 골조 추출 — 참조: 2번 파일(결합(back).dwg) 층별 블록</h2>'
        + table(sections1, ["골조", "중심선", "OPEN"], "길이 기준 %(허용 15mm). 재현=참조 중 내 결과에 있는 비율, 정밀=내 결과 중 참조에 있는 비율, F1=조화평균. 겹침 차이는 선분 단위 정확 일치(1.5mm) 기준.")
        + "".join(section("s1", s, leg1) for s in sections1)
        + f'<h2 class="stage" id="stage2">2단계 거더·보 — 참조: 3번 파일(S-711 구조평면도) 열별 Girder/Beam</h2>'
        + table(sections2, ["거더", "보"], "중심선 길이 기준 %(허용 100mm). 참조 2중선은 중심선으로 변환해 비교. N층 도면은 아래층(N+1) 기둥 기준, 1F는 B1 기둥 기준, B6 도면은 참조에 거더 없음.")
        + "".join(section("s2", s, leg2) for s in sections2)
        + '</main><div class="note">이미지를 클릭하면 원본 크기(4200px)로 전환되어 스크롤로 세부 확인. 2026-10-27 생성, Tools\\DwgRework\\compare_html.py</div>'
        f'<script>{JS}</script></body></html>')
open(out_html, "w", encoding="utf-8").write(html)
import os
print(f"wrote {out_html} {os.path.getsize(out_html)/1e6:.1f} MB  {time.time()-t0:.0f}s")
