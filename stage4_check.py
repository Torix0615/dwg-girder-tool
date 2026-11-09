"""4단계: MIDAS Gen 해석 결과표(Beam Force 텍스트)로 기둥·거더·보 단면을 KDS 14 20 강도설계법으로 검토하고 NG 부재는 철근→폭→춤 순으로 추천(피드백 1d7f01, 전문가 답변 11-09).
python stage4_check.py <요소대응표 _MIDAS_elements.json> <MIDAS 결과표 .txt|.csv> <출력폴더> [--config config.json]
출력: <출력폴더>/check.json(요소별 검토·추천, stage4_apply 입력) + check.xlsx(검토결과·요약·하중 시트). 표준 출력 마지막 줄 SUMMARY=<json>.
입력 결과표: MIDAS Gen 결과 테이블(Beam Force) 을 텍스트/CSV 로 내보낸 파일. 열 = Elem, Load, Part, Axial, Shear-y, Shear-z, Torsion, Moment-y, Moment-z (한글 머리글도 인식).
  단위는 머리글 괄호(kN, kN*m, kN*mm, N, tonf…)에서 읽고(설정 검토_결과_단위=auto), 없으면 MGT 와 같은 kN·mm 로 본다.
  Load 열이 개별 하중케이스(D/L 계열 이름)뿐이면 설정 검토_하중조합(기본 1.4D; 1.2D+1.6L)으로 조합을 만들고, 조합 이름이 있으면 그대로 쓴다.
검토 규칙(요약):
  기둥: 각 하중·위치의 (Pu, Muy)·(Pu, Muz) 를 축별 PM 상관도(변형률 적합, εcu 0.0033, β1 0.80, φ 0.65~0.85, φPn,max=0.80φPo)로 반경비 D/C. 최소 편심 15+0.03h, 세장비 klu/r>한계면 δns 확대(EI=0.4EcIg/(1+βd), Cm=1).
  거더·보: 양단(I·J)은 상부근, 중앙은 하부근으로 휨(φMn, εt≥0.004 미만이면 과다철근 NG), 전단은 Vc=(1/6)√fck·bw·d + 2가닥 스터럽 Vs(≤(2/3)√fck·bw·d), φ 0.75. 스터럽 간격 ≤ d/2·600(또는 d/4·300).
  판정 D/C ≤ 1.0 = OK. NG 추천: 철근(개수→직경, 스터럽 간격→직경) → 폭 +증분 → 춤 +증분(상한 = 단면_최대배율), 처음 OK 가 되는 조합.
"""
import sys, os, re, json, math, time, csv, io
from cfg import pop_config_arg

CFG, argv = pop_config_arg(sys.argv[1:])
if len(argv) < 3:
    sys.exit(__doc__)
elem_p, res_p, out_dir = argv[0], argv[1], argv[2]
os.makedirs(out_dir, exist_ok=True)
T0 = time.time()
LOG = []


def log(s):
    print(s, flush=True); LOG.append(s)


def step(name):
    print(f"\n=== {name}", flush=True); LOG.append(f"=== {name}")


# ---------------- 재료·철근 ----------------
BAR = {"D10": (9.53, 71.33), "D13": (12.7, 126.7), "D16": (15.9, 198.6), "D19": (19.1, 286.5), "D22": (22.2, 387.1), "D25": (25.4, 506.7),
       "D29": (28.6, 642.4), "D32": (31.8, 794.2), "D35": (34.9, 956.6), "D38": (38.1, 1140)}
ES = 200000.0
ECU = 0.0033


def bar_d(name):
    return BAR[name][0]


def bar_a(name):
    return BAR[name][1]


def parse_bars(s, what):
    m = re.fullmatch(r"\s*(\d+)\s*-\s*(D\d+)\s*", str(s), re.I)
    if not m or m.group(2).upper() not in BAR:
        raise SystemExit(f"설정 오류: {what} = '{s}' (예: 4-D22)")
    return int(m.group(1)), m.group(2).upper()


def parse_stirrup(s, what):
    m = re.fullmatch(r"\s*(D\d+)\s*@\s*(\d+)\s*", str(s), re.I)
    if not m or m.group(1).upper() not in BAR:
        raise SystemExit(f"설정 오류: {what} = '{s}' (예: D10@200)")
    return m.group(1).upper(), int(m.group(2))


def Ec(fck):
    return 8500.0 * (fck + (4 if fck <= 40 else 6 if fck >= 60 else 4 + (fck - 40) / 10)) ** (1 / 3)


def beta1(fck):
    return 0.80 if fck <= 40 else max(0.64, 0.80 - 0.04 * ((fck - 40) / 10))


def eta(fck):
    return 1.0 if fck <= 40 else max(0.84, 1.0 - 0.02 * ((fck - 40) / 10))


def phi_of(et, fy):
    ey = fy / ES; tcl = 0.005 if fy <= 400 else 2.5 * ey
    if et <= ey:
        return 0.65
    if et >= tcl:
        return 0.85
    return 0.65 + 0.20 * (et - ey) / (tcl - ey)


