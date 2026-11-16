# -*- coding: utf-8 -*-
"""Y9：估算把全部样本喂给目标模型的 token 用量与费用。

素材来自交付目录里的样本清单、材料台账、文本文件与提示词。
价格与折扣在 config_local.py 中配置。
"""
import os, csv, math, json
import config as C

BASE = C.DELIVERY_ROOT
LEDGER = os.path.join(BASE, C.D_SAMPLES, C.MATERIAL_LEDGER_NAME)
TEXTD = os.path.join(BASE, C.D_SAMPLES, *C.D_STIM_TEXT.split("/"))
PROMPTF = C.PROMPT_FILE
MANIFEST = os.path.join(BASE, C.D_SAMPLES, C.SAMPLE_MANIFEST_NAME)

with open(MANIFEST, encoding="utf-8-sig", newline="") as fh:
    N_SAMPLE = sum(1 for _ in csv.DictReader(fh))

PROMPT_CHARS = len(open(PROMPTF, encoding="utf-8").read()) if os.path.isfile(PROMPTF) else 0
if not PROMPT_CHARS:
    print(f"[warn] 提示词文件不存在或为空：{PROMPTF}（提示词 token 将按 0 计算）")

TEXT_CHARS = sum(len(open(os.path.join(TEXTD, f), encoding="utf-8").read())
                 for f in os.listdir(TEXTD))
HEADER_CHARS = N_SAMPLE * 15  # 【样本 0001｜图文材料】 ≈ 15 字符


def n_tiles(w, h, cap=None):
    """Gemini 图片 token 规则：≤384px → 1 单位；否则按 768×768 tile 切。"""
    if cap:
        m = max(w, h)
        if m > cap:
            s = cap / float(m)
            w, h = w * s, h * s
    if w <= 384 and h <= 384:
        return 1
    return int(math.ceil(w / 768.0)) * int(math.ceil(h / 768.0))


rows = []
with open(LEDGER, encoding="utf-8-sig", newline="") as fh:
    for d in csv.DictReader(fh):
        if d.get("ok") in ("True", "true", "1", ""):
            rows.append((int(d["out_w"]), int(d["out_h"])))

if not rows:
    raise SystemExit("材料台账里没有可用图片记录，无法估算。")

tokens_nocap = sum(258 * n_tiles(w, h) for w, h in rows)
tokens_cap = sum(258 * n_tiles(w, h, cap=1536) for w, h in rows)

print("=" * 62)
print("素材统计")
print("=" * 62)
print(f"样本数            : {N_SAMPLE}")
print(f"图片数            : {len(rows)}")
print(f"提示词字符数      : {PROMPT_CHARS}  (每条请求都带)")
print(f"正文总字符数      : {TEXT_CHARS}")
print(f"正文平均字符数    : {TEXT_CHARS/max(N_SAMPLE,1):.0f}")
print()
print(f"图片 tokens（不封顶，按 out_w/h 切 tile）: {tokens_nocap:,}  ({tokens_nocap/1e6:.2f} M)")
print(f"图片 tokens（先缩到长边≤1536 再切）      : {tokens_cap:,}  ({tokens_cap/1e6:.2f} M)")
print(f"平均每张图 tokens : {tokens_nocap/len(rows):.0f} ~ {tokens_cap/len(rows):.0f}")
print()

# 中文 token 折算系数：0.7（乐观）~ 1.0（保守）
results = {}
for k, label in ((0.7, "乐观(中文0.7/字)"), (1.0, "保守(中文1.0/字)")):
    prompt_t = PROMPT_CHARS * N_SAMPLE * k
    text_t = TEXT_CHARS * k
    header_t = HEADER_CHARS * k
    img_t = tokens_cap if k == 0.7 else tokens_nocap
    inp = prompt_t + text_t + header_t + img_t
    results[label] = inp
    print(f"--- {label} ---")
    print(f"  提示词  : {prompt_t/1e6:8.2f} M   ({prompt_t/inp*100:.1f}%  ← 每条请求重复携带)")
    print(f"  正文    : {text_t/1e6:8.2f} M")
    print(f"  表头    : {header_t/1e6:8.2f} M")
    print(f"  图片    : {img_t/1e6:8.2f} M   ({img_t/inp*100:.1f}%)")
    print(f"  INPUT 合计: {inp/1e6:8.2f} M")
print()

# 输出侧
OUT_LO, OUT_MID, OUT_HI = C.OUTPUT_TOKENS_LOW, C.OUTPUT_TOKENS_MID, C.OUTPUT_TOKENS_HIGH
PRICE_IN, PRICE_OUT = C.PRICE_INPUT_USD, C.PRICE_OUTPUT_USD
DISCOUNT = C.PRICE_DISCOUNT

print("=" * 62)
print("费用估算（USD）")
print("=" * 62)
for label, inp in results.items():
    print(f"\n[{label}]  input = {inp/1e6:.2f} M")
    for oname, out in (("输出 2M", OUT_LO), ("输出 3M", OUT_MID), ("输出 4M", OUT_HI)):
        c_std = inp / 1e6 * PRICE_IN + out / 1e6 * PRICE_OUT
        c_batch = c_std * 0.5
        c_disc = c_std * DISCOUNT
        c_disc_batch = c_batch * DISCOUNT
        print(f"   {oname:<8} 标准 ${c_std:6.2f} | Batch(半价) ${c_batch:6.2f} | "
              f"折扣价 ${c_disc:6.2f} | 折扣+Batch ${c_disc_batch:6.2f}")

json.dump({"prompt_chars": PROMPT_CHARS, "text_chars": TEXT_CHARS,
           "samples": N_SAMPLE, "images": len(rows),
           "img_tokens_nocap": tokens_nocap, "img_tokens_cap1536": tokens_cap,
           "input_optimistic": results["乐观(中文0.7/字)"],
           "input_conservative": results["保守(中文1.0/字)"]},
          open(os.path.join(C.WORK, "_cost_estimate.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)