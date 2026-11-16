# -*- coding: utf-8 -*-
"""Y5：自检 + 生成 材料台账.csv + 自检报告.md"""
import os, io, csv, json, random, hashlib, collections, datetime
from PIL import Image
import config as C

SRC = C.CLEAN_DIR
ROOT = C.DELIVERY_ROOT
SAMPLES = os.path.join(ROOT, C.D_SAMPLES)
TEXT_DIR = os.path.join(ROOT, C.D_SAMPLES, *C.D_STIM_TEXT.split("/"))
IMG_ROOT = os.path.join(ROOT, C.D_SAMPLES, *C.D_STIM_IMAGES.split("/"))
QA = os.path.join(ROOT, C.D_QC)
LOG = os.path.join(C.WORK, "_reencode_log.jsonl")
os.makedirs(QA, exist_ok=True)
MAXSIDE, Q_BYTES = C.MAXSIDE, C.MAX_IMAGE_BYTES

ok_all = []
def chk(name, cond, detail):
    ok_all.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + " :: " + detail)

# ---------- 1. 重编码日志 → 材料台账 ----------
recs = []
with io.open(LOG, encoding="utf-8") as f:
    for ln in f:
        try: recs.append(json.loads(ln))
        except Exception: pass
seen, uniq = {}, []
for r in recs:
    seen[r["src"]] = r          # 后出现者覆盖先出现者（重试成功会覆盖早先的失败记录）
for r in recs:
    if seen.get(r["src"]) is r:
        uniq.append(r)
recs = uniq
bad = [r for r in recs if not r.get("ok")]
print(f"重编码记录 {len(recs)} 条，失败 {len(bad)} 条")

cols = ["sample_id","record_id","src","dst","orig_w","orig_h","orig_bytes","resized",
        "out_w","out_h","out_bytes","sha256_orig","sha256_stim","ok","error"]
