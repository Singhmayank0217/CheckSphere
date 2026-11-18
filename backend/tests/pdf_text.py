"""Readable text of a ReportLab PDF, including text set in embedded TrueType subsets (decoded via each font's
ToUnicode map). Test helper only; no third-party PDF library needed."""
import base64
import re
import zlib


def _objects(pdf: bytes) -> dict:
    out = {}
    for m in re.finditer(rb"(\d+) 0 obj\s*(.*?)endobj", pdf, re.S):
        out[int(m.group(1))] = m.group(2)
    return out


def _stream(obj: bytes) -> bytes:
    m = re.search(rb"stream\r?\n(.*?)(?:\r?\n)?endstream", obj, re.S)  # ReportLab writes no line end before endstream
    if not m:
        return b""
    body = m.group(1)
    if b"ASCII85Decode" in obj[:m.start()]:
        body = body.strip()
        body = base64.a85decode(body[:-2] if body.endswith(b"~>") else body)
    if b"FlateDecode" in obj[:m.start()]:
        try:
            body = zlib.decompressobj().decompress(body)  # tolerant of the line end before "endstream"
        except zlib.error:
            return b""
    return body


def _cmap(data: bytes) -> dict:
    cmap = {}
    for block in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
        for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            cmap[int(src, 16)] = bytes.fromhex(dst.decode()).decode("utf-16-be", "ignore")
    for block in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
        for a, b, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            start = int(dst, 16)
            for i, code in enumerate(range(int(a, 16), int(b, 16) + 1)):
                cmap[code] = chr(start + i)
    return cmap


def _unescape(s: bytes) -> bytes:
    out, i = bytearray(), 0
    while i < len(s):
        c = s[i]
        if c == 0x5C and i + 1 < len(s):  # backslash
            n = s[i + 1]
            if 0x30 <= n <= 0x37:
                j = i + 1
                while j < len(s) and j < i + 4 and 0x30 <= s[j] <= 0x37:
                    j += 1
                out.append(int(s[i + 1:j], 8) & 0xFF)
                i = j
                continue
            out.append({ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}.get(n, n))
            i += 2
            continue
        out.append(c)
        i += 1
    return bytes(out)


def pdf_text(pdf: bytes) -> str:
    objs = _objects(pdf)
    font_maps = {}  # resource name -> cmap (None = plain single-byte text)
    font_dicts = []
    for body in objs.values():
        fd = re.search(rb"/Font\s*<<(.*?)>>", body, re.S)
        if fd:
            font_dicts.append(fd.group(1))
        ref = re.search(rb"/Font\s+(\d+)\s+0\s+R", body)
        if ref:
            font_dicts.append(objs.get(int(ref.group(1)), b""))
    for fd in font_dicts:
        for name, ref in re.findall(rb"/([\w+.-]+)\s+(\d+)\s+0\s+R", fd):
            fobj = objs.get(int(ref), b"")
            tu = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", fobj)
            font_maps[name.decode()] = _cmap(_stream(objs.get(int(tu.group(1)), b""))) if tu else None
    texts = []
    for body in objs.values():
        if b"stream" not in body or b"/Subtype /Image" in body or b"/Length1" in body:
            continue
        data = _stream(body)
        if b"Tj" not in data and b"TJ" not in data:
            continue
        cmap = None
        for tok in re.finditer(rb"/([\w+.-]+)\s+[\d.]+\s+Tf|\(((?:\\.|[^\\)])*)\)\s*Tj", data, re.S):
            if tok.group(1):
                cmap = font_maps.get(tok.group(1).decode())
                continue
            raw = _unescape(tok.group(2))
            texts.append("".join(cmap.get(b, "") for b in raw) if cmap else raw.decode("latin-1", "ignore"))
    return " ".join(texts)
