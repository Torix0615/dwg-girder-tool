"""4단계 자체 회귀: 요소 대응표로 가상 MIDAS Beam Force 결과표를 만들어 stage4_check → stage4_apply 왕복을 검사한다(실제 MIDAS 결과 샘플이 없을 때).
python stage4_selftest.py <_MIDAS_elements.json> <_MIDAS.mgt> <출력폴더> [--config config.json] [--heavy]
  기본: 중력 하중 수준 부재력(거더 w=40 kN/m 등)으로 대부분 OK. --heavy: 하중을 3배로 키워 NG·추천·단면 교체까지 검사.
  결과표 3형식(탭/CSV/공백, kN·mm / kN·m, 하중케이스 D·L만 / 조합 이름)으로 각각 돌려 파서를 함께 검사.
"""
import sys, os, json, subprocess, random

args = [a for a in sys.argv[1:] if not a.startswith("--")]
heavy = "--heavy" in sys.argv
cfg = ["--config", sys.argv[sys.argv.index("--config") + 1]] if "--config" in sys.argv else []
if "--config" in sys.argv:
    args = [a for a in args if a != sys.argv[sys.argv.index("--config") + 1]]
elem_p, mgt_p, out_dir = args[0], args[1], args[2]
os.makedirs(out_dir, exist_ok=True)
EL = json.load(open(elem_p, encoding="utf-8"))
random.seed(7)
scale = 3.0 if heavy else 1.0


def forces(e):
    """(N, Vy, Vz, T, My, Mz) in kN / kN·mm, D 와 L 로 나눠 반환"""
    L = e.get("len") or 5000.0
    if e["kind"] == "col":
        floors_above = max(1, sum(1 for s in EL["stories"] if s["z"] > e["z"]) - 1)
        P = -(900 + 450 * floors_above) * scale  # 압축(-)
        return {"D": (P * 0.7, 10, 12, 0, 60e3 * scale, 45e3 * scale), "L": (P * 0.3, 4, 5, 0, 25e3 * scale, 20e3 * scale)}
    w = (40 if e["kind"] == "girder" else 22) * scale / 1000.0  # kN/mm
    M_end = w * L ** 2 / 12; M_mid = w * L ** 2 / 24; V = w * L / 2
    return {"D": (0, 0, V * 0.65, 0, M_end * 0.65, 0), "L": (0, 0, V * 0.35, 0, M_end * 0.35, 0)}, M_mid


def rows_for(e):
    out = []
    f = forces(e)
    if e["kind"] == "col":
        for ld, v in f.items():
            for part in ("I[1]", "J[2]"):
                out.append((e["id"], ld, part, *v))
    else:
        d, M_mid = f
        for ld, v in d.items():
            share = 0.65 if ld == "D" else 0.35
            out.append((e["id"], ld, "I[1]", 0, 0, v[2], 0, -v[4], 0))
            out.append((e["id"], ld, "2/4", 0, 0, 0, 0, M_mid * share, 0))
            out.append((e["id"], ld, "J[2]", 0, 0, -v[2], 0, -v[4], 0))
    return out


elems = [e for e in EL["elements"] if e["kind"] in ("col", "girder", "beam")]
rows = [r for e in elems for r in rows_for(e)]


