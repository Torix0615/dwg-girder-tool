"""A31 2단계 비교: 내 거더·보(s2_result.pkl, 층 좌표) vs 참조 구조도(d_ref_full.pkl)의 MLINE 거더·보 중심선.
python compare2_a31.py data/a31/s1.pkl data/a31/s2_result.pkl data/a31/d_ref_full.pkl [--tol 150] [--report f]
참조: ++GIRDER(거더), ++BEAM·S-BEAM(보), ++WG(벽거더), ++Trans(전이보). 시트 행 y 895k~1000k, 시트 폭 126150.
"""
import sys, re, pickle, argparse, collections
import numpy as np
from geom import to_segments, match_metrics, find_offset

ap = argparse.ArgumentParser()
ap.add_argument("cand"); ap.add_argument("result"); ap.add_argument("ref")
ap.add_argument("--tol", type=float, default=150.0); ap.add_argument("--report")
a = ap.parse_args()
C = pickle.load(open(a.cand, "rb")); cand = C["cand"]
RES = pickle.load(open(a.result, "rb")); result, floors = RES["result"], RES["floors"]
short = {f["id"]: f["short"] for f in floors}
R = pickle.load(open(a.ref, "rb"))["msp"]
SF = {0: -5, 1: -4, 2: -3, 3: -2, 4: -1, 5: 1, 6: 2, 7: 3, 8: 4, 9: 4.5, 10: 5, 11: 15, 12: 16, 13: 17, 14: 100, 15: 101}


def rep(p):
    k = p["kind"]
    if k == "LINE": return p["x1"], p["y1"]
    if k == "POLY": return p["pts"][0][0], p["pts"][0][1]
    if k in ("ARC", "CIRCLE"): return p["cx"], p["cy"]
    return p.get("x", 0), p.get("y", 0)


ref_by = collections.defaultdict(lambda: collections.defaultdict(list))
for p in R:
    x, y = rep(p)
    if 895000 <= y <= 1000000 and int(x // 126150) in SF:
        ref_by[SF[int(x // 126150)]][p["layer"]].append(p)

lines = []
def out(s=""):
    print(s); lines.append(s)
def fmt(m):
    return f"참조 {m['ref_len']/1000:6.0f}m 내것 {m['my_len']/1000:6.0f}m  길이재현 {m['len_recall']:5.1f}% 정밀 {m['len_prec']:5.1f}%  F1 {m['f1']:5.1f}%"

tot = []
for fid in sorted(result):
    if fid not in ref_by or fid not in cand:
        continue
    rb = ref_by[fid]
    ref_golf = to_segments(rb["##CON-상부"]); my_golf = to_segments(cand[fid]["golf"])
    if not len(ref_golf) or not len(my_golf):
        continue
    dx, dy, _, _ = find_offset(ref_golf, my_golf); off = np.array([dx, dy, dx, dy])
    RG = to_segments(rb.get("++GIRDER", []) + rb.get("++WG", []) + rb.get("++Trans", []), with_arcs=False) + off if (rb.get("++GIRDER") or rb.get("++WG") or rb.get("++Trans")) else np.zeros((0, 4))
    RB = to_segments(rb.get("++BEAM", []) + rb.get("S-BEAM", []), with_arcs=False) + off if (rb.get("++BEAM") or rb.get("S-BEAM")) else np.zeros((0, 4))
    G, B = result[fid]["G"], result[fid]["B"]
    out(f"===== {short[fid]:7} 참조 거더 {len(RG)} 보 {len(RB)} | 내 거더 {len(G)} 보 {len(B)}")
    r = {}
    if len(RG) and len(G):
        m = match_metrics(RG, G, cover_tol=a.tol); r["g"] = m; out("  거더       " + fmt(m))
    if len(RB) and len(B):
        m = match_metrics(RB, B, cover_tol=a.tol); r["b"] = m; out("  보         " + fmt(m))
    if len(RG) + len(RB) and len(G) + len(B):
        m = match_metrics(np.vstack([RG, RB]), np.vstack([G, B]), cover_tol=a.tol); r["all"] = m; out("  거더+보    " + fmt(m))
    tot.append((short[fid], r))
out("===== 요약(길이 재현/정밀 %)  층  거더  보  전체F1")
for sh, r in tot:
    g = f"{r['g']['len_recall']:5.1f}/{r['g']['len_prec']:5.1f}" if "g" in r else "   -   "
    b = f"{r['b']['len_recall']:5.1f}/{r['b']['len_prec']:5.1f}" if "b" in r else "   -   "
    out(f"{sh:7} {g}  {b}  {r['all']['f1'] if 'all' in r else float('nan'):5.1f}")
if a.report:
    open(a.report, "w", encoding="utf-8").write("\n".join(lines))
