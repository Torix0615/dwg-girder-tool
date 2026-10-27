"""1단계 비교: 내 후보(s1_cand.pkl) vs 참조 2번 파일 블록(d2.pkl 지1..지하 6) — 층별·범주별 일치율(%).
python compare1.py out/s1_cand.pkl out/d2.pkl [--golf-layers CON,COL] [--cen-layers CEN,CEN-1] [--report out/x.txt]
"""
import sys, re, pickle, argparse
import numpy as np
from geom import to_segments, match_metrics, find_offset

ap = argparse.ArgumentParser()
ap.add_argument("cand"); ap.add_argument("ref")
ap.add_argument("--golf-layers", default="CON,COL")
ap.add_argument("--cen-layers", default="CEN,CEN-1,CEN-PARK")
ap.add_argument("--report")
ap.add_argument("--variants", action="store_true", help="골조 레이어 조합별 점수 비교")
a = ap.parse_args()

C = pickle.load(open(a.cand, "rb")); cand = C["cand"]
R = pickle.load(open(a.ref, "rb"))
REF_NAME = {1: "지1", 2: "지2", 3: "지하3", 4: "지하4", 5: "지하 5", 6: "지하 6"}
REF_B = {1: "지1 b", 2: "지2 b", 3: "wl3 b", 4: "지3 b", 5: "지5 b", 6: "지6 b"}


def by_layers(prims, layers):
    s = set(layers)
    return [p for p in prims if p["layer"] in s]


def fmt(m):
    return (f"참조 {m['ref_n']:5d}개/{m['ref_len']/1000:8.0f}m  내것 {m['my_n']:5d}개/{m['my_len']/1000:8.0f}m  "
            f"선분재현 {m['seg_recall']:5.1f}% 정밀 {m['seg_prec']:5.1f}%  길이재현 {m['len_recall']:5.1f}% 정밀 {m['len_prec']:5.1f}%  F1 {m['f1']:5.1f}%")


lines = []
def out(s=""):
    print(s); lines.append(s)

tot = {}
for n in sorted(cand):
    ref = R["blocks"][REF_NAME[n]]
    ref_golf = to_segments([p for p in ref if p["layer"] == "----- (구조) 골조"])
    ref_cen = to_segments([p for p in ref if re.search(r"^CEN", p["layer"])])
    ref_open = to_segments([p for p in ref if p["layer"] == "OPEN"])
    my_golf = to_segments(by_layers(cand[n]["golf"], a.golf_layers.split(",")))
    dx, dy, nx, ny = find_offset(ref_golf, my_golf)
    out(f"===== B{n}  참조블록 {REF_NAME[n]}  정렬 이동량 dx={dx:.1f} dy={dy:.1f} (표 {nx},{ny})")
    off = np.array([dx, dy, dx, dy])
    ref_golf = ref_golf + off; ref_cen = ref_cen + off; ref_open = ref_open + off
    mg = match_metrics(ref_golf, my_golf); out("  골조   " + fmt(mg))
    if a.variants:
        layers = sorted({p["layer"] for p in cand[n]["golf"]})
        for ly in layers:
            segs = to_segments([p for p in cand[n]["golf"] if p["layer"] == ly])
            if len(segs) == 0: continue
            m = match_metrics(ref_golf, segs)
            out(f"     레이어 {ly:14s} 내것 {m['my_n']:5d}개  이 레이어 선분 중 참조에 있는 비율 {m['seg_prec']:5.1f}% (길이 {m['len_prec']:5.1f}%)")
        # 골조 중 참조에 없는 것: 상위 블록 경로별
        import collections
        from scipy.spatial import cKDTree
        from geom import norm_segs
        prims = by_layers(cand[n]["golf"], a.golf_layers.split(","))
        t = cKDTree(norm_segs(ref_golf))
        miss = collections.Counter(); tot_c = collections.Counter()
        for p in prims:
            s = to_segments([p])
            if len(s) == 0: continue
            d, _ = t.query(norm_segs(s), distance_upper_bound=1.5)
            key = (p["layer"], p["path"][0][:14] if p["path"] else "-", p["kind"])
            tot_c[key] += len(s); miss[key] += int((~np.isfinite(d)).sum())
        out("     참조에 없는 내 골조 선분 (레이어, 최상위 블록, 종류): 미일치/전체")
        for k, v in sorted(miss.items(), key=lambda kv: -kv[1])[:15]:
            out(f"       {k}  {v}/{tot_c[k]}")
        # 참조에 있으나 내게 없는 것: 길이 분포
        tm = cKDTree(norm_segs(my_golf))
        d, _ = tm.query(norm_segs(ref_golf), distance_upper_bound=1.5)
        missing = ref_golf[~np.isfinite(d)]
        if len(missing):
            L = np.hypot(missing[:, 2] - missing[:, 0], missing[:, 3] - missing[:, 1])
            out(f"     내게 없는 참조 골조 선분 {len(missing)}개, 길이 중앙값 {np.median(L):.0f}, 범위 x {missing[:,0].min():.0f}~{missing[:,0].max():.0f} y {missing[:,1].min():.0f}~{missing[:,1].max():.0f}")
    my_cen = to_segments(by_layers(cand[n]["cen"], a.cen_layers.split(",")))
    mc = match_metrics(ref_cen, my_cen); out("  중심선 " + fmt(mc))
    my_open = to_segments(cand[n]["open"])
    mo = match_metrics(ref_open, my_open); out("  OPEN   " + fmt(mo))
    tot[n] = {"golf": mg, "cen": mc, "open": mo, "dx": dx, "dy": dy}

out("===== 요약(F1 %)")
out("층   골조   중심선  OPEN")
for n in sorted(tot):
    out(f"B{n}  {tot[n]['golf']['f1']:5.1f}  {tot[n]['cen']['f1']:5.1f}  {tot[n]['open']['f1']:5.1f}")
avg = {c: np.mean([tot[n][c]["f1"] for n in tot]) for c in ("golf", "cen", "open")}
out(f"평균 {avg['golf']:5.1f}  {avg['cen']:5.1f}  {avg['open']:5.1f}")
if a.report:
    open(a.report, "w", encoding="utf-8").write("\n".join(lines))
pickle.dump(tot, open(a.cand.replace(".pkl", "_cmp.pkl"), "wb"))