S = {k: CFG.get(k) for k in CFG if str(k).startswith("검토_")}
FCK_COL = float(S["검토_fck_기둥"]); FCK_BEAM = float(S["검토_fck_보"]); FY = float(S["검토_fy"]); FYT = float(S["검토_fy_전단"])
COVER = {"col": float(S["검토_피복_기둥"]), "girder": float(S["검토_피복_보"]), "beam": float(S["검토_피복_보"])}
CANDS = [c.strip().upper() for c in str(S["검토_철근_후보"]).replace(";", ",").split(",") if c.strip()]
CANDS = [c for c in CANDS if c in BAR] or ["D13", "D16", "D19", "D22", "D25", "D29", "D32"]
DB_STEP = int(S["검토_폭_증분"]); DH_STEP = int(S["검토_춤_증분"]); MAXR = max(1.0, float(S["검토_단면_최대배율"]) / 100.0)
RHO_MAX_COL = float(S["검토_기둥_철근비_최대"]) / 100.0
K_EFF = float(S["검토_유효길이계수"]); BETA_D = float(S["검토_크리프계수"]); SLEND = float(S["검토_세장비_한계"])
REBAR0 = {
    "col": {"main": parse_bars(S["검토_기둥_주근"], "검토_기둥_주근"), "tie": parse_stirrup(S["검토_기둥_띠철근"], "검토_기둥_띠철근")},
    "girder": {"top": parse_bars(S["검토_거더_상부"], "검토_거더_상부"), "bot": parse_bars(S["검토_거더_하부"], "검토_거더_하부"), "stir": parse_stirrup(S["검토_거더_스터럽"], "검토_거더_스터럽")},
    "beam": {"top": parse_bars(S["검토_보_상부"], "검토_보_상부"), "bot": parse_bars(S["검토_보_하부"], "검토_보_하부"), "stir": parse_stirrup(S["검토_보_스터럽"], "검토_보_스터럽")},
}

# ---------------- 요소 대응표 ----------------
step("요소 대응표 읽기")
EL = json.load(open(elem_p, encoding="utf-8"))
SECS = {int(k): v for k, v in EL["sections"].items()}
elements = [e for e in EL["elements"] if e["kind"] in ("col", "girder", "beam")]
by_id = {e["id"]: e for e in elements}
log(f"요소 {len(EL['elements'])}개 중 검토 대상 {len(elements)}개 (기둥 {sum(e['kind']=='col' for e in elements)} 거더 {sum(e['kind']=='girder' for e in elements)} 보 {sum(e['kind']=='beam' for e in elements)})")

# ---------------- 결과표 파서 ----------------
ALIAS = {
    "elem": ["elem", "element", "요소", "부재"], "load": ["load", "lcase", "하중", "조합"], "part": ["part", "position", "pos", "위치", "지점"],
    "n": ["axial", "fx", "축력"], "vy": ["shear-y", "shear y", "shear_y", "sheary", "fy", "전단-y", "전단y", "전단력-y"],
    "vz": ["shear-z", "shear z", "shear_z", "shearz", "fz", "전단-z", "전단z", "전단력-z"], "t": ["torsion", "mx", "비틀림"],
    "my": ["moment-y", "moment y", "moment_y", "momenty", "모멘트-y", "모멘트y", "휨모멘트-y"], "mz": ["moment-z", "moment z", "moment_z", "momentz", "모멘트-z", "모멘트z", "휨모멘트-z"],
}
F_UNIT = {"kn": 1.0, "n": 1e-3, "tonf": 9.80665, "tf": 9.80665, "kgf": 9.80665e-3, "kips": 4.44822, "kip": 4.44822, "lbf": 4.44822e-3}
L_UNIT = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8}


def norm(h):
    return re.sub(r"\s+", " ", str(h).strip().lower().replace("(", " (").replace("*", "·").replace("ㆍ", "·"))


def match_col(h):
    base = re.sub(r"\(.*?\)|\[.*?\]", "", norm(h)).strip()
    for key, al in ALIAS.items():
        for a in al:
            if base == a or base.startswith(a) or base.replace("-", "").replace(" ", "") == a.replace("-", "").replace(" ", ""):
                return key
    return None


def unit_of(h):
    m = re.search(r"[\(\[]([^\)\]]*)[\)\]]", str(h))
    if not m:
        return None
    u = m.group(1).lower().replace("·", "*").replace("ㆍ", "*").replace("x", "*").replace(" ", "")
    parts = u.split("*")
    f = next((F_UNIT[p] for p in parts if p in F_UNIT), None)
    l = next((L_UNIT[p] for p in parts if p in L_UNIT), None)
    return f, l


def split_line(line, delim):
    if delim == "\t":
        return [c.strip() for c in line.split("\t")]
    if delim == ",":
        rows_ = list(csv.reader(io.StringIO(line)))
        return [c.strip() for c in rows_[0]] if rows_ else []
    return [c.strip() for c in re.split(r"\s{2,}|\t", line.strip())]


def parse_part(p):
    p = str(p).strip().upper()
    if p.startswith("I") or p in ("시작", "I단"):
        return "I"
    if p.startswith("J") or p in ("끝", "J단"):
        return "J"
    return "M"


def to_float(s):
    try:
        return float(str(s).replace(",", ""))
    except ValueError:
        return None