def write_cases(path, delim, unit_m):
    conv = 1e-3 if unit_m == "m" else 1.0  # kN·mm → kN·m
    hdr = ["Elem", "Load", "Part", "Axial (kN)", "Shear-y (kN)", "Shear-z (kN)", f"Torsion (kN*{unit_m})", f"Moment-y (kN*{unit_m})", f"Moment-z (kN*{unit_m})"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("Beam Force\n\n")
        join = (lambda c: "\t".join(c)) if delim == "\t" else (lambda c: ",".join(c)) if delim == "," else (lambda c: "  ".join(x.ljust(14) for x in c))
        f.write(join(hdr) + "\n")
        for r in rows:
            vals = [f"{r[3]:.3f}", f"{r[4]:.3f}", f"{r[5]:.3f}", f"{r[6]*conv:.4f}", f"{r[7]*conv:.4f}", f"{r[8]*conv:.4f}"]
            f.write(join([str(r[0]), r[1], r[2], *vals]) + "\n")


def write_combos(path):
    """조합 이름(1.2D+1.6L, 1.4D)으로 이미 조합된 표(탭, kN·mm)"""
    byk = {}
    for r in rows:
        byk.setdefault((r[0], r[2]), {})[r[1]] = r[3:]
    with open(path, "w", encoding="utf-8") as f:
        f.write("Elem\tLoad\tPart\tAxial (kN)\tShear-y (kN)\tShear-z (kN)\tTorsion (kN*mm)\tMoment-y (kN*mm)\tMoment-z (kN*mm)\n")
        for (eid, part), d in byk.items():
            D = d.get("D", (0,) * 6); L = d.get("L", (0,) * 6)
            for name, fd, fl in (("1.4D", 1.4, 0), ("1.2D+1.6L", 1.2, 1.6)):
                v = [fd * a + fl * b for a, b in zip(D, L)]
                f.write("\t".join([str(eid), name, part] + [f"{x:.3f}" for x in v]) + "\n")


cases = [("tab_mm_cases.txt", "\t", "mm"), ("csv_m_cases.csv", ",", "m"), ("space_mm_cases.txt", " ", "mm")]
for name, d, u in cases:
    write_cases(os.path.join(out_dir, name), d, u)
write_combos(os.path.join(out_dir, "tab_mm_combos.txt"))
HERE = os.path.dirname(os.path.abspath(__file__))
env = dict(os.environ, PYTHONUTF8="1")
ref = None
fails = []
for name in [c[0] for c in cases] + ["tab_mm_combos.txt"]:
    od = os.path.join(out_dir, "chk_" + name.split(".")[0])
    r = subprocess.run([sys.executable, os.path.join(HERE, "stage4_check.py"), elem_p, os.path.join(out_dir, name), od] + cfg, cwd=HERE, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True)
    summ = next((l for l in r.stdout.splitlines() if l.startswith("SUMMARY=")), None)
    print(f"[{name}] rc={r.returncode} {summ or r.stderr[-400:]}")
    if r.returncode != 0 or not summ:
        fails.append(name); continue
    s = json.loads(summ[8:])
    if ref is None:
        ref = s
    elif (s["ok"], s["ng"], s["none"]) != (ref["ok"], ref["ng"], ref["none"]):
        fails.append(f"{name}: 결과 불일치 {s} vs {ref}")
    if s["none"] != 0 or s["unknown"] != 0:
        fails.append(f"{name}: 결과 없음 {s['none']} / 모르는 요소 {s['unknown']}")
    if heavy and s["ng"] == 0:
        fails.append(f"{name}: --heavy 인데 NG 0")
    if not heavy and s["ng"] > s["total"] * 0.5:  # 기둥은 기본 철근(12-D22)이 큰 단면에서 최소 철근비 1% 미달로 NG 가 날 수 있음
        fails.append(f"{name}: 기본 하중인데 NG {s['ng']}/{s['total']}")
    # 승인 → 수정 MGT
    r2 = subprocess.run([sys.executable, os.path.join(HERE, "stage4_apply.py"), mgt_p, os.path.join(od, "check.json"), os.path.join(od, "modified.mgt")], cwd=HERE, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True)
    summ2 = next((l for l in r2.stdout.splitlines() if l.startswith("SUMMARY=")), None)
    print(f"   apply rc={r2.returncode} {summ2 or r2.stderr[-300:]}")
    if r2.returncode != 0:
        fails.append(name + " apply")
    elif summ2:
        s2 = json.loads(summ2[8:])
        if s2["changed"] != s["dims_changed"]:
            fails.append(f"{name}: 치수 변경 {s['dims_changed']} ≠ MGT 교체 {s2['changed']}")
        txt = open(os.path.join(od, "modified.mgt"), encoding="utf-8").read()
        if "*SECTION" not in txt or "*ENDDATA" not in txt:
            fails.append(name + ": 수정 MGT 형식 깨짐")
print("\nRESULT:", "FAIL " + "; ".join(fails) if fails else f"PASS (OK {ref['ok']} NG {ref['ng']} 치수변경 {ref['dims_changed']})")
sys.exit(1 if fails else 0)
