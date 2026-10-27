"""DXF 읽기·블록 재귀 전개 공통 모듈.
프리미티브(dict):
  kind: LINE(x1,y1,x2,y2) | POLY(pts[[x,y,bulge]...],closed) | ARC(cx,cy,r,a1,a2) | CIRCLE(cx,cy,r)
        | TEXT(x,y,h,s,rot) | INSERT(name,x,y)  (전개 안 한 경우)
  layer, lcolor(레이어색), color(유효색), path(상위 블록 경로 튜플)
"""
import math
import ezdxf
from ezdxf.math import Matrix44, Vec3


def layer_colors(doc):
    d = {}
    for ly in doc.layers:
        d[ly.dxf.name] = ly.dxf.color
    d["__lt__"] = {ly.dxf.name: ly.dxf.linetype for ly in doc.layers}  # 레이어 선종류(유효 선종류 계산용)
    return d


def eff_linetype(e, lcolors, parent_lt):
    lt = e.dxf.linetype if e.dxf.hasattr("linetype") else "BYLAYER"
    u = lt.upper()
    if u == "BYLAYER":
        return lcolors.get("__lt__", {}).get(e.dxf.layer, "Continuous")
    if u == "BYBLOCK":
        return parent_lt if parent_lt else "Continuous"
    return lt


def eff_color(e, lcolors, parent_color, parent_layer_color):
    c = e.dxf.color if e.dxf.hasattr("color") else 256
    ly = e.dxf.layer
    if c == 256:  # bylayer
        if ly == "0" and parent_layer_color is not None:
            return parent_layer_color
        return lcolors.get(ly, 7)
    if c == 0:  # byblock
        return parent_color if parent_color is not None else 7
    return c


def _tp(m, x, y):
    v = m.transform(Vec3(x, y, 0))
    return v.x, v.y


def _mat_info(m):
    """회전각(도)·균일 스케일·미러 여부 추정"""
    ux = m.transform_direction(Vec3(1, 0, 0))
    uy = m.transform_direction(Vec3(0, 1, 0))
    sx = ux.magnitude
    sy = uy.magnitude
    rot = math.degrees(math.atan2(ux.y, ux.x))
    mirror = (ux.x * uy.y - ux.y * uy.x) < 0
    return rot, sx, sy, mirror


def _clip_polygon(insert, m):
    """INSERT 의 XCLIP 경계(WCS) 를 현재 변환 m 으로 옮긴 꼭짓점 배열. 클립 없음/꺼짐이면 None."""
    try:
        from ezdxf.xclip import XClip
        c = XClip(insert)
        if not (c.has_clipping_path and c.is_clipping_enabled):
            return None
        p = c.get_wcs_clipping_path()
        if p.is_inverted_clip or len(p.vertices) < 3:
            return None
        import numpy as _np
        return _np.array([_tp(m, v.x, v.y) for v in p.vertices], dtype=float)
    except Exception:
        return None


def _content_center(prims):
    """프리미티브 묶음의 대표점 평균과 범위 (cx, cy, w, h) (없으면 None)"""
    xs = []; ys = []
    for p in prims:
        k = p["kind"]
        if k == "LINE":
            xs += [p["x1"], p["x2"]]; ys += [p["y1"], p["y2"]]
        elif k == "POLY" and p["pts"]:
            xs += [q[0] for q in p["pts"]]; ys += [q[1] for q in p["pts"]]
        elif k in ("ARC", "CIRCLE"):
            xs.append(p["cx"]); ys.append(p["cy"])
        elif k in ("TEXT", "INSERT"):
            xs.append(p["x"]); ys.append(p["y"])
    if not xs:
        return None
    return (sum(xs) / len(xs), sum(ys) / len(ys), max(xs) - min(xs), max(ys) - min(ys))


def _clip_prims(prims, poly):
    """프리미티브 대표점(선=중점·양끝, 폴리=꼭짓점, 원호=중심, 문자=삽입점) 중 하나라도 폴리곤 안이면 유지."""
    from matplotlib.path import Path as _Path
    import numpy as _np
    P = _Path(poly)
    keep = []
    for p in prims:
        k = p["kind"]
        if k == "LINE":
            pts = [(p["x1"], p["y1"]), (p["x2"], p["y2"]), ((p["x1"] + p["x2"]) / 2, (p["y1"] + p["y2"]) / 2)]
        elif k == "POLY":
            pts = [(q[0], q[1]) for q in p["pts"]]
        elif k in ("ARC", "CIRCLE"):
            pts = [(p["cx"], p["cy"])]
        elif k in ("TEXT", "INSERT", "INSTANCE"):
            pts = [(p["x"], p["y"])]
        else:
            keep.append(p); continue
        if P.contains_points(_np.array(pts)).any():
            keep.append(p)
    return keep