def parse_result(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp949", "utf-16", "latin-1"):
        try:
            text = raw.decode(enc); break
        except UnicodeDecodeError:
            continue
    lines = [l.rstrip("\r\n") for l in text.splitlines()]
    hdr_i = hdr = delim = None
    for i, l in enumerate(lines):
        for d in ("\t", ",", None):
            cols = split_line(l, d)
            keys = [match_col(c) for c in cols]
            if "elem" in keys and ("n" in keys or "my" in keys or "mz" in keys) and len([k for k in keys if k]) >= 4:
                hdr_i, hdr, delim = i, cols, d; break
        if hdr is not None:
            break
    if hdr is None:
        raise SystemExit("결과표 머리글을 찾지 못함 — MIDAS 결과 테이블(Beam Force: Elem, Load, Part, Axial, Shear, Moment 열)을 텍스트/CSV 로 내보낸 파일이어야 함")
    keys = [match_col(c) for c in hdr]
    idx = {k: keys.index(k) for k in ALIAS if k in keys}
    unit_mode = str(S.get("검토_결과_단위", "auto")).lower().replace(" ", "")
    fu = lu = None
    if unit_mode != "auto" and "," in unit_mode:
        a, b = unit_mode.split(",", 1); fu = F_UNIT.get(a); lu = L_UNIT.get(b)
    f_force = fu; f_len = lu
    if f_force is None:
        for k in ("n", "vz", "vy"):
            if k in idx:
                u = unit_of(hdr[idx[k]])
                if u and u[0]:
                    f_force = u[0]; break
    m_scale = None
    for k in ("my", "mz", "t"):
        if k in idx:
            u = unit_of(hdr[idx[k]])
            if u and u[0]:
                m_scale = u[0] * (u[1] or (f_len or 1.0)); break
    if f_force is None:
        f_force = 1.0
    if m_scale is None:
        m_scale = f_force * (f_len or 1.0)
    rows = []; bad = 0; unknown_ids = set()
    rx_fallback = re.compile(r"^\s*(\d+)\s+(.+?)\s+(I\[?\d*\]?|J\[?\d*\]?|\d/\d|I|J|MID\w*|중앙|시작|끝)\s+([-+\d.eE\s,]+)$", re.I)
    for l in lines[hdr_i + 1:]:
        if not l.strip():
            continue
        cols = split_line(l, delim)
        if len(cols) < len(hdr) and delim is None:
            m = rx_fallback.match(l)
            if m:
                nums = [x for x in re.split(r"[\s,]+", m.group(4).strip()) if x]
                cols = [m.group(1), m.group(2), m.group(3)] + nums
                tmp = {}
                order = [k for k in ("n", "vy", "vz", "t", "my", "mz") if k in idx]
                for k, v in zip(order, nums):
                    tmp[k] = v
                cols = {"elem": m.group(1), "load": m.group(2), "part": m.group(3), **tmp}
        def get(k):
            if isinstance(cols, dict):
                return cols.get(k)
            j = idx.get(k)
            return cols[j] if j is not None and j < len(cols) else None
        eid = to_float(get("elem"))
        if eid is None or int(eid) != eid:
            if match_col(str(get("elem") or "")) == "elem":
                continue  # 반복 머리글
            bad += 1; continue
        eid = int(eid)
        if eid not in by_id:
            unknown_ids.add(eid); continue
        vals = {}
        for k in ("n", "vy", "vz", "t", "my", "mz"):
            v = to_float(get(k)) if k in idx or isinstance(cols, dict) else None
            vals[k] = (v or 0.0) * (m_scale if k in ("t", "my", "mz") else f_force)
        rows.append({"elem": eid, "load": str(get("load") or "-").strip(), "part": parse_part(get("part") or "M"), **vals})
    meta = {"file": os.path.basename(path), "header": hdr, "delim": {"\t": "tab", ",": "comma", None: "space"}[delim], "rows": len(rows), "skipped": bad,
            "unknown_ids": sorted(unknown_ids)[:50], "unknown_count": len(unknown_ids), "force_to_kN": f_force, "moment_to_kNmm": m_scale, "unit_mode": unit_mode}
    return rows, meta


step("MIDAS 결과표 읽기")
rows, meta = parse_result(res_p)
if not rows:
    raise SystemExit(f"결과표에서 요소 대응표와 번호가 맞는 행이 없음(읽은 행 {meta['rows']}, 모르는 요소 번호 {meta['unknown_count']}개) — 3단계 MGT 를 그대로 해석한 결과표인지 확인")
loads = sorted({r["load"] for r in rows})
log(f"행 {len(rows)}개, 하중 {len(loads)}종 {loads[:8]}{'…' if len(loads) > 8 else ''}, 단위 환산 힘×{meta['force_to_kN']:g}→kN 모멘트×{meta['moment_to_kNmm']:g}→kN·mm, 모르는 요소 {meta['unknown_count']}개")

# ---------------- 하중조합(개별 케이스만 있을 때) ----------------
RX_D = re.compile(r"^(D|DL|DEAD|SW|SELF|SELFWEIGHT|G|고정|자중)", re.I)
RX_L = re.compile(r"^(L|LL|LIVE|Q|활)", re.I)
RX_COMBO = re.compile(r"\+|LCB|COMB|ENV|조합", re.I)


def classify_load(name):
    if RX_COMBO.search(name):
        return "combo"
    if RX_D.match(name):
        return "D"
    if RX_L.match(name):
        return "L"
    return "?"


kinds = {l: classify_load(l) for l in loads}
combo_note = ""
if all(k in ("D", "L") for k in kinds.values()):
    combos = []
    for c in str(S["검토_하중조합"]).replace(",", ";").split(";"):
        c = c.strip()
        if not c:
            continue
        fac = {}
        for m in re.finditer(r"([-+]?\s*\d*\.?\d*)\s*\*?\s*([DL])", c.replace(" ", ""), re.I):
            f = m.group(1).replace(" ", "")
            fac[m.group(2).upper()] = fac.get(m.group(2).upper(), 0.0) + (float(f) if f not in ("", "+", "-") else (1.0 if f != "-" else -1.0))
        if fac:
            combos.append((c, fac))
    if combos:
        by_key = {}
        for r in rows:
            by_key.setdefault((r["elem"], r["part"]), {}).setdefault(kinds[r["load"]], []).append(r)
        new = []
        for (eid, part), d in by_key.items():
            for name, fac in combos:
                acc = {k: 0.0 for k in ("n", "vy", "vz", "t", "my", "mz")}
                for typ, f in fac.items():
                    for r in d.get(typ, []):
                        for k in acc:
                            acc[k] += f * r[k]
                new.append({"elem": eid, "load": name, "part": part, **acc})
        rows = new
        combo_note = f"개별 하중케이스({', '.join(loads)})만 있어 설정 하중조합 {len(combos)}개({'; '.join(c for c, _ in combos)})를 프로그램이 조합함"
        log(combo_note)
    else:
        combo_note = "하중조합 설정이 비어 있어 하중케이스를 그대로 검토"
else:
    unk = [l for l, k in kinds.items() if k == "?"]
    combo_note = "결과표의 하중(조합) 이름을 그대로 사용" + (f" — 분류 안 되는 이름 {len(unk)}개도 조합으로 간주: {unk[:5]}" if unk else "")
    log(combo_note)
rows_by_elem = {}
for r in rows:
    rows_by_elem.setdefault(r["elem"], []).append(r)

# ---------------- 단면 강도 ----------------
_curve_cache = {}


def col_layers(h, b, n, D, cover, tie):
    """축 깊이 h 방향 철근층 [(압축면에서 거리, 면적)]. n 은 4의 배수(아니면 올림), 4면 균등 배치"""
    n4 = max(4, int(math.ceil(n / 4.0)) * 4)
    m = n4 // 4 + 1
    d1 = cover + bar_d(tie) + bar_d(D) / 2
    if h - 2 * d1 < bar_d(D):
        return None
    pos = [d1 + (h - 2 * d1) * i / (m - 1) for i in range(m)]
    a = bar_a(D)
    return [(pos[0], m * a)] + [(p, 2 * a) for p in pos[1:-1]] + [(pos[-1], m * a)]


def pm_curve(h, b, layers, fck, fy):
    key = (round(h), round(b), tuple((round(d, 1), round(a, 1)) for d, a in layers), fck, fy)
    if key in _curve_cache:
        return _curve_cache[key]
    b1 = beta1(fck); et_ = eta(fck); Ag = h * b; Ast = sum(a for _, a in layers)
    Po = et_ * 0.85 * fck * (Ag - Ast) + fy * Ast
    cap = 0.65 * 0.80 * Po
    dmax = max(d for d, _ in layers)
    pts = []
    cs = [h * (0.02 * 1.05 ** i) for i in range(0, 260)]
    cs = [c for c in cs if c <= 50 * h]
    for c in cs:
        a = min(b1 * c, h); Cc = et_ * 0.85 * fck * a * b
        P = Cc; M = Cc * (h / 2 - a / 2)
        for d, As in layers:
            es = ECU * (c - d) / c; fs = max(-fy, min(fy, ES * es))
            if d < a and fs > 0:
                fs -= et_ * 0.85 * fck
            P += As * fs; M += As * fs * (h / 2 - d)
        et = ECU * (dmax - c) / c
        phi = phi_of(et, fy)
        pts.append((phi * max(M, 0.0), phi * P))
    pts.sort(key=lambda p: -p[1])
    poly = [(0.0, cap)]
    for M, P in pts:
        if P < cap:
            poly.append((M, P))
    poly.append((0.0, -0.85 * fy * Ast))
    # 상단 수평 구간: cap 과 만나는 M
    first = next((i for i, (M, P) in enumerate(pts) if P < cap), None)
    if first is not None and first > 0:
        (M1, P1), (M2, P2) = pts[first - 1], pts[first]
        Mc = M1 + (M2 - M1) * (cap - P1) / (P2 - P1) if P2 != P1 else M2
        poly.insert(1, (Mc, cap))
    res = {"poly": poly, "cap": cap, "Mmax": max(M for M, _ in poly), "Ast": Ast, "rho": Ast / Ag}
    _curve_cache[key] = res
    return res


def radial_dc(curve, Pu, Mu):
    """원점→(Mu,Pu) 반직선이 φ곡선을 지나는 비율 = D/C"""
    if Mu <= 1e-9 and abs(Pu) <= 1e-9:
        return 0.0
    poly = curve["poly"]
    best = None
    for (ax, ay), (bx, by) in zip(poly[:-1], poly[1:]):
        dx, dy = bx - ax, by - ay
        det = Mu * (-dy) - Pu * (-dx)
        if abs(det) < 1e-12:
            continue
        t = (ax * (-dy) - ay * (-dx)) / det
        s = (Mu * ay - Pu * ax) / det
        if t > 0 and -1e-9 <= s <= 1 + 1e-9:
            if best is None or t > best:
                best = t
    if best is None or best <= 0:
        return max(Pu / curve["cap"] if Pu > 0 else 0.0, Mu / curve["Mmax"] if curve["Mmax"] > 0 else 9.99)
    return 1.0 / best


def check_column(e, dims, rebar, rws):
    """dims=(H,B) H=요소 z축(모멘트-y 깊이), B=요소 y축(모멘트-z 깊이). 반환 dict"""
    H, B = dims; n, D = rebar["main"]; tie = rebar["tie"][0]; cover = COVER["col"]; fck = FCK_COL
    res = {"dc": 0.0, "flags": [], "gov": None}
    layers = {"y": col_layers(H, B, n, D, cover, tie), "z": col_layers(B, H, n, D, cover, tie)}
    if layers["y"] is None or layers["z"] is None:
        res["dc"] = 9.99; res["flags"].append("배근 불가(단면 작음)"); return res
    curves = {"y": pm_curve(H, B, layers["y"], fck, FY), "z": pm_curve(B, H, layers["z"], fck, FY)}
    rho = curves["y"]["rho"]
    if rho > RHO_MAX_COL:
        res["flags"].append(f"철근비 {rho*100:.1f}% > 최대 {RHO_MAX_COL*100:.0f}%"); res["dc"] = max(res["dc"], 9.0)
    if rho < 0.01:
        res["flags"].append(f"철근비 {rho*100:.2f}% < 최소 1%")
    lu = (e.get("len") or EL.get("story_h") or 5000.0); Ecm = Ec(fck)
    slender = {}
    for ax, h in (("y", H), ("z", B)):
        r = 0.3 * h; kl_r = K_EFF * lu / r
        if kl_r > SLEND:
            Ig = B * H ** 3 / 12 if ax == "y" else H * B ** 3 / 12
            EI = 0.4 * Ecm * Ig / (1 + BETA_D)
            Pc = math.pi ** 2 * EI / (K_EFF * lu) ** 2 / 1e3  # kN
            slender[ax] = (kl_r, Pc)
    for r in rws:
        Pu = -r["n"]  # MIDAS 축력 (+)인장 → 압축 양수
        for ax, h, Mu in (("y", H, abs(r["my"])), ("z", B, abs(r["mz"]))):
            if Pu > 0:
                Mu = max(Mu, Pu * (15 + 0.03 * h))
                if ax in slender:
                    kl_r, Pc = slender[ax]
                    if Pu >= 0.75 * Pc:
                        dc = 9.99; res["flags"].append("좌굴(Pu ≥ 0.75Pc)")
                    else:
                        Mu *= max(1.0, 1.0 / (1 - Pu / (0.75 * Pc)))
                        dc = radial_dc(curves[ax], Pu, Mu * 1e3)
                else:
                    dc = radial_dc(curves[ax], Pu, Mu * 1e3)
            else:
                dc = radial_dc(curves[ax], Pu, Mu * 1e3)
            if dc > res["dc"]:
                res["dc"] = dc
                res["gov"] = {"load": r["load"], "part": r["part"], "axis": ax, "Pu": round(Pu, 1), "Mu": round(Mu / 1e3, 1), "Vu": round(math.hypot(r["vy"], r["vz"]), 1)}
    res["rho"] = rho
    res["slender"] = {ax: round(v[0], 1) for ax, v in slender.items()}
    res["flags"] = sorted(set(res["flags"]))
    return res


def beam_fit(b, n, D, cover, stir):
    """한 층 배근 가능 여부(순간격 ≥ max(25, db))"""
    if n < 2:
        return False
    db = bar_d(D); clear = (b - 2 * cover - 2 * bar_d(stir) - n * db) / (n - 1)
    return clear >= max(25.0, db)


def beam_flex(b, h, n, D, cover, stir, fck, fy):
    """φMn(kN·mm), εt, 플래그"""
    db = bar_d(D); d = h - cover - bar_d(stir) - db / 2; As = n * bar_a(D)
    a = As * fy / (eta(fck) * 0.85 * fck * b); c = a / beta1(fck)
    et = ECU * (d - c) / c if c > 0 else 1.0
    phi = phi_of(et, fy); Mn = As * fy * (d - a / 2)
    flags = []
    if et < 0.004:
        flags.append("과다철근(εt<0.004)")
    rho = As / (b * d); rmin = max(0.25 * math.sqrt(fck) / fy, 1.4 / fy)
    if rho < rmin:
        flags.append(f"최소철근비 미달(ρ {rho*100:.2f}%<{rmin*100:.2f}%)")
    return phi * Mn / 1e3, et, flags, d


def beam_shear(b, d, stir, fck, fyt):
    D, s = stir; Av = 2 * bar_a(D)
    Vc = math.sqrt(fck) / 6 * b * d / 1e3; Vs = Av * fyt * d / s / 1e3; Vs_max = 2 / 3 * math.sqrt(fck) * b * d / 1e3
    flags = []
    smax = min(d / 2, 600) if Vs <= math.sqrt(fck) / 3 * b * d / 1e3 else min(d / 4, 300)
    if s > smax:
        flags.append(f"스터럽 간격 {s} > 허용 {smax:.0f}")
    if Vs > Vs_max:
        flags.append("전단 단면 부족(Vs>2/3√fck·bw·d)")
    return 0.75 * (Vc + Vs), flags


def check_beam(e, dims, rebar, rws):
    H, B = dims; cover = COVER[e["kind"]]; fck = FCK_BEAM; stir = rebar["stir"]
    res = {"dc": 0.0, "dc_m": 0.0, "dc_v": 0.0, "flags": [], "gov": None}
    cap = {}
    for pos, key in (("end", "top"), ("mid", "bot")):
        n, D = rebar[key]
        if not beam_fit(B, n, D, cover, stir[0]):
            res["flags"].append(f"{'상부' if key=='top' else '하부'} {n}-{D} 한 층 배근 불가(폭 {B:.0f})")
        phiMn, et, fl, d = beam_flex(B, H, n, D, cover, stir[0], fck, FY)
        if any("과다철근" in f for f in fl):
            phiMn = 1e-9
        cap[pos] = phiMn; res["flags"] += [f"{'단부' if pos=='end' else '중앙'} {f}" for f in fl]
    d = H - cover - bar_d(stir[0]) - max(bar_d(rebar["top"][1]), bar_d(rebar["bot"][1])) / 2
    phiVn, flv = beam_shear(B, d, stir, fck, FYT)
    if any("단면 부족" in f for f in flv):
        phiVn = 1e-9
    spacing_ng = any("간격" in f for f in flv)
    res["flags"] += flv
    for r in rws:
        Mu = abs(r["my"]); Vu = abs(r["vz"]); pos = "end" if r["part"] in ("I", "J") else "mid"
        dc_m = Mu / cap[pos] if cap[pos] > 0 else 9.99
        dc_v = Vu / phiVn if phiVn > 0 else 9.99
        if spacing_ng:
            dc_v = max(dc_v, 1.001)
        dc = max(dc_m, dc_v)
        if dc_m > res["dc_m"]:
            res["dc_m"] = dc_m
        if dc_v > res["dc_v"]:
            res["dc_v"] = dc_v
        if dc > res["dc"]:
            res["dc"] = dc
            res["gov"] = {"load": r["load"], "part": r["part"], "Pu": round(-r["n"], 1), "Mu": round(Mu / 1e3, 1), "Vu": round(Vu, 1), "mode": "휨" if dc_m >= dc_v else "전단"}
    res["flags"] = sorted(set(res["flags"]))
    return res


def check(e, dims, rebar, rws):
    r = check_column(e, dims, rebar, rws) if e["kind"] == "col" else check_beam(e, dims, rebar, rws)
    # OK = D/C ≤ 1 이고 배근 가능·철근비(기둥 1~최대%) 범위 안. 보의 최소철근비·스터럽 간격은 플래그(간격은 전단 D/C 에 반영)
    r["ok"] = r["dc"] <= 1.0 and not any(("배근 불가" in f or f.startswith("철근비")) for f in r["flags"])
    return r


# ---------------- 추천(철근 → 폭 → 춤) ----------------
def bar_options(cur, cands, nmin, nmax_fn, step=1):
    n0, D0 = cur
    start = cands.index(D0) if D0 in cands else 0
    seq = cands[start:] if D0 in cands else [D0] + cands
    for D in seq:
        nmax = nmax_fn(D)
        n_from = n0 if D == D0 else nmin
        n = n_from
        while n <= nmax:
            yield (n, D)
            n += step


def stir_options(cur, cands):
    D0, s0 = cur
    spaces = [s for s in (s0, 250, 200, 150, 125, 100, 75) if s <= s0]
    spaces = sorted(set(spaces), reverse=True)
    start = cands.index(D0) if D0 in cands else 0
    Ds = [D0] + [c for c in cands[start:] if bar_d(c) > bar_d(D0) and c in ("D13", "D16")]
    for D in Ds:
        for s in spaces:
            yield (D, s)


def dim_options(H, B, kind):
    """(H,B) 후보: 폭(B) 먼저 늘리고 그래도 안 되면 춤(H) — 기둥은 두 치수를 번갈아(X 먼저)"""
    Hmax = H * MAXR; Bmax = B * MAXR
    out = []
    if kind == "col":
        k = 0
        while True:
            found = False
            for i in range(k, -1, -1):
                j = k - i
                h = H + i * DH_STEP; b = B + j * DB_STEP
                if h <= Hmax + 1e-6 and b <= Bmax + 1e-6:
                    out.append((h, b)); found = True
            if not found:
                break
            k += 1
    else:
        h = H
        while h <= Hmax + 1e-6:
            b = B
            while b <= Bmax + 1e-6:
                out.append((h, b)); b += DB_STEP
            h += DH_STEP
    return out


def recommend(e, dims, rebar, rws):
    kind = e["kind"]
    tried = 0
    for (h, b) in dim_options(dims[0], dims[1], kind):
        if kind == "col":
            def nmax(D):
                return int((RHO_MAX_COL * h * b) // bar_a(D) // 4 * 4)
            for n, D in bar_options(rebar["main"], CANDS, 4, nmax, 4):
                rb = {"main": (n, D), "tie": rebar["tie"]}
                r = check(e, (h, b), rb, rws); tried += 1
                if r["ok"]:
                    return (h, b), rb, r, tried
                if tried > 4000:
                    return None
        else:
            cover = COVER[kind]
            def nmax(D, _b=b):
                n = 2
                while beam_fit(_b, n + 1, D, cover, rebar["stir"][0]):
                    n += 1
                return n
            # 휨: 상부(단부 행)·하부(중앙 행) 따로 최소 철근을 찾고, 전단: 스터럽 → 마지막에 전체 재검토
            best = {}
            for key in ("top", "bot"):
                sub = [x for x in rws if (x["part"] in ("I", "J")) == (key == "top")]
                if not sub:
                    best[key] = rebar[key]; continue
                for n, D in bar_options(rebar[key], CANDS, 2, nmax):
                    rb = dict(rebar); rb[key] = (n, D)
                    rr = check(e, (h, b), rb, sub); tried += 1
                    pos = "단부" if key == "top" else "중앙"
                    bad = any(("과다" in f and pos in f) or "배근 불가" in f for f in rr["flags"])
                    if rr["dc_m"] <= 1.0 and not bad:
                        best[key] = (n, D); break
                if tried > 4000:
                    return None
            if "top" in best and "bot" in best:
                for st in stir_options(rebar["stir"], CANDS):
                    rb = {"top": best["top"], "bot": best["bot"], "stir": st}
                    r = check(e, (h, b), rb, rws); tried += 1
                    if r["ok"]:
                        return (h, b), rb, r, tried
    return None


# ---------------- 전체 검토 ----------------
step("단면 검토")
results = []
cnt = {"ok": 0, "ng": 0, "none": 0}
for i, e in enumerate(elements):
    sec = SECS.get(e["sec"]) or {}
    dims = (float(sec.get("H", 600)), float(sec.get("B", 600)))
    rebar = REBAR0[e["kind"]]
    rws = rows_by_elem.get(e["id"])
    out = {"id": e["id"], "kind": e["kind"], "floor": e.get("floor"), "sec": e["sec"], "sec_name": sec.get("name"), "H": dims[0], "B": dims[1], "len": e.get("len"),
           "rebar": rebar}
    if not rws:
        out.update({"status": "none", "dc": None}); cnt["none"] += 1; results.append(out); continue
    r = check(e, dims, rebar, rws)
    out.update({"status": "ok" if r["ok"] else "ng", "dc": round(r["dc"], 3), "dc_m": round(r.get("dc_m", 0), 3) if "dc_m" in r else None,
                "dc_v": round(r.get("dc_v", 0), 3) if "dc_v" in r else None, "flags": r["flags"], "gov": r["gov"], "rho": round(r.get("rho", 0) * 100, 2) if "rho" in r else None,
                "slender": r.get("slender")})
    if r["ok"]:
        cnt["ok"] += 1
    else:
        cnt["ng"] += 1
        rec = recommend(e, dims, rebar, rws)
        if rec:
            (h, b), rb, rr, tried = rec
            out["rec"] = {"H": h, "B": b, "rebar": rb, "dc": round(rr["dc"], 3), "dims_changed": (h, b) != dims, "tried": tried}
        else:
            out["rec"] = None
    results.append(out)
    if (i + 1) % 200 == 0:
        log(f"  {i+1}/{len(elements)} 검토…")
log(f"검토 {len(elements)}개: OK {cnt['ok']} / NG {cnt['ng']} / 결과 없음 {cnt['none']}")
by_kind = {}
for r in results:
    d = by_kind.setdefault(r["kind"], {"ok": 0, "ng": 0, "none": 0, "dims": 0})
    d[r["status"]] += 1
    if r.get("rec") and r["rec"]["dims_changed"]:
        d["dims"] += 1

# ---------------- 저장 ----------------
step("결과 저장")
KIND_KO = {"col": "기둥", "girder": "거더", "beam": "보"}


def bars_s(rb, kind):
    if kind == "col":
        return f"{rb['main'][0]}-{rb['main'][1]}", f"{rb['tie'][0]}@{rb['tie'][1]}"
    return f"상 {rb['top'][0]}-{rb['top'][1]} / 하 {rb['bot'][0]}-{rb['bot'][1]}", f"{rb['stir'][0]}@{rb['stir'][1]}"


def tuplify(rb):
    return {k: list(v) for k, v in rb.items()}


summary = {"total": len(elements), **cnt, "by_kind": by_kind, "loads": loads, "combo_note": combo_note, "parse": meta,
           "settings": S, "elements_file": os.path.basename(elem_p), "result_file": os.path.basename(res_p), "at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "sections": SECS, "dims_changed": sum(1 for r in results if r.get("rec") and r["rec"]["dims_changed"])}
check_json = {"version": 1, "summary": summary,
              "results": [{**r, "rebar": tuplify(r["rebar"]), "rec": ({**r["rec"], "rebar": tuplify(r["rec"]["rebar"])} if r.get("rec") else r.get("rec"))} for r in results]}
json.dump(check_json, open(os.path.join(out_dir, "check.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)

from stage4_xlsx import write_xlsx
hdr = ["요소", "층", "종류", "단면 H×B\n(mm)", "주근(상/하)", "띠·스터럽", "Pu (kN)", "Mu (kN·m)", "Vu (kN)", "지배 하중", "위치", "D/C 휨·PM", "D/C 전단", "D/C", "판정",
       "추천 단면 H×B", "추천 주근", "추천 띠·스터럽", "추천 D/C", "비고"]
rows_x = [[(h, 1) for h in hdr]]
order = {"col": 0, "girder": 1, "beam": 2}
for r in sorted(results, key=lambda x: (order[x["kind"]], x["id"])):
    bars, stir = bars_s(r["rebar"], r["kind"])
    g = r.get("gov") or {}
    st = r["status"]
    judge = ("OK", 2) if st == "ok" else ("NG", 3) if st == "ng" else ("결과 없음", 4)
    rec = r.get("rec")
    rec_cells = ["", "", "", ""]
    if st == "ng":
        if rec:
            rb2, st2 = bars_s(rec["rebar"], r["kind"])
            rec_cells = [f"{rec['H']:.0f}×{rec['B']:.0f}" + ("" if rec["dims_changed"] else " (유지)"), rb2, st2, rec["dc"]]
        else:
            rec_cells = [("상한 내 해결 불가", 3), "", "", ""]
    part_ko = {"I": "I단", "J": "J단", "M": "중앙"}.get(g.get("part"), "")
    if r["kind"] == "col" and g.get("axis"):
        part_ko += f" M{g['axis']}"
    rows_x.append([r["id"], r.get("floor") or "", KIND_KO[r["kind"]], f"{r['H']:.0f}×{r['B']:.0f}", bars, stir, g.get("Pu", ""), g.get("Mu", ""), g.get("Vu", ""),
                   g.get("load", ""), part_ko, r.get("dc_m") if r["kind"] != "col" else r.get("dc"), r.get("dc_v") if r["kind"] != "col" else "", r.get("dc") if r["dc"] is not None else "",
                   judge, *rec_cells, "; ".join(r.get("flags") or [])])
sum_rows = [[("항목", 1), ("값", 1)],
            ["검토 시각", summary["at"]], ["요소 대응표", summary["elements_file"]], ["MIDAS 결과표", summary["result_file"]],
            ["검토 요소 수", summary["total"]], ["OK", summary["ok"]], ["NG", summary["ng"]], ["결과 없음(결과표에 요소 없음)", summary["none"]],
            ["치수 변경 추천", summary["dims_changed"]]]
for k in ("col", "girder", "beam"):
    d = by_kind.get(k)
    if d:
        sum_rows.append([f"{KIND_KO[k]} OK/NG/없음", f"{d['ok']} / {d['ng']} / {d['none']}  (치수 변경 {d['dims']})"])
sum_rows += [["하중", combo_note], ["하중 목록", ", ".join(loads)],
             ["단위 환산", f"힘 ×{meta['force_to_kN']:g} → kN, 모멘트 ×{meta['moment_to_kNmm']:g} → kN·mm (머리글: {' | '.join(meta['header'])})"],
             ["읽은 행 / 건너뜀 / 모르는 요소", f"{meta['rows']} / {meta['skipped']} / {meta['unknown_count']}" + (f" {meta['unknown_ids'][:20]}" if meta["unknown_ids"] else "")],
             ["", ""], [("설계 기준", 1), ("KDS 14 20 강도설계법 — εcu 0.0033, β1 0.80(fck≤40), φ 휨 0.65~0.85, φ 전단 0.75, 기둥 φPn,max=0.80φPo, 최소 편심 15+0.03h, 장주 δns(Cm=1, k=설정)", 5)]]
for k, v in S.items():
    sum_rows.append([k, str(v)])
sum_rows += [["", ""], [("주의", 1), ("이 검토값은 설계 참고용입니다. 구조 인증·납품 계산서는 MIDAS 설계 결과로 확인하십시오. 하중·하중조합은 MIDAS 모델에서 정의한 것을 결과표로 받아 사용합니다.", 5)]]
load_rows = [[("요소", 1), ("하중", 1), ("위치", 1), ("N (kN)", 1), ("Vy (kN)", 1), ("Vz (kN)", 1), ("T (kN·m)", 1), ("My (kN·m)", 1), ("Mz (kN·m)", 1)]]
for r in sorted(rows, key=lambda x: (x["elem"], x["load"], x["part"]))[:20000]:
    load_rows.append([r["elem"], r["load"], {"I": "I단", "J": "J단", "M": "중앙"}[r["part"]], round(r["n"], 1), round(r["vy"], 1), round(r["vz"], 1), round(r["t"] / 1e3, 2), round(r["my"] / 1e3, 2), round(r["mz"] / 1e3, 2)])
write_xlsx(os.path.join(out_dir, "check.xlsx"), [
    {"name": "검토결과", "rows": rows_x, "freeze": 1, "widths": [7, 7, 6, 12, 22, 11, 9, 10, 9, 14, 9, 10, 9, 8, 8, 14, 22, 12, 9, 50]},
    {"name": "요약", "rows": sum_rows, "widths": [28, 110]},
    {"name": "하중(환산)", "rows": load_rows, "freeze": 1, "widths": [7, 16, 7, 10, 10, 10, 10, 11, 11]},
])
log(f"saved {os.path.join(out_dir, 'check.xlsx')}, check.json ({time.time()-T0:.1f}s)")
open(os.path.join(out_dir, "check_log.txt"), "w", encoding="utf-8").write("\n".join(LOG))
print("SUMMARY=" + json.dumps({"total": summary["total"], "ok": cnt["ok"], "ng": cnt["ng"], "none": cnt["none"], "by_kind": by_kind, "dims_changed": summary["dims_changed"],
                                "loads": len(loads), "rows": meta["rows"], "unknown": meta["unknown_count"]}, ensure_ascii=False), flush=True)
