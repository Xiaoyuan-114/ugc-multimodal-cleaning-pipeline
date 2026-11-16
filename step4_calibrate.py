# -*- coding: utf-8 -*-
"""Step 4（闸门）：校准批。抽 120 条覆盖四类情形，跑完整两级判定（广告 + 不可用），交用户验收。"""
import os, sys, json, csv, re, collections, time, html, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import adjudicate as A
import decisions as D

INTERIM = C.INTERIM
CAL = os.path.join(C.WORK, "calibration")
os.makedirs(CAL, exist_ok=True)

if not A.API_KEY:
    print("未配置 API key：请设置环境变量 UGC_API_KEY 或 DS_API_KEY")
    raise SystemExit(2)

AD_RE = re.compile(C.AD_KEYWORDS_REGEX)

PER_CELL = C.SAMPLE_PER_CELL
TARGET = C.SAMPLE_TARGET
CATS = C.SAMPLE_CATEGORIES

SERVICE_RE = re.compile(C.SERVICE_KEYWORDS_REGEX)
# 定向探针：来自 config_local.PROBES，每项 {"name", "match", "count"}
PROBES = C.PROBES


def load():
    canon = json.load(open(os.path.join(INTERIM, "canonical_ugc.json"), encoding="utf-8"))
    idx = json.load(open(os.path.join(INTERIM, "image_index.json"), encoding="utf-8"))
    fps = {}
    p = os.path.join(INTERIM, "image_fingerprints.jsonl")
    with open(p, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
                fps[d["source_path"]] = d
            except Exception:
                pass
    return canon, idx["index"], fps


def images_of(rec, idx):
    out = []
    for entry in idx.get(rec["platform"], {}).get(rec["source_id"], []) or []:
        for f in entry["files"]:
            if os.path.splitext(f)[1].lower() in C.IMG_EXTS:
                out.append(f)
    return sorted(out)


def categorize(rec, imgs, fps):
    for p in imgs:
        d = fps.get(p)
        if d and (d.get("decode_status") == "failed" or d.get("file_size", 1) == 0):
            return "疑似不可用"
    if not imgs:
        return "纯文本无图"
    if AD_RE.search((rec.get("title_raw") or "") + " " + (rec.get("text_raw") or "")):
        return "疑似广告"
    return "正常图文"


def sample(canon):
    rng = __import__("random").Random(C.SAMPLE_SEED)
    picked, seen = [], set()

    def add(r, tag):
        if r["record_id"] in seen:
            return
        seen.add(r["record_id"])
        picked.append(dict(r, _tag=tag))

    for plat in C.PLATFORMS:
        for cat in CATS:
            pool = sorted([r for r in canon if r["platform"] == plat and r["_cat"] == cat],
                          key=lambda r: r["record_id"])
            take = pool if len(pool) <= PER_CELL else rng.sample(pool, PER_CELL)
            for r in take:
                add(r, f"{plat}/{cat}")
    # 定向探针（验证边界情形）
    for probe in PROBES:
        name, fn, per = probe["name"], probe["match"], probe.get("count", 14)
        pool = sorted([r for r in canon if fn(r)], key=lambda r: r["record_id"])
        take = pool if len(pool) <= per else rng.sample(pool, per)
        for r in take:
            add(r, f"探针/{name}")
    if len(picked) < TARGET:
        pool = sorted([r for r in canon if r["_cat"] == "正常图文" and r["record_id"] not in seen],
                      key=lambda r: r["record_id"])
        for r in rng.sample(pool, min(TARGET - len(picked), len(pool))):
            add(r, "补足/正常图文")
    return picked


def run_one(rec, fps):
    t0 = time.time()
    full = [os.path.join(C.DATA, p) for p in rec["_imgs"]]
    verdicts, usages = [], []
    for i in range(0, len(full), A.IMAGES_PER_CALL):
        chunk = full[i:i + A.IMAGES_PER_CALL]
        inds = list(range(i + 1, i + 1 + len(chunk)))
        v, u = A.judge_images(chunk, inds)
        verdicts.extend(v[k] for k in sorted(v))
        usages.append(u)
    sample_imgs = [full[0]] if full else []
    if len(full) > 2:
        sample_imgs.append(full[len(full) // 2])
    if len(full) > 1:
        sample_imgs.append(full[-1])
    rv, ru = A.judge_record(dict(rec, image_count=len(full)), verdicts, sample_imgs)
    usages.append(ru)
    agg = collections.Counter()
    for u in usages:
        for k, val in (u or {}).items():
            if isinstance(val, int):
                agg[k] += val
    status, primary, reasons, _ = D.decide_record(rec, rv, verdicts, bool(full))
    img_removed = [v for v in verdicts if D.decide_image(v)[0] != "keep"]
    sg_hit, sg_ev = D.scope_guard(rec, rv)
    return dict(rec=rec, verdicts=verdicts, record_verdict=rv, usage=dict(agg),
                money=A.money_of(dict(agg)), seconds=round(time.time() - t0, 1),
                status=status, primary=primary, reasons=reasons, img_removed=img_removed,
                scope_guard=sg_hit, scope_evidence=sg_ev)


def main():
    canon, idx, fps = load()
    print(f"规范 UGC {len(canon)} 条；图片指纹 {len(fps)} 条", flush=True)
    for r in canon:
        r["_imgs"] = images_of(r, idx)
        r["image_count"] = len(r["_imgs"])
        r["_cat"] = categorize(r, r["_imgs"], fps)
    dist = collections.Counter((r["platform"], r["_cat"]) for r in canon)
    print("\n全量四类分布：")
    for plat in C.PLATFORMS:
        print("  %-6s " % plat + "  ".join(f"{c}={dist.get((plat,c),0)}" for c in CATS))

    picked = sample(canon)
    print(f"\n校准批 {len(picked)} 条  分布: {dict(collections.Counter(r['_tag'] for r in picked))}", flush=True)

    results, usage_tot = [], collections.Counter()
    t0 = time.time()
    with open(os.path.join(CAL, "calib_partial.jsonl"), "w", encoding="utf-8") as pf, \
            ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(run_one, r, fps) for r in picked]
        for n, fut in enumerate(as_completed(futs), 1):
            try:
                res = fut.result()
            except Exception as e:
                print(f"  [跳过] {type(e).__name__}: {e}"); traceback.print_exc(); continue
            results.append(res)
            pf.write(json.dumps({"record_id": res["rec"]["record_id"]}, ensure_ascii=False) + "\n"); pf.flush()
            if n % 20 == 0:
                print(f"  {n}/{len(picked)}  {(time.time()-t0)/60:.1f} 分", flush=True)

    for r in results:
        for k, v in r["usage"].items():
            usage_tot[k] += v
    json.dump(results, open(os.path.join(CAL, "calib_results.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    m = A.money_of(dict(usage_tot))

    n_img_calls = sum(max(1, (len(r["rec"]["_imgs"]) + A.IMAGES_PER_CALL - 1) // A.IMAGES_PER_CALL)
                      for r in results)
    n_calls = n_img_calls + len(results)
    tot_tok = usage_tot.get("prompt_tokens", 0) + usage_tot.get("completion_tokens", 0)
    print(f"\n用时 {(time.time()-t0)/60:.1f} 分")
    print(f"请求 {n_calls} 次（图片 {n_img_calls} + 记录 {len(results)}）")
    print(f"token: 输入 {usage_tot.get('prompt_tokens',0):,}（命中 {usage_tot.get('prompt_cache_hit_tokens',0):,} / "
          f"未命中 {usage_tot.get('prompt_cache_miss_tokens',0):,}）+ 输出 {usage_tot.get('completion_tokens',0):,} = {tot_tok:,}")
    print(f"校准批成本：空闲 ¥{m['offpeak_cny']:.4f}  高峰 ¥{m['peak_cny']:.4f}")

    tot_imgs = sum(len(r["_imgs"]) for r in canon)
    est_calls = tot_imgs / A.IMAGES_PER_CALL + len(canon)
    per_call = tot_tok / max(1, n_calls)
    scale = est_calls / max(1, n_calls)
    est_tok = tot_tok * scale
    est_m = {"prompt_cache_miss_tokens": usage_tot.get("prompt_cache_miss_tokens", 0) * scale,
             "prompt_cache_hit_tokens": usage_tot.get("prompt_cache_hit_tokens", 0) * scale,
             "completion_tokens": usage_tot.get("completion_tokens", 0) * scale}
    em = A.money_of(est_m)
    print(f"\n全量规模：图片 {tot_imgs} 张、记录 {len(canon)} 条 → 约 {est_calls:.0f} 次请求")
    print(f"校准批平均每次 {per_call:.0f} token → 外推全量 ≈ {est_tok/1e6:.2f} M token")
    print(f"外推全量成本：空闲 ¥{em['offpeak_cny']:.2f}  高峰 ¥{em['peak_cny']:.2f}")

    # ---- 判定表
    idx2path = {}
    rows = []
    for r in results:
        rec, rv = r["rec"], r["record_verdict"]
        full = [os.path.join(C.DATA, p) for p in rec["_imgs"]]
        for k, v in enumerate(r["verdicts"], 1):
            idx2path[k] = rec["_imgs"][k - 1] if k - 1 < len(rec["_imgs"]) else ""
        img_rm = [{"idx": v.get("index"), "path": idx2path.get(v.get("index"), ""),
                   "status": D.decide_image(v)[0], "code": D.decide_image(v)[1],
                   "ev": (v.get("promotion_evidence") or []) + ([v.get("unusable_evidence")] if v.get("unusable_evidence") else [])}
                  for v in r["img_removed"]]
        usable = D.usable_image_count(r["verdicts"])
        rows.append({
            "platform": rec["platform"], "record_id": rec["record_id"], "category": rec["_cat"],
            "sample_tag": rec.get("_tag", ""),
            "image_count": rec["image_count"], "usable_image_count": usable,
            "status": r["status"], "primary_reason_code": r["primary"],
            "all_reason_codes": json.dumps(r["reasons"], ensure_ascii=False),
            "scope_guard": r.get("scope_guard", False), "scope_evidence": r.get("scope_evidence", ""),
            "is_ad": rv.get("is_ad"), "ad_reason_code": rv.get("reason_code", ""),
            "record_is_travel_experience": rv.get("record_is_travel_experience"),
            "t001": rv.get("t001"), "r001": rv.get("r001"), "r003": rv.get("r003"),
            "promotion_evidence": json.dumps(rv.get("promotion_evidence", []), ensure_ascii=False)[:400],
            "ad_evidence_short": "；".join(rv.get("promotion_evidence", []))[:300],
            "landscape_content_present": rv.get("landscape_content_present"),
            "landscape_evidence": "；".join(rv.get("landscape_evidence", []))[:200],
            "r001_evidence": rv.get("r001_evidence", ""), "r003_evidence": rv.get("r003_evidence", ""),
            "t001_evidence": rv.get("t001_evidence", ""),
            "confidence": rv.get("confidence", ""), "notes": rv.get("notes", ""),
            "removed_image_count": len(img_rm),
            "removed_image_detail": json.dumps(img_rm, ensure_ascii=False)[:700],
            "low_res_flags": sum(1 for p in rec["_imgs"] if (fps.get(p) or {}).get("width")
                                 and fps[p]["width"] * fps[p]["height"] < C.LOW_RES_PIXELS),
            "title": (rec.get("title_raw") or "")[:60],
            "text": (rec.get("text_raw") or "")[:150].replace("\n", " "),
        })
    rows.sort(key=lambda x: (x["status"], x["platform"], x["category"], x["record_id"]))
    if not rows:
        print("\n没有判定结果，跳过判定表写出。")
        return rows, results
    with open(os.path.join(CAL, "校准批_判定表.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

    st = collections.Counter(x["status"] for x in rows)
    print("\n整条判定分布:", dict(st))
    print("主原因分布:", dict(collections.Counter(x["primary_reason_code"] for x in rows if x["primary_reason_code"])))
    print("按抽样类别×判定:", {c: dict(collections.Counter(x["status"] for x in rows if x["category"] == c)) for c in CATS})
    print("按抽样标签×判定:", {t: dict(collections.Counter(x["status"] for x in rows if x["sample_tag"] == t))
                               for t in sorted({x["sample_tag"] for x in rows})})
    print("范围守卫命中:", sum(1 for x in rows if x["scope_guard"]),
          "｜判为广告:", sum(1 for x in rows if x["status"] == "exclude_ad"),
          "｜判为游览记录:", sum(1 for x in rows if x["record_is_travel_experience"]))
    print("单图移除合计:", sum(x["removed_image_count"] for x in rows))

    # ---- HTML
    def esc(x):
        return html.escape(str(x if x is not None else ""))
    CMAP = {"exclude_ad": "广告", "exclude_unusable": "不可用", "keep": "保留"}
    tr = []
    for x in rows:
        cls = "ad" if x["status"] == "exclude_ad" else ("un" if x["status"] == "exclude_unusable" else "")
        ev = x["ad_evidence_short"] or x["scope_evidence"] or x["r001_evidence"] or x["r003_evidence"] or x["t001_evidence"]
        tr.append(f"""<tr class="{cls}">
<td class="mono">{esc(x['record_id'])}</td><td>{esc(x['platform'])}</td><td>{esc(x['sample_tag'])}</td>
<td class="num">{x['image_count']}<br><span class="sm">可用{x['usable_image_count']}</span></td>
<td><b>{esc(CMAP[x['status']])}</b><br><span class="sm">{esc(x['primary_reason_code'])}</span></td>
<td>{esc(ev)[:300]}</td>
<td>{'游览' if x['record_is_travel_experience'] else '招揽'}</td>
<td>{'有' if x['landscape_content_present'] else '无'}</td>
<td class="num">{x['removed_image_count']}</td>
<td class="num">{x['low_res_flags']}</td>
<td>{esc(x['notes'])[:150]}</td>
<td class="txt">{esc(x['title'])}<br><span class="sm">{esc(x['text'])}</span></td></tr>""")
    doc = f"""<h2>{esc(C.PROJECT_NAME)} · 校准批判定表</h2>
<p class="meta">共 {len(rows)} 条 ｜ 模型 {esc(C.MODEL)} ｜ thinking=disabled ｜ 规则 {esc(C.RULE_VERSION)}</p>
<p class="meta">整条判定：{dict(st)} ｜ 被动过图的记录 {sum(1 for x in rows if x['removed_image_count'])} 条，单图移除合计 {sum(x['removed_image_count'] for x in rows)} 张</p>
<p class="meta">token {tot_tok:,}（{n_calls} 次请求）｜ 校准批成本 空闲 ¥{m['offpeak_cny']:.3f}、高峰 ¥{m['peak_cny']:.3f} ｜ 外推全量 空闲 ¥{em['offpeak_cny']:.1f}、高峰 ¥{em['peak_cny']:.1f}</p>
<p class="meta"><span class="chip ad">红</span>=整条判广告排除　<span class="chip un">橙</span>=整条判不可用排除　白=保留。请重点核：红/橙行的证据是否站得住；白行里有没有本该排除却放过的。</p>
<table><thead><tr><th>record_id</th><th>平台</th><th>抽样标签</th><th>图数</th><th>整条判定</th>
<th>证据</th><th>主旨</th><th>景观内容</th><th>移除图</th><th>低分图</th><th>模型说明</th><th>原文摘要</th></tr></thead>
<tbody>{''.join(tr)}</tbody></table>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:13px;color:#2C2C2A;background:#fff;margin:24px}}
h2{{font-size:17px;font-weight:500;margin:0 0 8px}}
.meta{{color:#5F5E5A;font-size:12px;margin:3px 0}}
.chip{{display:inline-block;padding:0 6px;border-radius:4px;font-size:11px}}
.chip.ad{{background:#FCEBEB;color:#A32D2D}} .chip.un{{background:#FAEEDA;color:#854F0B}}
table{{border-collapse:collapse;width:100%;margin-top:12px}}
th,td{{border:1px solid #D3D1C7;padding:5px 7px;vertical-align:top;font-size:12px;line-height:1.5}}
th{{background:#F1EFE8;font-weight:500;text-align:left}}
tr.ad{{background:#FCEBEB}} tr.un{{background:#FAEEDA}}
.num{{text-align:center;white-space:nowrap}}
.mono{{font-family:ui-monospace,Consolas,monospace;font-size:11px}}
.sm{{color:#5F5E5A;font-size:11px}}
.txt{{max-width:220px}}
</style>"""
    open(os.path.join(CAL, "校准批_判定表.html"), "w", encoding="utf-8").write(doc)
    print("\n已写出 校准批_判定表.csv / .html")
    return rows, results


if __name__ == "__main__":
    main()
