# -*- coding: utf-8 -*-
"""Y4：平台痕迹与泄漏扫描（只扫描、不删改）。
   1) 文本文件内容 == TEXT_FIELDS 拼接 的逐字节一致性（防止任何额外注入）
   2) 平台名 / 平台壳层文字 / 话题标签 命中清单
   3) 是否误含 record_id / 平台 token
"""
import os, csv, json, io, re, collections
import config as C

SRC = C.CLEAN_DIR
ROOT = C.DELIVERY_ROOT
TEXT_DIR = os.path.join(ROOT, C.D_SAMPLES, *C.D_STIM_TEXT.split("/"))
QA = os.path.join(ROOT, C.D_QC)
os.makedirs(QA, exist_ok=True)

PLATFORM_WORDS = list(C.PLATFORM_WORDS)
SHELL_PATTERNS = [
    ("转发链", re.compile(r"//\s*@")),
    ("@提及", re.compile(r"@[\w\u4e00-\u9fff\-_]{1,30}")),
    ("展开全文", re.compile(r"展开全文|收起全文|点击展开")),
    ("分享提示", re.compile(r"分享图片|分享至|转发微博|分享到")),
    ("话题标签", re.compile(r"#[^#\s]{1,30}#")),
    ("链接残留", re.compile(r"https?://|网页链接|戳链接|点击链接")),
    ("平台字段名", re.compile(r"\b(source_id|record_id|sample_id|image_files|cleaning_status)\b")),
]
if C.SCORING_TERMS:
    SHELL_PATTERNS.append(("评分维度词", re.compile("|".join(map(re.escape, C.SCORING_TERMS)))))

rows = {}
with open(os.path.join(SRC, "可用UGC.csv"), "r", encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        rows[r["record_id"]] = r

manifest = {}
with open(os.path.join(ROOT, C.D_SAMPLES, C.SAMPLE_MANIFEST_NAME), "r", encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        manifest[r["record_id"]] = r["sample_id"]

def build_text(r):
    parts = []
    for k in C.TEXT_FIELDS:
        v = (r.get(k) or "").strip()
        if v:
            parts.append(v)
    return "\n".join(parts)

hits = []
mismatch = []
cat_n = collections.Counter()
sample_n = set()

for rid, sid in sorted(manifest.items(), key=lambda x: x[1]):
    r = rows[rid]
    fp = os.path.join(TEXT_DIR, sid + ".txt")
    with io.open(fp, encoding="utf-8") as f:
        content = f.read()
    expect = build_text(r)
    if content != expect:
        mismatch.append({"sample_id": sid, "record_id": rid,
                         "diff": f"expect {len(expect)} chars, got {len(content)}"})
    for w in PLATFORM_WORDS:
        if w in content:
            i = content.find(w)
            hits.append({"sample_id": sid, "record_id": rid, "platform": r["platform"],
                         "类别": "平台名", "命中": w, "片段": content[max(0, i-20):i+20].replace("\n", " ")})
            cat_n["平台名"] += 1; sample_n.add(sid)
    for name, pat in SHELL_PATTERNS:
        for m in pat.finditer(content):
            i = m.start()
            hits.append({"sample_id": sid, "record_id": rid, "platform": r["platform"],
                         "类别": name, "命中": m.group(0)[:40],
                         "片段": content[max(0, i-20):i+40].replace("\n", " ")})
            cat_n[name] += 1; sample_n.add(sid)

out = os.path.join(QA, "平台痕迹扫描.csv")
with open(out, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["sample_id", "record_id", "platform", "类别", "命中", "片段"])
    w.writeheader(); w.writerows(hits)

print("文本一致性校验：不一致", len(mismatch), "条")
for m in mismatch[:5]:
    print("  ", m)
_total = max(len(manifest), 1)
print("\n命中总数:", len(hits), "  涉及样本:", len(sample_n), f"({len(sample_n)/_total*100:.1f}%)")
print("按类别:", dict(cat_n))
print("按平台:", dict(collections.Counter(h["platform"] for h in hits)))
print("写出:", out)

# 采集关键词是否混入：source_keywords 是采集元数据，若正文里出现是作者自己写的，属正常；
# 这里只统计"文本文件里出现了 source_keywords 的值"的比例，供人工判断
kw_hit = 0
for rid, sid in manifest.items():
    kws = json.loads(rows[rid].get("source_keywords") or "[]")
    with io.open(os.path.join(TEXT_DIR, sid + ".txt"), encoding="utf-8") as f:
        c = f.read()
    if kws and any(k in c for k in kws if len(k) >= 2):
        kw_hit += 1
print(f"\n正文中出现采集关键词的样本: {kw_hit}/{len(manifest)} ({kw_hit/_total*100:.1f}%) —— 属作者自述，非注入")