def flatten(doc, entities, out, m=None, path=(), depth=0, max_depth=8, lcolors=None,
            parent_color=None, parent_layer_color=None, keep_insert=None, max_entities=None, parent_lt=None):
    """entities 를 행렬 m 으로 변환해 out 리스트에 프리미티브 추가. keep_insert(name)->True 면 전개 안 함."""
    if lcolors is None:
        lcolors = layer_colors(doc)
    if m is None:
        m = Matrix44()
    rot, sx, sy, mirror = _mat_info(m)
    for e in entities:
        t = e.dxftype()
        ly = e.dxf.layer
        col = eff_color(e, lcolors, parent_color, parent_layer_color)
        elt = eff_linetype(e, lcolors, parent_lt)
        base = {"layer": ly, "lcolor": lcolors.get(ly, 7), "color": col, "lt": elt, "path": path}
        try:
            if t == "LINE":
                x1, y1 = _tp(m, e.dxf.start.x, e.dxf.start.y)
                x2, y2 = _tp(m, e.dxf.end.x, e.dxf.end.y)
                out.append({**base, "kind": "LINE", "x1": x1, "y1": y1, "x2": x2, "y2": y2})
            elif t == "LWPOLYLINE":
                pts = []
                for x, y, b in e.get_points("xyb"):
                    tx, ty = _tp(m, x, y)
                    pts.append([tx, ty, -b if mirror else b])
                out.append({**base, "kind": "POLY", "pts": pts, "closed": bool(e.closed)})
            elif t == "POLYLINE" and e.is_2d_polyline:
                pts = []
                for v in e.vertices:
                    tx, ty = _tp(m, v.dxf.location.x, v.dxf.location.y)
                    b = v.dxf.bulge if v.dxf.hasattr("bulge") else 0.0
                    pts.append([tx, ty, -b if mirror else b])
                out.append({**base, "kind": "POLY", "pts": pts, "closed": bool(e.is_closed)})
            elif t == "MLINE":  # 다중선(구조도 거더·보): 중심 꺾은선 + 폭(mw)
                pts = []
                for v in e.vertices:
                    tx, ty = _tp(m, v.location.x, v.location.y)
                    pts.append([tx, ty, 0.0])
                if len(pts) >= 2:
                    out.append({**base, "kind": "POLY", "pts": pts, "closed": bool(e.is_closed), "mline": True,
                                "mw": float(e.dxf.get("scale_factor", 0.0)) * sx})
            elif t == "ARC":
                cx, cy = _tp(m, e.dxf.center.x, e.dxf.center.y)
                r = e.dxf.radius * sx
                a1, a2 = e.dxf.start_angle, e.dxf.end_angle
                if mirror:
                    # x 축 미러(스케일 -1) 가정: 각도 반전
                    a1, a2 = 180 - a2, 180 - a1
                out.append({**base, "kind": "ARC", "cx": cx, "cy": cy, "r": r, "a1": (a1 + rot) % 360, "a2": (a2 + rot) % 360})
            elif t == "CIRCLE":
                cx, cy = _tp(m, e.dxf.center.x, e.dxf.center.y)
                out.append({**base, "kind": "CIRCLE", "cx": cx, "cy": cy, "r": e.dxf.radius * sx})
            elif t in ("TEXT", "ATTRIB", "ATTDEF"):
                if t == "ATTDEF":
                    continue
                x, y = _tp(m, e.dxf.insert.x, e.dxf.insert.y)
                out.append({**base, "kind": "TEXT", "x": x, "y": y, "h": e.dxf.height * sx, "s": e.dxf.text,
                            "rot": (e.dxf.rotation + rot) % 360})
            elif t == "MTEXT":
                x, y = _tp(m, e.dxf.insert.x, e.dxf.insert.y)
                out.append({**base, "kind": "TEXT", "x": x, "y": y, "h": e.dxf.char_height * sx, "s": e.plain_text()[:200],
                            "rot": (e.dxf.rotation + rot) % 360, "mtext": True})
            elif t == "INSERT":
                name = e.dxf.name
                x, y = _tp(m, e.dxf.insert.x, e.dxf.insert.y)
                if depth >= max_depth or (keep_insert and keep_insert(name)) or name not in doc.blocks:
                    out.append({**base, "kind": "INSERT", "name": name, "x": x, "y": y})
                    continue
                blk = doc.blocks[name]
                m2 = e.matrix44() * m
                # 속성(ATTRIB)
                for a in e.attribs:
                    ax, ay = _tp(m, a.dxf.insert.x, a.dxf.insert.y)
                    out.append({"layer": a.dxf.layer, "lcolor": lcolors.get(a.dxf.layer, 7), "color": 7, "path": path + (name,),
                                "kind": "TEXT", "x": ax, "y": ay, "h": a.dxf.height * sx, "s": a.dxf.text, "rot": (a.dxf.rotation + rot) % 360})
                ins_lc = lcolors.get(ly, 7) if ly != "0" else (parent_layer_color if parent_layer_color is not None else 7)
                clip = _clip_polygon(e, m)
                tmp = []
                flatten(doc, blk, tmp, m2, path + (name,), depth + 1, max_depth, lcolors, col, ins_lc, keep_insert, max_entities, elt)
                if clip is not None:  # XCLIP: 블록 내용을 전개한 뒤 클립 폴리곤 안(대표점 기준)만 남김
                    tmp = _clip_prims(tmp, clip)
                cxy = _content_center(tmp)
                if cxy is not None:  # 전개된 블록 인스턴스 기록(내용 중심·크기, 반복 부품 블록 판정용)
                    out.append({"layer": ly, "lcolor": lcolors.get(ly, 7), "color": col, "lt": elt, "path": path,
                                "kind": "INSTANCE", "name": name, "x": cxy[0], "y": cxy[1], "w": cxy[2], "h": cxy[3], "n": len(tmp)})
                out.extend(tmp)
            # DIMENSION/HATCH/SOLID/ELLIPSE/SPLINE 등은 무시
        except Exception as ex:  # 손상 엔티티 무시
            out.append({**base, "kind": "ERR", "msg": str(ex)[:80], "t": t})
        if max_entities and len(out) > max_entities:
            break
    return out
