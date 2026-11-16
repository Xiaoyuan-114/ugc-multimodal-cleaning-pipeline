# -*- coding: utf-8 -*-
"""Y3：生成 requests.jsonl —— 每行一个样本的材料清单，供调用侧脚本直接消费。
   刻意不含 platform / source_keywords / 任何模型不该看到的信息，降低误喂风险。"""
import os, io, json
import config as C

ROOT = C.DELIVERY_ROOT
LEDGER = os.path.join(C.WORK, "_ledger.json")
OUTDIR = os.path.join(ROOT, C.D_REQUESTS)
os.makedirs(OUTDIR, exist_ok=True)

SAMPLE_DIR = C.D_SAMPLES.replace("\\", "/")

with io.open(LEDGER, encoding="utf-8") as f:
    ledger = json.load(f)

def rel(p):
    return p.replace(os.sep, "/")

n_img = 0
out = os.path.join(OUTDIR, C.REQUESTS_NAME)
with io.open(out, "w", encoding="utf-8", newline="\n") as f:
    for it in ledger:
        sid = it["sample_id"]
        imgs = [f"{SAMPLE_DIR}/stimuli/{rel(p)}" for p in it["image_files"]]
        n_img += len(imgs)
        rec = {
            "sample_id": sid,
            "record_id": it["record_id"],
            "has_image": bool(imgs),
            "image_count": len(imgs),
            "text_file": f"{SAMPLE_DIR}/{C.D_STIM_TEXT}/{sid}.txt",
            "images": imgs,
            # 调用方需在首个 text part 前加上这一行标记（如提示词要求在材料开头标明 sample_id）
            "material_header": f"【样本 {sid}｜图文材料】",
        }
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

n = sum(1 for _ in io.open(out, encoding="utf-8"))
print("requests.jsonl:", out)
print("行数:", n, " 图片引用:", n_img)
print("首行:", io.open(out, encoding="utf-8").readline().strip()[:300])
