"""외부참조(XREF) 결합: 마스터 DXF 의 XREF 블록 정의에 참조 파일의 모델공간을 심어 일반 블록으로 만든다(바인딩).
python xref_bind.py <master.dxf> <out.dxf> [--dirs 폴더;폴더...] [--work 임시폴더]
- 참조 경로가 절대경로(Z:\...)여도 파일 이름으로 --dirs(기본: 마스터 폴더·원본 DWG 폴더·그 아래 XREF 폴더)에서 찾는다.
- .dwg 참조는 dwg2dxf 로 임시 변환해 읽는다. INSERT 의 XCLIP 은 그대로 남으며 dump.py(dxfio.flatten)가 전개 때 잘라낸다.
- 찾지 못한 참조는 건너뛰고(빈 블록 유지) 이름을 보고한다. 종료 코드 0, 출력 마지막 줄 BOUND=<결합 수> MISSING=<이름들>
"""
import sys, os, subprocess, argparse, pathlib
import ezdxf
from ezdxf import xref

HERE = os.path.dirname(os.path.abspath(__file__))
_cands = [os.path.join(os.path.dirname(sys.executable), "dwg2dxf.exe"), os.path.join(os.path.dirname(HERE), "runtime", "dwg2dxf.exe"),
          os.path.join(os.path.dirname(HERE), "libredwg", "dwg2dxf.exe")]
DWG2DXF = next((p for p in _cands if os.path.exists(p)), _cands[-1])


def list_xrefs(doc):
    """[(블록 이름, xref_path)]"""
    out = []
    for b in doc.blocks:
        try:
            if b.block.is_xref:
                out.append((b.name, b.block.dxf.get("xref_path", "")))
        except Exception:
            pass
    return out


def make_loader(work):
    os.makedirs(work, exist_ok=True)

    def load(path):
        p = str(path)
        if p.lower().endswith(".dwg"):
            dxf = os.path.join(work, pathlib.Path(p).stem + "_xref.dxf")
            if not os.path.exists(dxf):
                r = subprocess.run([DWG2DXF, "-y", "-o", dxf, p], capture_output=True, text=True, encoding="utf-8", errors="replace")
                if not os.path.exists(dxf):
                    raise FileNotFoundError(f"dwg2dxf 실패: {p}\n{r.stderr[-500:]}")
            p = dxf
        return ezdxf.readfile(p)
    return load


def bind(doc, search_dirs, work):
    xrefs = list_xrefs(doc)
    bound, missing = [], []
    paths = [pathlib.Path(d) for d in search_dirs if d and os.path.isdir(d)]
    load = make_loader(work)
    for name, xpath in xrefs:
        blk = doc.blocks[name]
        try:
            xref.embed(blk, load_fn=load, search_paths=paths)
            n = len(list(blk))
            bound.append((name, n))
            print(f"XREF 결합: {name} ← {os.path.basename(xpath)} ({n} 엔티티)", flush=True)
        except FileNotFoundError:
            missing.append(name)
            print(f"XREF 없음(건너뜀): {name} ← {xpath}", flush=True)
        except Exception as e:  # 손상·버전 문제
            missing.append(name)
            print(f"XREF 결합 실패(건너뜀): {name}: {type(e).__name__} {str(e)[:120]}", flush=True)
    return bound, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--dirs", default="", help="참조 파일을 찾을 폴더(; 구분)")
    ap.add_argument("--work", default=None)
    a = ap.parse_args()
    doc = ezdxf.readfile(a.src)
    xrefs = list_xrefs(doc)
    if not xrefs:
        print("XREF 없음"); print("BOUND=0 MISSING="); return
    dirs = [d for d in a.dirs.split(";") if d] + [os.path.dirname(os.path.abspath(a.src))]
    extra = []
    for d in dirs:
        for sub in ("XREF", "xref", "Xref"):
            if os.path.isdir(os.path.join(d, sub)):
                extra.append(os.path.join(d, sub))
    work = a.work or os.path.join(os.path.dirname(os.path.abspath(a.out)), "xref_tmp")
    bound, missing = bind(doc, dirs + extra, work)
    if bound:
        try:  # LibreDWG 변환 DXF 의 ACAD_MATERIAL 미해결 핸들 제거(저장 실패 방지)
            od = doc.materials.object_dict
            for k in [k for k, v in list(od.items()) if isinstance(v, str)]:
                od.remove(k)
        except Exception as ex:
            print("materials 정리 생략:", ex)
        doc.saveas(a.out)
        print(f"saved {a.out}")
    print(f"BOUND={len(bound)} MISSING={','.join(missing)}")


if __name__ == "__main__":
    main()
