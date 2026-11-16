# -*- coding: utf-8 -*-
"""Step 5：全量两级判定。

   图片级 = 广告(A) + 不可用(R002/R003/R004/R005) + 无法解码(F001)
   记录级 = 广告(A) + T001 + R001 + R003 + 可选的范围守卫

逐条追加写入 full/full_results.jsonl，可断点续跑；失败条目记入 full/full_errors.jsonl
并在本轮末尾自动补跑。用法：
   python step5_full.py [--limit N] [--workers K]
"""
import os, sys, json, time, collections, traceback, argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import adjudicate as A
import decisions as D

INTERIM = C.INTERIM
FULL = os.path.join(C.WORK, "full")
os.makedirs(FULL, exist_ok=True)
RES = os.path.join(FULL, "full_results.jsonl")
ERR = os.path.join(FULL, "full_errors.jsonl")

if not A.API_KEY:
    print("未配置 API key：请设置环境变量 UGC_API_KEY 或 DS_API_KEY")
    raise SystemExit(2)

FIELDS = ["platform", "record_id", "source_id", "title_raw", "text_raw", "repost_text_raw",
          "source_keywords", "text_clean"]


def load():
    canon = json.load(open(os.path.join(INTERIM, "canonical_ugc.json"), encoding="utf-8"))
    idx = json.load(open(os.path.join(INTERIM, "image_index.json"), encoding="utf-8"))["index"]
    fps = {}
    with open(os.path.join(INTERIM, "image_fingerprints.jsonl"), encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
                fps[d["source_path"]] = d
            except Exception:
                pass
    return canon, idx, fps


def images_of(rec, idx):
    out = []
    for entry in idx.get(rec["platform"], {}).get(rec["source_id"], []) or []:
        for f in entry["files"]:
            if os.path.splitext(f)[1].lower() in C.IMG_EXTS:
                out.append(f)
    return sorted(out)


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
    sample = []
    if full:
        sample = [full[0]]
        if len(full) > 2:
            sample.append(full[len(full) // 2])
        if len(full) > 1:
            sample.append(full[-1])
    rv, ru = A.judge_record(dict(rec, image_count=len(full)), verdicts, sample)
    usages.append(ru)
    agg = collections.Counter()
    for u in usages:
        for k, val in (u or {}).items():
            if isinstance(val, int):
                agg[k] += val

    status, primary, reasons, _ = D.decide_record(rec, rv, verdicts, bool(full))
    hit, ev = D.scope_guard(rec, rv)
    return {
        "record_id": rec["record_id"], "platform": rec["platform"],
        "verdicts": verdicts, "record_verdict": rv,
        "usage": dict(agg), "money": A.money_of(dict(agg)),
        "seconds": round(time.time() - t0, 1),
        "status": status, "primary": primary, "reasons": reasons,
        "scope_guard": hit, "scope_evidence": ev,
        "guard_overrode_model": bool(hit and not rv.get("r001")),
    }


def done_ids():
    ids = set()
    if os.path.exists(RES):
        with open(RES, encoding="utf-8") as f:
            for line in f:
                try:
                    ids.add(json.loads(line)["record_id"])
                except Exception:
                    pass
    return ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    canon, idx, fps = load()
    for r in canon:
        r["_imgs"] = images_of(r, idx)
        r["_imgs"] = [p for p in r["_imgs"] if os.path.exists(os.path.join(C.DATA, p))]
    canon.sort(key=lambda r: r["record_id"])
    if args.limit:
        canon = canon[:args.limit]

    seen = done_ids()
    todo = [r for r in canon if r["record_id"] not in seen]

    # 预过滤：范围守卫命中的记录（SCOPE_GUARD_ENABLED 时生效）。
    # 无论模型怎么判都会被守卫排除，因此不必调用 API；其图片在输出时按 inherited_from_record 处理。
    pre, todo = [r for r in todo if D.scope_guard(r)[0]], [r for r in todo if not D.scope_guard(r)[0]]

    print(f"规范 UGC {len(canon)} 条 | 已完成 {len(seen)} 条 | 范围预过滤 {len(pre)} 条 | "
          f"待调模型 {len(todo)} 条 | 并发 {args.workers}", flush=True)

    if pre:
        with open(RES, "a", encoding="utf-8") as f:
            for r in pre:
                f.write(json.dumps({
                    "record_id": r["record_id"], "platform": r["platform"],
                    "verdicts": [], "record_verdict": {},
                    "usage": {}, "money": {"offpeak_cny": 0.0, "peak_cny": 0.0}, "seconds": 0.0,
                    "status": "exclude_unusable", "primary": "R001", "reasons": ["R001"],
                    "scope_guard": True, "scope_evidence": D.scope_guard(r)[1],
                    "guard_overrode_model": False, "prefiltered": True,
                }, ensure_ascii=False) + "\n")
        print(f"范围预过滤 {len(pre)} 条已直接落定（R001），未调用 API。", flush=True)

    if not todo:
        print("无待调模型条目。"); return

    t0 = time.time()
    usage_tot = collections.Counter()
    n_done = 0
    fails = []
    with open(RES, "a", encoding="utf-8") as f, ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_one, r, fps): r for r in todo}
        for fut in as_completed(futs):
            rec = futs[fut]
            try:
                res = fut.result()
            except Exception as e:
                fails.append({"record_id": rec["record_id"], "error": f"{type(e).__name__}: {e}",
                              "tb": traceback.format_exc()[-800:]})
                n_done += 1
                continue
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
            for k, v in res["usage"].items():
                usage_tot[k] += v
            n_done += 1
            if n_done % 100 == 0:
                f.flush()
                el = time.time() - t0
                rate = n_done / el
                left = (len(todo) - n_done) / max(rate, 1e-6)
                print(f"  {n_done}/{len(todo)}  {el/60:.1f} 分  预计剩余 {left/60:.1f} 分", flush=True)

    if fails:
        with open(ERR, "a", encoding="utf-8") as ef:
            for x in fails:
                ef.write(json.dumps(x, ensure_ascii=False) + "\n")
        print(f"\n本轮失败 {len(fails)} 条，已写入 {ERR}（重跑本脚本会自动补跑）", flush=True)

    m = A.money_of(dict(usage_tot))
    print(f"\n本轮完成 {n_done} 条，用时 {(time.time()-t0)/60:.1f} 分")
    print(f"本轮成本：空闲 ¥{m['offpeak_cny']:.3f}  高峰 ¥{m['peak_cny']:.3f}")
    print(f"累计结果文件 {RES} 共 {len(done_ids())} 条")


if __name__ == "__main__":
    main()
