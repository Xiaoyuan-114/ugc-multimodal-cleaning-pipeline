# -*- coding: utf-8 -*-
"""Y1：生成样本清单 + 文本材料。原始数据只读。"""
import os, csv, json, io, collections
import config as C

SRC = C.CLEAN_DIR
ROOT = C.DELIVERY_ROOT
SAMPLE_DIR = os.path.join(ROOT, C.D_SAMPLES)
TEXT_DIR = os.path.join(ROOT, C.D_SAMPLES, *C.D_STIM_TEXT.split("/"))
os.makedirs(TEXT_DIR, exist_ok=True)

LANDMARKS = list(C.LANDMARK_TOKENS)
GENERIC = set(C.GENERIC_PLACE_TOKENS)

rows = []
with open(os.path.join(SRC, "可用UGC.csv"), "r", encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

print("读入可用 UGC:", len(rows))
print("repost_text_raw 非空:", sum(1 for r in rows if (r.get("repost_text_raw") or "").strip()))
print("title_raw 非空:", sum(1 for r in rows if (r.get("title_raw") or "").strip()))

# 稳定排序：platform 升序 → record_id 升序
rows.sort(key=lambda r: (r["platform"], r["record_id"]))

def build_text(r):
    """材料正文：按 TEXT_FIELDS 拼接，不含采集关键词/平台信息。"""
    parts = []
    for k in C.TEXT_FIELDS:
        v = (r.get(k) or "").strip()
        if v:
            parts.append(v)
    return "\n".join(parts)

manifest = []
ledger = []
for i, r in enumerate(rows, start=1):
    sid = f"{i:04d}"
    imgs = json.loads(r.get("image_files") or "[]")
    txt = build_text(r)
    fp = os.path.join(TEXT_DIR, sid + ".txt")
    with io.open(fp, "w", encoding="utf-8", newline="\n") as f:   # 无 BOM，LF 换行
        f.write(txt)
    blob = "\n".join((r.get(k) or "") for k in C.TEXT_FIELDS)
    hits = [t for t in LANDMARKS if t in blob]
    spec = [t for t in hits if t not in GENERIC]
    manifest.append({
        "sample_id": sid,
        "record_id": r["record_id"],
        "platform": r["platform"],
        "has_image": 1 if imgs else 0,
        "image_count": len(imgs),
        "text_len": len(txt),
        "landmark_any": "|".join(hits),
        "landmark_specific": "|".join(spec),
    })
    ledger.append({"sample_id": sid, "record_id": r["record_id"], "image_files": imgs})

# 样本清单.csv（UTF-8 with BOM，Excel 可直接打开）
mf = os.path.join(SAMPLE_DIR, C.SAMPLE_MANIFEST_NAME)
with open(mf, "w", encoding="utf-8-sig", newline="") as f:
    fields = list(manifest[0].keys()) if manifest else [
        "sample_id", "record_id", "platform", "has_image", "image_count",
        "text_len", "landmark_any", "landmark_specific"]
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader(); w.writerows(manifest)

print("样本清单:", mf, len(manifest), "行")
print("文本文件:", len(os.listdir(TEXT_DIR)))
print("有图:", sum(1 for m in manifest if m["has_image"]), " 纯文本:", sum(1 for m in manifest if not m["has_image"]))
print("前 3 条:", manifest[:3])
print("图片引用数:", sum(len(l["image_files"]) for l in ledger))

# 中间件给下一步（图片重编码）用
with io.open(os.path.join(C.WORK, "_ledger.json"), "w", encoding="utf-8") as f:
    json.dump(ledger, f, ensure_ascii=False)
print("ledger 已写:", os.path.join(C.WORK, "_ledger.json"))
