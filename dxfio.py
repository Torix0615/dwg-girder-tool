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
    return d


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


def flatten(doc, entities, out, m=None, path=(), depth=0, max_depth=8, lcolors=None,
            parent_color=None, parent_layer_color=None, keep_insert=None, max_entities=None):
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
        base = {"layer": ly, "lcolor": lcolors.get(ly, 7), "color": col, "path": path}
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
                flatten(doc, blk, out, m2, path + (name,), depth + 1, max_depth, lcolors, col, ins_lc, keep_insert, max_entities)
            # DIMENSION/HATCH/SOLID/ELLIPSE/SPLINE 등은 무시
        except Exception as ex:  # 손상 엔티티 무시
            out.append({**base, "kind": "ERR", "msg": str(ex)[:80], "t": t})
        if max_entities and len(out) > max_entities:
            break
    return out
