# -*- coding: utf-8 -*-
"""Step 3：表格解析、字段核实、规范 UGC 合并、图片文件夹索引。
产出 interim/raw_rows.jsonl、interim/canonical_ugc.json、原始记录映射.csv"""
import os, sys, csv, json, re, hashlib, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import openpyxl

OUT_DIR = C.OUT_TMP
os.makedirs(OUT_DIR, exist_ok=True)
INTERIM = C.INTERIM

# ---------------------------------------------------------------- 文本处理
SHELL_LINE_PATTERNS = [
    re.compile(r"^展开全文$"), re.compile(r"^收起$"), re.compile(r"^展开$"),
    re.compile(r"^全文$"), re.compile(r"^点击查看更多$"), re.compile(r"^阅读全文$"),
]
SHELL_SUBSTR = ["网页链接"]          # 微博的裸链接占位文字
REMOVAL_LOG = collections.Counter()


def normalize_ws(t):
    if not t:
        return ""
    t = str(t).replace("\r\n", "\n").replace("\r", "\n")
    t = t.replace("\u3000", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def clean_text(t):
    """保守清洗：仅处理空白、明确平台壳层、纯占位链接、完全重复段落。"""
    t = normalize_ws(t)
    if not t:
        return ""
    paras = t.split("\n")
    out, seen = [], set()
    for p in paras:
        s = p.strip()
        if not s:
            out.append("")
            continue
        if any(r.match(s) for r in SHELL_LINE_PATTERNS):
            REMOVAL_LOG["shell_line"] += 1
            continue
        if all(k in s for k in ("网页链接",)) and len(s) <= 12:
            REMOVAL_LOG["link_placeholder"] += 1
            continue
        if s in seen:
            REMOVAL_LOG["dup_paragraph"] += 1
            continue
        seen.add(s)
        out.append(s)
    res = "\n".join(out)
    res = re.sub(r"\n{3,}", "\n\n", res).strip()
    if res != t.strip():
        REMOVAL_LOG["changed_rows"] += 1
    return res


def split_repost(t, regex=r"//\s*@"):
    """按配置的正则切分“作者正文 / 转发引用”。"""
    if not t:
        return t, ""
    m = re.search(regex, t)
    if not m:
        return t, ""
    return t[: m.start()].strip(), t[m.start():].strip()


REPOST_SPLIT = dict(C.REPOST_SPLIT or {})
for _spec in C.TABLES:
    if _spec.get("repost_regex"):
        REPOST_SPLIT.setdefault(_spec["platform"], _spec["repost_regex"])


def norm_id(v):
    if v is None:
        return ""
    s = str(v).strip()
    if re.fullmatch(r"\d+\.0", s):
        s = s[:-2]
    return s


# ---------------------------------------------------------------- 读表
def read_xlsx_rows(path, sheet=None):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for ws in wb.worksheets:
        if sheet and ws.title != sheet:
            continue
        it = ws.iter_rows(values_only=True)
        try:
            hdr = list(next(it))
        except StopIteration:
            continue
        hdr = [str(h).strip() if h is not None else "" for h in hdr]
        rowno = 1
        for r in it:
            rowno += 1
            if r is None:
                continue
            if all(c is None or str(c).strip() == "" for c in r):
                continue
            yield ws.title, rowno, hdr, list(r)
    wb.close()


def read_csv_rows(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f)
        hdr = next(rd)
        hdr = [str(h).strip() for h in hdr]
        for i, r in enumerate(rd, start=2):
            if all(c is None or str(c).strip() == "" for c in r):
                continue
            yield "", i, hdr, list(r)


def col(row, hdr, name):
    try:
        i = hdr.index(name)
    except ValueError:
        return None
    return row[i] if i < len(row) else None


# ---------------------------------------------------------------- 表读取
def iter_table(spec):
    path = os.path.join(C.DATA, spec["path"])
    kind = (spec.get("kind") or os.path.splitext(path)[1].lstrip(".")).lower()
    if kind == "csv":
        yield from read_csv_rows(path)
    else:
        sheets = spec.get("sheets")
        for item in read_xlsx_rows(path):
            if sheets and item[0] not in sheets:
                continue
            yield item


# ---------------------------------------------------------------- 字段核实
def verify_columns(spec, a, b):
    """核实两列的取值分布是否与表头语义一致（用于发现表头写反）。"""
    samples = []
    for sheet, rowno, hdr, row in iter_table(spec):
        samples.append((col(row, hdr, a), col(row, hdr, b)))
        if len(samples) >= 400:
            break
    va = [str(x) for x, y in samples if x]
    vb = [str(y) for x, y in samples if y]
    return {
        "header_order": [a, b],
        f"col_{a}_unique": len(set(va)), f"col_{a}_samples": list(dict.fromkeys(va))[:6],
        f"col_{b}_unique": len(set(vb)), f"col_{b}_samples": list(dict.fromkeys(vb))[:6],
    }


# ---------------------------------------------------------------- 图片索引
def build_image_index():
    idx = collections.defaultdict(lambda: collections.defaultdict(list))
    stray = []
    for plat, dirs in C.IMAGE_DIRS.items():
        for d in dirs:
            base = os.path.join(C.DATA, d)
            if not os.path.isdir(base):
                continue
            for e in sorted(os.listdir(base)):
                ep = os.path.join(base, e)
                if os.path.isdir(ep):
                    files = []
                    for dp, dn, fn in os.walk(ep):
                        for f in sorted(fn):
                            rp = os.path.relpath(os.path.join(dp, f), C.DATA).replace("\\", "/")
                            files.append(rp)
                    idx[plat][e].append({"dir": os.path.relpath(ep, C.DATA).replace("\\", "/"),
                                         "files": sorted(files)})
                elif os.path.splitext(e)[1].lower() in C.IMG_EXTS:
                    stray.append(os.path.relpath(ep, C.DATA).replace("\\", "/"))
    return idx, stray


# ---------------------------------------------------------------- 主流程
def main():
    raw_rows = []
    field_notes = {}

    # ---- 按 config.TABLES 逐表读取
    for spec in C.TABLES:
        plat = spec["platform"]
        cols = spec.get("columns") or {}
        src = spec["path"].replace("\\", "/")
        swap_a = swap_b = None
        swapped = False
        if spec.get("swap_check"):
            swap_a, swap_b = spec["swap_check"]["a"], spec["swap_check"]["b"]
            v = verify_columns(spec, swap_a, swap_b)
            swapped = v[f"col_{swap_a}_unique"] > v[f"col_{swap_b}_unique"]
            field_notes[src] = {"verify": v, "swapped": swapped,
                                "rule": f"{swap_a} 取值种类 > {swap_b} 时视为表头写反"}
            print(f"[字段核实] {src}: {swap_a}={v[f'col_{swap_a}_unique']} 种 / "
                  f"{swap_b}={v[f'col_{swap_b}_unique']} 种 → "
                  f"{'表头与内容顺序相反，已按语义对调' if swapped else '顺序正确，不调整'}")

        for sheet, rowno, hdr, row in iter_table(spec):
            kw = col(row, hdr, cols["keyword"]) if cols.get("keyword") else None
            nk = col(row, hdr, swap_b) if swap_b else None
            if swapped:
                kw, nk = nk, kw
            note = (f"表头 {swap_a}/{swap_b} 与内容顺序相反，已按语义对调写入规范字段"
                    if swapped else "")
            raw_rows.append(dict(
                platform=plat, source_table=src, source_sheet=sheet or "", source_row_number=rowno,
                source_id_raw=col(row, hdr, cols.get("id")),
                source_id_normalized=norm_id(col(row, hdr, cols.get("id"))),
                title_raw=normalize_ws(col(row, hdr, cols["title"])) if cols.get("title") else "",
                text_raw=normalize_ws(col(row, hdr, cols["text"])) if cols.get("text") else "",
                source_keywords=[str(kw or "").strip()],
                field_mapping_notes=note,
                _raw_keyword=str(kw or "").strip(), _raw_nick=str(nk or "").strip()))

    print(f"\n原始表数据行合计：{len(raw_rows)}")
    print("  平台分布:", dict(collections.Counter(r["platform"] for r in raw_rows)))

    # ---- 缺失编码处理
    for r in raw_rows:
        if not r["source_id_normalized"]:
            basis = "|".join([r["source_table"], r["source_sheet"], str(r["source_row_number"]),
                              r["title_raw"], r["text_raw"]])
            h = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
            r["record_id"] = f"{C.PREFIX[r['platform']]}_MISSING_{h}"
            r["missing_source_id_flag"] = True
            r["record_id_basis"] = f"sha256(来源表|工作表|原始行号|标题|正文) 前16位 = {h}"
        else:
            r["record_id"] = f"{C.PREFIX[r['platform']]}_{r['source_id_normalized']}"
            r["missing_source_id_flag"] = False
            r["record_id_basis"] = ""

    # ---- 合并为规范 UGC
    groups = collections.defaultdict(list)
    for r in raw_rows:
        groups[(r["platform"], r["record_id"])].append(r)

    def effective_len(t):
        return len(t or "")

    canonical = []
    for (plat, rid), rows in groups.items():
        # 规则1：优先"标题与正文均非空"的版本
        both = [r for r in rows if r["title_raw"] and r["text_raw"]]
        pool = both if both else [r for r in rows if r["title_raw"] or r["text_raw"]]
        if not pool:
            pool = rows
        # 规则2、3：有效正文字符数最多 → 按来源表、工作表顺序、行号
        pool_sorted = sorted(pool, key=lambda r: (-effective_len(r["text_raw"]),
                                                  r["source_table"], r["source_sheet"],
                                                  r["source_row_number"]))
        pick = pool_sorted[0]

        texts = set(r["text_raw"] for r in rows if r["text_raw"])
        titles = set(r["title_raw"] for r in rows if r["title_raw"])
        conflict = len(texts) > 1 or len(titles) > 1

        repost = ""
        own = pick["text_raw"]
        if plat in REPOST_SPLIT:
            own, repost = split_repost(pick["text_raw"], REPOST_SPLIT[plat])

        keywords = []
        for r in rows:
            for k in r["source_keywords"]:
                if k and k not in keywords:
                    keywords.append(k)

        canonical.append(dict(
            platform=plat, record_id=rid, source_id=pick["source_id_normalized"],
            title_raw=pick["title_raw"], text_raw=own, repost_text_raw=repost,
            text_clean=clean_text(own),
            source_tables=sorted(set(r["source_table"] for r in rows)),
            source_sheets=sorted(set(r["source_sheet"] for r in rows)),
            source_keywords=keywords,
            merged_row_count=len(rows),
            merge_conflict_flag=conflict,
            missing_source_id_flag=pick["missing_source_id_flag"],
            text_variants=[{"source_table": r["source_table"], "source_sheet": r["source_sheet"],
                            "source_row_number": r["source_row_number"],
                            "title_raw": r["title_raw"], "text_raw": r["text_raw"],
                            "source_keywords": r["source_keywords"]}
                           for r in sorted(rows, key=lambda r: (r["source_table"], r["source_sheet"],
                                                                r["source_row_number"]))],
            field_mapping_notes=sorted(set(r["field_mapping_notes"] for r in rows if r["field_mapping_notes"])),
        ))

    print(f"规范 UGC 数：{len(canonical)}")
    print("  平台分布:", dict(collections.Counter(c["platform"] for c in canonical)))
    print("  合并冲突条数:", sum(1 for c in canonical if c["merge_conflict_flag"]))
    print("  缺失编码条数:", sum(1 for c in canonical if c["missing_source_id_flag"]))
    print("  文本清洗改动行数:", dict(REMOVAL_LOG))

    # ---- 图片索引
    idx, stray = build_image_index()
    print(f"\n图片文件夹：", {k: len(v) for k, v in idx.items()})
    print(f"散图（直接位于平台图片目录下、无编码子文件夹）：{len(stray)}", stray[:5])

    canon_ids = {c["platform"]: set() for c in canonical}
    for c in canonical:
        canon_ids[c["platform"]].add(c["source_id"])
    orphan_report = {}
    for plat, m in idx.items():
        orphan = sorted(set(m.keys()) - {i for i in canon_ids[plat] if i})
        orphan_report[plat] = orphan
        print(f"  {plat}: 文件夹 {len(m)} 个，孤立（表中无对应正文）{len(orphan)} 个 {orphan[:5]}")
    noimg = {plat: len([i for i in ids if i and i not in idx.get(plat, {})]) for plat, ids in canon_ids.items()}
    print(f"  有编码但无图片文件夹：{noimg}")

    # ---- 落盘
    with open(os.path.join(INTERIM, "raw_rows.jsonl"), "w", encoding="utf-8") as f:
        for r in raw_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(INTERIM, "canonical_ugc.json"), "w", encoding="utf-8") as f:
        json.dump(canonical, f, ensure_ascii=False)
    with open(os.path.join(INTERIM, "image_index.json"), "w", encoding="utf-8") as f:
        json.dump({"index": {p: {k: v for k, v in m.items()} for p, m in idx.items()},
                   "stray": stray, "orphan": orphan_report}, f, ensure_ascii=False)
    with open(os.path.join(INTERIM, "field_verify.json"), "w", encoding="utf-8") as f:
        json.dump(field_notes, f, ensure_ascii=False, indent=2)

    # ---- 原始记录映射.csv
    canon_pick = {}
    for c in canonical:
        canon_pick[(c["platform"], c["record_id"])] = c["title_raw"] + "\x00" + c["text_raw"]
    COLS = ["platform", "source_table", "source_sheet", "source_row_number", "source_id_raw",
            "source_id_normalized", "record_id", "record_action", "selected_as_canonical",
            "merge_conflict_flag", "title_raw", "text_raw", "source_keywords", "field_mapping_notes"]
    with open(os.path.join(OUT_DIR, "原始记录映射.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in sorted(raw_rows, key=lambda r: (r["platform"], r["source_table"], r["source_sheet"],
                                                 r["source_row_number"])):
            key = (r["platform"], r["record_id"])
            sel = canon_pick.get(key, "") == (r["title_raw"] + "\x00" + r["text_raw"])
            notes = r["field_mapping_notes"]
            if r["record_id_basis"]:
                notes = (notes + " | " if notes else "") + "缺失编码临时 record_id 生成依据：" + r["record_id_basis"]
            w.writerow({
                "platform": r["platform"], "source_table": r["source_table"],
                "source_sheet": r["source_sheet"], "source_row_number": r["source_row_number"],
                "source_id_raw": "" if r["source_id_raw"] is None else str(r["source_id_raw"]),
                "source_id_normalized": r["source_id_normalized"], "record_id": r["record_id"],
                "record_action": "canonical" if sel else "merged_reference",
                "selected_as_canonical": "true" if sel else "false",
                "merge_conflict_flag": "true" if any(c["record_id"] == r["record_id"] and
                                                     c["merge_conflict_flag"] for c in canonical) else "false",
                "title_raw": r["title_raw"], "text_raw": r["text_raw"],
                "source_keywords": json.dumps(r["source_keywords"], ensure_ascii=False),
                "field_mapping_notes": notes,
            })
    print(f"\n原始记录映射.csv 已写出：{len(raw_rows)} 行")


if __name__ == "__main__":
    main()
