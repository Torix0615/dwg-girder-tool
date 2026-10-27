"""A31 비교: 내 1단계 후보(s1.pkl) vs 참조 구조도(251215, d_ref_full.pkl) 시트 행.
python compare_a31.py data/a31/s1.pkl data/a31/d_ref_full.pkl [--report f] [--variants]
참조 시트 = x 126150 간격 16장(B5..옥탑지붕), 시트 행 y 895k~1000k. 참조 골조 = ##CON-상부(노랑), 중심선 = A-ST-AXIS-CEN-WALL, OPEN = A-FLOR-OPEN-BELO.
"""
import sys, re, pickle, argparse, collections
import numpy as np
from geom import to_segments, match_metrics, find_offset, norm_segs

ap = argparse.ArgumentParser()
ap.add_argument("cand"); ap.add_argument("ref")
ap.add_argument("--report"); ap.add_argument("--variants", action="store_true")
ap.add_argument("--y0", type=float, default=895000); ap.add_argument("--y1", type=float, default=1000000)
ap.add_argument("--sheet", type=float, default=126150)
a = ap.parse_args()

C = pickle.load(open(a.cand, "rb")); cand, floors = C["cand"], C["floors"]
R = pickle.load(open(a.ref, "rb"))["msp"]
SHEET_FLOOR = {0: -5, 1: -4, 2: -3, 3: -2, 4: -1, 5: 1, 6: 2, 7: 3, 8: 4, 9: 0, 10: 5, 11: 15, 12: 16, 13: 17, 14: 100, 15: 101}


def rep(p):
    k = p["kind"]
    if k == "LINE": return p["x1"], p["y1"]
    if k == "POLY": return p["pts"][0][0], p["pts"][0][1]
    if k in ("ARC", "CIRCLE"): return p["cx"], p["cy"]
    return p.get("x", 0), p.get("y", 0)


ref_by = collections.defaultdict(lambda: collections.defaultdict(list))
for p in R:
    x, y = rep(p)
    if not (a.y0 <= y <= a.y1):
        continue
    s = int(x // a.sheet)
    if s not in SHEET_FLOOR:
        continue
    ref_by[SHEET_FLOOR[s]][p["layer"]].append(p)

lines = []
def out(s=""):
    print(s); lines.append(s)
def fmt(m):
    return (f"참조 {m['ref_n']:5d}개/{m['ref_len']/1000:7.0f}m  내것 {m['my_n']:5d}개/{m['my_len']/1000:7.0f}m  "
            f"선분재현 {m['seg_recall']:5.1f}% 정밀 {m['seg_prec']:5.1f}%  길이재현 {m['len_recall']:5.1f}% 정밀 {m['len_prec']:5.1f}%  F1 {m['f1']:5.1f}%")

short = {f["id"]: f["short"] for f in floors}
tot = {}
for fid in sorted(cand):
    if fid not in ref_by:
        out(f"===== {short.get(fid, fid)}: 참조 시트 없음"); continue
    rb = ref_by[fid]
    ref_golf = to_segments(rb.get("##CON-상부", []))
    ref_low = to_segments(rb.get("##con-하부", []))
    ref_cen = to_segments([p for ly, v in rb.items() if re.search(r"AXIS-CEN|^CEN", ly) for p in v])
    ref_open = to_segments(rb.get("A-FLOR-OPEN-BELO", []))
    my_golf = to_segments(cand[fid]["golf"]); my_cen = to_segments(cand[fid]["cen"]); my_open = to_segments(cand[fid]["open"])
    if len(ref_golf) == 0 or len(my_golf) == 0:
        out(f"===== {short.get(fid, fid)}: 참조 골조 {len(ref_golf)} 내 골조 {len(my_golf)} — 비교 생략"); continue
    dx, dy, nx, ny = find_offset(ref_golf, my_golf)
    off = np.array([dx, dy, dx, dy])
    out(f"===== {short.get(fid, fid):7} 정렬 dx={dx:.0f} dy={dy:.0f} (표 {nx},{ny})  참조 레이어 {dict((k, len(v)) for k, v in rb.items() if len(v) > 3)}")
    mg = match_metrics(ref_golf + off, my_golf); out("  골조(상부) " + fmt(mg))
    if len(ref_low):
        ml = match_metrics(ref_low + off, my_golf); out("  골조(하부) " + fmt(ml))
    if a.variants:
        for ly in sorted({p["layer"] for p in cand[fid]["golf"]}):
            segs = to_segments([p for p in cand[fid]["golf"] if p["layer"] == ly])
            if len(segs) == 0: continue
            m = match_metrics(ref_golf + off, segs)
            out(f"     레이어 {ly:22s} 내것 {m['my_n']:5d}개  참조에 있는 비율 {m['seg_prec']:5.1f}% (길이 {m['len_prec']:5.1f}%)")
    mc = match_metrics(ref_cen + off, my_cen) if len(ref_cen) and len(my_cen) else None
    if mc: out("  중심선     " + fmt(mc))
    mo = match_metrics(ref_open + off, my_open) if len(ref_open) and len(my_open) else None
    if mo: out("  OPEN       " + fmt(mo))
    else: out(f"  OPEN       참조 {len(ref_open)} 내것 {len(my_open)}")
    tot[fid] = {"golf": mg, "cen": mc, "open": mo}

out("===== 요약(F1 %)  층  골조  중심선  OPEN")
for fid in sorted(tot):
    t = tot[fid]
    out(f"{short.get(fid, fid):7} {t['golf']['f1']:5.1f}  {t['cen']['f1'] if t['cen'] else float('nan'):5.1f}  {t['open']['f1'] if t['open'] else float('nan'):5.1f}")
if a.report:
    open(a.report, "w", encoding="utf-8").write("\n".join(lines))