led = os.path.join(SAMPLES, C.MATERIAL_LEDGER_NAME)
with open(led, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in sorted(recs, key=lambda x: (x["sample_id"], x["src"])):
        w.writerow(r)

# ---------- 2. 数量守恒 ----------
with io.open(os.path.join(SAMPLES, C.SAMPLE_MANIFEST_NAME), encoding="utf-8-sig", newline="") as f:
    manifest = list(csv.DictReader(f))
with io.open(os.path.join(ROOT, C.D_REQUESTS, C.REQUESTS_NAME), encoding="utf-8") as f:
    reqs = [json.loads(l) for l in f if l.strip()]

n_samples = len(manifest)
expected_imgs = sum(int(m.get("image_count") or 0) for m in manifest)

txt_files = sorted(os.listdir(TEXT_DIR))
img_files = []
for r, d, fs in os.walk(IMG_ROOT):
    for fn in fs:
        img_files.append(os.path.join(r, fn))

chk("样本清单行数 = 文本文件数", len(manifest) == len(txt_files), f"{len(manifest)} vs {len(txt_files)}")
chk("requests 行数 = 样本数", len(reqs) == n_samples, f"{len(reqs)} vs {n_samples}")
chk("磁盘图片数 = 样本清单图片数", len(img_files) == expected_imgs, f"{len(img_files)} vs {expected_imgs}")
chk("requests 图片引用总数 = 样本清单图片数",
    sum(r["image_count"] for r in reqs) == expected_imgs,
    f"{sum(r['image_count'] for r in reqs)} vs {expected_imgs}")
chk("重编码成功数 = 样本清单图片数", len(recs) - len(bad) == expected_imgs, f"{len(recs)-len(bad)} vs {expected_imgs}")

# ---------- 3. requests 路径可解析 ----------
missing, badsize, badside, badext = [], [], [], []
for r in reqs:
    for rel in r["images"]:
        p = os.path.join(ROOT, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            missing.append((r["sample_id"], rel)); continue
        sz = os.path.getsize(p)
        if sz > Q_BYTES: badsize.append((r["sample_id"], rel, sz))
        if not p.lower().endswith(".jpg"): badext.append((r["sample_id"], rel))
        # 尺寸抽查：只查 resized=False 之外的全部（用台账更省；这里按台账查）
chk("requests 中图片路径全部存在", not missing, f"缺失 {len(missing)}")
chk(f"全部图片体积 ≤ {Q_BYTES/1024/1024:.0f}MB", not badsize, f"超限 {len(badsize)}  最大 {max((r.get('out_bytes',0) for r in recs), default=0)/1024/1024:.2f}MB")
chk("全部图片为 .jpg", not badext, f"异常 {len(badext)}")
over = [r for r in recs if r.get("ok") and max(r.get("out_w",0), r.get("out_h",0)) > MAXSIDE]
chk(f"全部图片长边 ≤ {MAXSIDE}", not over, f"超限 {len(over)}")

# ---------- 4. 文本与清单一致 ----------
with open(os.path.join(SRC, "可用UGC.csv"), "r", encoding="utf-8-sig", newline="") as f:
    ugc = {r["record_id"]: r for r in csv.DictReader(f)}
def build(rec):
    ps = []
    for k in C.TEXT_FIELDS:
        v = (rec.get(k) or "").strip()
        if v: ps.append(v)
    return "\n".join(ps)
mis = []
for m in manifest:
    with io.open(os.path.join(TEXT_DIR, m["sample_id"] + ".txt"), encoding="utf-8") as f:
        if f.read() != build(ugc[m["record_id"]]):
            mis.append(m["sample_id"])
chk("文本文件内容与原始字段逐字节一致", not mis, f"不一致 {len(mis)}")
chk("文本文件无 BOM", all(io.open(os.path.join(TEXT_DIR, t), "rb").read(3) != b"\xef\xbb\xbf" for t in txt_files[:200]),
    "抽查 200 个")
chk("requests.jsonl 无 BOM", io.open(os.path.join(ROOT, C.D_REQUESTS, C.REQUESTS_NAME), "rb").read(3) != b"\xef\xbb\xbf", "-")

# ---------- 5. 泄漏检查 ----------
leak = []
for m in manifest:
    with io.open(os.path.join(TEXT_DIR, m["sample_id"] + ".txt"), encoding="utf-8") as f:
        c = f.read()
    rec = ugc[m["record_id"]]
    for token in [rec["record_id"], m["sample_id"], "source_keywords", "image_files",
                  "cleaning_status", "keep", "exclude_ad"]:
        if token and token in c:
            leak.append((m["sample_id"], token))
chk("文本中无台账字段/ID 泄漏", not leak, f"命中 {len(leak)}")

# ---------- 6. 图片 SHA-256 抽查（50 张）----------
random.seed(C.SAMPLE_SEED)
ok_recs = [r for r in recs if r.get("ok")]
pick = random.sample(ok_recs, min(50, len(ok_recs))) if ok_recs else []
mm = 0
for r in pick:
    p = os.path.join(ROOT, r["dst"].replace("/", os.sep))
    h = hashlib.sha256(io.open(p, "rb").read()).hexdigest()
    if h != r["sha256_stim"]: mm += 1
chk("刺激图 SHA-256 抽查 50 张", mm == 0, f"不一致 {mm}")

# ---------- 7. 抽样目检清单 ----------
random.seed(7)
strat = collections.defaultdict(list)
for m in manifest:
    key = ("n" if m["has_image"] == "0" else str(min(int(m["image_count"]), 9)) )
    strat[key].append(m)
picklist = []
for k in sorted(strat):
    picklist += random.sample(strat[k], min(3, len(strat[k])))
picklist = picklist[:24]
with open(os.path.join(QA, "抽样目检清单.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["sample_id","record_id","platform","has_image","image_count","text_len","正文前80字","图片示例"])
    for m in picklist:
        with io.open(os.path.join(TEXT_DIR, m["sample_id"] + ".txt"), encoding="utf-8") as fh:
            t = fh.read().replace("\n", " ")[:80]
        req = next(r for r in reqs if r["sample_id"] == m["sample_id"])
        ex = req["images"][0] if req["images"] else ""
        w.writerow([m["sample_id"], m["record_id"], m["platform"], m["has_image"],
                    m["image_count"], m["text_len"], t, ex])

# ---------- 8. 平台痕迹汇总 ----------
trace = os.path.join(QA, "平台痕迹扫描.csv")
tr_rows = list(csv.DictReader(io.open(trace, encoding="utf-8-sig")))
by_cat = collections.Counter(r["类别"] for r in tr_rows)
by_cat_samples = collections.defaultdict(set)
for r in tr_rows:
    by_cat_samples[r["类别"]].add(r["sample_id"])

# ---------- 9. 汇总数字 ----------
tot_orig = sum(r.get("orig_bytes", 0) for r in recs if r.get("ok"))
tot_out = sum(r.get("out_bytes", 0) for r in recs if r.get("ok"))
n_resized = sum(1 for r in recs if r.get("resized"))
n_textonly = sum(1 for m in manifest if m["has_image"] == "0")

rep = os.path.join(QA, "自检报告.md")
with io.open(rep, "w", encoding="utf-8", newline="\n") as f:
    f.write(f"# {C.PROJECT_NAME} · Y 侧交付自检报告\n\n")
    f.write(f"> 生成时间：{datetime.date.today().isoformat()}　|　交付根目录：`{C.DELIVERY_TOP_NAME}/`\n\n")
    f.write("## 一、校验结果\n\n| # | 校验项 | 结果 | 明细 |\n|---|---|---|---|\n")
    for i, (n, c, d) in enumerate(ok_all, 1):
        f.write(f"| {i} | {n} | {'✅ 通过' if c else '❌ 未通过'} | {d} |\n")
    npass = sum(1 for _, c, _ in ok_all if c)
    f.write(f"\n**通过 {npass}/{len(ok_all)}**\n\n")

    f.write("## 二、数量汇总\n\n| 项 | 值 |\n|---|---|\n")
    f.write(f"| 样本数 | {n_samples} |\n| 有图样本 | {len(manifest)-n_textonly} |\n| 纯文本样本 | {n_textonly} |\n")
    f.write(f"| 文本文件 | {len(txt_files)} |\n| 刺激图片 | {len(img_files)} |\n")
    f.write(f"| requests 行数 | {len(reqs)} |\n")
    f.write(f"| 图片原始体积 | {tot_orig/1024**3:.2f} GB |\n")
    f.write(f"| 刺激图体积 | {tot_out/1024**3:.2f} GB（压缩至 {tot_out/tot_orig*100:.1f}%）|\n")
    f.write(f"| 发生缩放的图片 | {n_resized} 张（长边 >1568 的）|\n")
    f.write(f"| 重编码失败 | {len(bad)} 张 |\n")
    mx = max((r.get("out_bytes", 0) for r in recs if r.get("ok")), default=0)
    f.write(f"| 刺激图单张最大体积 | {mx/1024/1024:.2f} MB（上限 {Q_BYTES/1024/1024:.0f} MB）|\n\n")

    f.write("## 三、平台痕迹扫描汇总\n\n")
    f.write("> **只扫描、未删改。** 这些命中都属于材料固有内容，是否处理请研究负责人决定。\n\n")
    f.write("| 类别 | 命中数 | 涉及样本数 |\n|---|---|---|\n")
    for k, v in by_cat.most_common():
        f.write(f"| {k} | {v} | {len(by_cat_samples[k])} |\n")
    f.write(f"\n明细见 `平台痕迹扫描.csv`（{len(tr_rows)} 行）。\n\n")
    f.write("**重点提示**：\n")
    f.write("- **平台名**命中绝大多数是**作者自述**（如“在某某平台购票”“某平台搜索”），不是元数据注入。"
            "但若研究要求盲态，这部分样本会**间接暴露平台**——无法在不改动材料的前提下消除。\n")
    f.write("- **“展开全文”“网页链接”** 一类是平台壳层文字被采集进了正文，属于清洗阶段的轻微残留噪声。\n")
    f.write("- **`#话题#`** 是平台标签，可能夹杂导出畸形标记。\n")
    f.write("- **“评分维度词”命中需人工判断**：可能是作者原文，不一定是泄题。\n\n")

    f.write("## 四、抽样目检清单\n\n")
    f.write("`抽样目检清单.csv` 按图片张数分层随机抽了 24 条，覆盖三个平台与纯文本样本，供人工过目。\n\n")
    f.write("| sample_id | platform | 图片数 | 正文长度 |\n|---|---|---|---|\n")
    for m in picklist[:24]:
        f.write(f"| {m['sample_id']} | {m['platform']} | {m['image_count']} | {m['text_len']} |\n")
    f.write("\n")

    f.write("## 五、结论\n\n")
    if npass == len(ok_all) and not bad:
        f.write("全部校验通过，刺激材料可直接用于调用。\n")
    else:
        f.write(f"⚠️ 有 {len(ok_all)-npass} 项未通过 / {len(bad)} 张图片处理失败，请先处理再调用。\n")

print("\n报告:", rep)
print(f"通过 {sum(1 for _,c,_ in ok_all if c)}/{len(ok_all)}")
print(f"图片 {len(img_files)}  文本 {len(txt_files)}  原始 {tot_orig/1024**3:.2f}GB → 刺激图 {tot_out/1024**3:.2f}GB  缩放 {n_resized} 张")
