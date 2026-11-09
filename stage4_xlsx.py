"""최소 xlsx 작성기(표준 라이브러리 zipfile 만, openpyxl 없는 배포 런타임용).
write_xlsx(path, sheets) — sheets = [{"name": 시트명, "rows": [[셀, ...], ...], "widths": [열 너비, ...], "freeze": 1}]
셀 = 값(str/int/float/None) 또는 (값, 스타일번호). 스타일: 0 기본, 1 머리글(굵게·회색 바탕), 2 NG(빨강 바탕), 3 OK(초록 바탕), 4 주의(노랑 바탕), 5 줄바꿈 문자.
"""
import zipfile, re
from xml.sax.saxutils import escape

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="2"><font><sz val="10"/><name val="맑은 고딕"/></font><font><b/><sz val="10"/><name val="맑은 고딕"/></font></fonts>
<fills count="6"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFD9D9D9"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFFFC7CE"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFC6EFCE"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFFFEB9C"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>
<border><left style="thin"><color rgb="FFBFBFBF"/></left><right style="thin"><color rgb="FFBFBFBF"/></right><top style="thin"><color rgb="FFBFBFBF"/></top><bottom style="thin"><color rgb="FFBFBFBF"/></bottom><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="6">
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="1" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center"/></xf>
<xf numFmtId="0" fontId="0" fillId="4" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center"/></xf>
<xf numFmtId="0" fontId="0" fillId="5" borderId="1" xfId="0" applyFill="1" applyBorder="1"/>
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def _col(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26); s = chr(65 + r) + s
    return s


def _cell(ref, v, st):
    s_attr = f' s="{st}"' if st else ""
    if v is None or v == "":
        return f'<c r="{ref}"{s_attr}/>' if st else ""
    if isinstance(v, bool):
        return f'<c r="{ref}" t="b"{s_attr}><v>{int(v)}</v></c>'
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
            v = "∞" if v > 0 else "-∞"
        else:
            return f'<c r="{ref}"{s_attr}><v>{v}</v></c>'
    txt = escape(str(v)); txt = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", txt)
    sp = ' xml:space="preserve"' if txt != txt.strip() or "\n" in txt else ""
    return f'<c r="{ref}" t="inlineStr"{s_attr}><is><t{sp}>{txt}</t></is></c>'


def _sheet_xml(sh):
    rows = sh.get("rows", []); widths = sh.get("widths") or []; freeze = sh.get("freeze", 0)
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">']
    if freeze:
        out.append(f'<sheetViews><sheetView workbookViewId="0"><pane ySplit="{freeze}" topLeftCell="A{freeze+1}" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>')
    if widths:
        out.append("<cols>" + "".join(f'<col min="{i+1}" max="{i+1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths)) + "</cols>")
    out.append("<sheetData>")
    for r, row in enumerate(rows, 1):
        cells = []
        for c, v in enumerate(row, 1):
            st = 0
            if isinstance(v, tuple):
                v, st = v
            cells.append(_cell(f"{_col(c)}{r}", v, st))
        out.append(f'<row r="{r}">' + "".join(cells) + "</row>")
    out.append("</sheetData>")
    if freeze:
        out.append(f'<autoFilter ref="A{freeze}:{_col(max(1, max((len(r) for r in rows), default=1)))}{max(freeze, len(rows))}"/>')
    out.append("</worksheet>")
    return "\n".join(out)


def write_xlsx(path, sheets):
    names = [re.sub(r"[\[\]\*\?/\\:]", "_", str(s.get("name") or f"Sheet{i+1}"))[:31] for i, s in enumerate(sheets)]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(len(sheets)))
                   + "</Types>")
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(n)}" sheetId="{i+1}" r:id="rId{i+1}"/>' for i, n in enumerate(names))
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i+1}.xml"/>' for i in range(len(sheets)))
                   + f'<Relationship Id="rId{len(sheets)+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   + "</Relationships>")
        z.writestr("xl/styles.xml", STYLES)
        for i, sh in enumerate(sheets):
            z.writestr(f"xl/worksheets/sheet{i+1}.xml", _sheet_xml(sh))


if __name__ == "__main__":
    import sys
    write_xlsx(sys.argv[1] if len(sys.argv) > 1 else "test.xlsx", [{"name": "검토결과", "freeze": 1, "widths": [8, 10, 12],
                "rows": [[("요소", 1), ("층", 1), ("판정", 1)], [1, "B2", ("OK", 2)], [2, "1F", ("NG", 3)], [3, "1F", ("주의", 4)]]}])
    print("ok")
