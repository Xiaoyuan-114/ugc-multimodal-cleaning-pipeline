# -*- coding: utf-8 -*-
"""Step 1：输入盘点。产出 输入文件清单.csv 与 manifest_before.json。"""
import os, sys, csv, json, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import openpyxl

OUT_DIR = C.OUT_TMP
os.makedirs(OUT_DIR, exist_ok=True)

rows = []
manifest = {}

IMG_DIR_SET = set()
for dirs in C.IMAGE_DIRS.values():
    for d in dirs:
        IMG_DIR_SET.add(d.replace("\\", "/").lower())


def rel(p):
    return os.path.relpath(p, C.DATA).replace("\\", "/")


def walk_all():
    for dp, dn, fn in os.walk(C.DATA):
        for f in fn:
            yield os.path.join(dp, f)


def sheet_info(path):
    """返回 [(sheet_name, 行数, 列头, 判定, 原因)]"""
    out = []
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for ws in wb.worksheets:
        it = ws.iter_rows(values_only=True)
        try:
            hdr = next(it)
        except StopIteration:
            out.append((ws.title, 0, [], "空表", "工作表无任何内容"))
            continue
        hdr = list(hdr) if hdr else []
        n = 0
        for r in it:
            if r is None:
                continue
            if all(c is None or str(c).strip() == "" for c in r):
                continue
            n += 1
        h = set(str(x).strip() for x in hdr if x is not None)
        if any(c in h for c in C.SHEET_COMMENT_COLS):
            verdict, why = "评论表", "字段结构为评论数据（comment/parent_comment），不进入主要 UGC 数据"
        elif any(c in h for c in C.SHEET_BODY_ID_COLS) and any(c in h for c in C.SHEET_BODY_TEXT_COLS):
            verdict, why = "正文表", ""
        elif n == 0:
            verdict, why = "空表", "无有效数据行"
        else:
            verdict, why = "未识别", f"字段结构未匹配任何已知正文表：{sorted(h)[:12]}"
        out.append((ws.title, n, hdr, verdict, why))
    wb.close()
    return out


print("扫描文件…")
files = sorted(walk_all())
print(f"共 {len(files)} 个文件")

for i, fp in enumerate(files):
    r = rel(fp)
    name = os.path.basename(fp).lower()
    ext = os.path.splitext(fp)[1].lower()
    st = os.stat(fp)
    manifest[r] = {"size": st.st_size, "mtime": round(st.st_mtime, 3)}

    rel_dir = os.path.dirname(r)
    if name in C.SYSTEM_FILES:
        rows.append(dict(source_path=r, file_type="system", source_sheet="",
                         file_size=st.st_size, modified_time_before="", modified_time_after="",
                         discovery_status="skipped", included_in_cleaning="no",
                         skip_reason="操作系统生成的系统文件，非候选图片"))
        continue

    if r.lower() in C.SKIP_FILES:
        rows.append(dict(source_path=r, file_type="archive", source_sheet="",
                         file_size=st.st_size, modified_time_before="", modified_time_after="",
                         discovery_status="skipped", included_in_cleaning="no",
                         skip_reason=C.SKIP_FILES[r.lower()]))
        continue

    if ext in C.IMG_EXTS:
        rd = rel_dir.replace("\\", "/").lower()
        in_img_dir = any(rd == d or rd.startswith(d + "/") for d in IMG_DIR_SET)
        rows.append(dict(source_path=r, file_type="image", source_sheet="",
                         file_size=st.st_size, modified_time_before="", modified_time_after="",
                         discovery_status="scanned" if in_img_dir else "skipped",
                         included_in_cleaning="yes" if in_img_dir else "no",
                         skip_reason="" if in_img_dir else "不在已登记的平台图片目录内"))
        continue

    if ext == ".xlsx":
        for sheet, n, hdr, verdict, why in sheet_info(fp):
            is_body = verdict == "正文表"
            if os.path.basename(fp).lower() in C.SKIP_TABLES:
                is_body = False
                why = C.SKIP_TABLES[os.path.basename(fp).lower()]
                verdict = "评论表"
            elif verdict == "空表":
                is_body = False
            elif verdict == "未识别":
                is_body = False
            rows.append(dict(source_path=r, file_type="excel", source_sheet=sheet,
                             file_size=st.st_size, modified_time_before="", modified_time_after="",
                             discovery_status=f"{verdict}（{n} 行）",
                             included_in_cleaning="yes" if is_body else "no",
                             skip_reason="" if is_body else why))
        continue

    if ext == ".csv":
        base = os.path.basename(fp).lower()
        if base in C.SKIP_TABLES:
            rows.append(dict(source_path=r, file_type="csv", source_sheet="",
                             file_size=st.st_size, modified_time_before="", modified_time_after="",
                             discovery_status="skipped", included_in_cleaning="no",
                             skip_reason=C.SKIP_TABLES[base]))
        else:
            rows.append(dict(source_path=r, file_type="csv", source_sheet="",
                             file_size=st.st_size, modified_time_before="", modified_time_after="",
                             discovery_status="正文表", included_in_cleaning="yes", skip_reason=""))
        continue

    if ext in (".py", ".txt", ".md", ".json"):
        reason = "非 UGC 数据文件（脚本或说明文档），不参与清洗"
    elif ext in (".zip", ".rar", ".7z"):
        reason = "压缩包，不展开扫描（已在 SKIP_FILES 中登记的除外）"
    else:
        reason = f"未识别的文件类型（{ext or '无扩展名'}）"
    rows.append(dict(source_path=r, file_type=ext.lstrip(".") or "unknown", source_sheet="",
                     file_size=st.st_size, modified_time_before="", modified_time_after="",
                     discovery_status="skipped", included_in_cleaning="no",
                     skip_reason=reason))

    if i % 5000 == 0:
        print(f"  …{i}/{len(files)}")

COLS = ["source_path", "file_type", "source_sheet", "file_size", "modified_time_before",
        "modified_time_after", "discovery_status", "included_in_cleaning", "skip_reason"]

out_csv = os.path.join(OUT_DIR, "输入文件清单.csv")
with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=COLS)
    w.writeheader()
    w.writerows(rows)

with open(os.path.join(C.INTERIM, "manifest_before.json"), "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False)

print(f"\n输入文件清单.csv 已写出：{len(rows)} 行")
import collections
print("file_type 分布:", dict(collections.Counter(x["file_type"] for x in rows)))
print("included 分布:", dict(collections.Counter(x["included_in_cleaning"] for x in rows)))
print("跳过的表：")
for x in rows:
    if x["file_type"] in ("excel", "csv", "archive", "system") and x["included_in_cleaning"] == "no":
        print(f"   {x['source_path']} [{x['source_sheet']}] {x['discovery_status']} → {x['skip_reason'][:60]}")
print("\n纳入清洗的表：")
for x in rows:
    if x["file_type"] in ("excel", "csv") and x["included_in_cleaning"] == "yes":
        print(f"   {x['source_path']} [{x['source_sheet']}] {x['discovery_status']}")
