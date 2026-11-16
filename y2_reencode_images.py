# -*- coding: utf-8 -*-
"""Y2：把保留图片统一重编码为「长边 ≤ MAXSIDE / JPEG qQUALITY」，输出到 stimuli/ 下。
   原图不覆盖；输出剥离 EXIF（同时避免位置元数据泄漏）。多进程 + 断点续跑。"""
import os, io, json, hashlib, time, sys
from multiprocessing import Pool
from PIL import Image
import config as C

SRC = C.CLEAN_DIR
ROOT = C.DELIVERY_ROOT
STIM = os.path.join(ROOT, C.D_SAMPLES, "stimuli")
LOG = os.path.join(C.WORK, "_reencode_log.jsonl")
LEDGER = os.path.join(C.WORK, "_ledger.json")

MAXSIDE = C.MAXSIDE
QUALITY = C.JPEG_QUALITY

def sha256(p, buf=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

_ledger = None
def _init(led):
    global _ledger
    _ledger = led

def work(task):
    """task = (sample_id, record_id, rel_path)"""
    sid, rid, rel = task
    src = os.path.join(SRC, rel.replace("/", os.sep))
    dst = os.path.join(STIM, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    rec = {"sample_id": sid, "record_id": rid, "src": rel, "dst": os.path.relpath(dst, ROOT).replace(os.sep, "/")}
    try:
        rec["orig_bytes"] = os.path.getsize(src)
        with Image.open(src) as im:
            rec["orig_w"], rec["orig_h"] = im.size
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            w, h = im.size
            m = max(w, h)
            if m > MAXSIDE:
                s = MAXSIDE / m
                nw, nh = max(1, round(w * s)), max(1, round(h * s))
                im = im.resize((nw, nh), Image.LANCZOS)
                rec["resized"] = True
            else:
                rec["resized"] = False
            rec["out_w"], rec["out_h"] = im.size
            im.save(dst, format="JPEG", quality=QUALITY, optimize=True, progressive=False)
        rec["out_bytes"] = os.path.getsize(dst)
        rec["sha256_orig"] = sha256(src)
        rec["sha256_stim"] = sha256(dst)
        # 二次校验：输出必须可解码
        with Image.open(dst) as chk:
            chk.verify()
        rec["ok"] = True
    except Exception as e:
        rec["ok"] = False
        rec["error"] = f"{type(e).__name__}: {e}"
    return rec

def main():
    with io.open(LEDGER, encoding="utf-8") as f:
        ledger = json.load(f)

    tasks = []
    for item in ledger:
        for rel in item["image_files"]:
            tasks.append((item["sample_id"], item["record_id"], rel))
    print(f"待处理图片 {len(tasks)} 张", flush=True)

    done = set()
    if os.path.isfile(LOG):
        with io.open(LOG, encoding="utf-8") as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                    if r.get("ok"):
                        done.add(r["src"])
                except Exception:
                    pass
    if done:
        tasks = [t for t in tasks if t[2] not in done]
        print(f"已完成 {len(done)} 张，剩余 {len(tasks)} 张", flush=True)

    t0 = time.time()
    n_ok = n_bad = 0
    with io.open(LOG, "a", encoding="utf-8") as logf, Pool(processes=8) as pool:
        for i, rec in enumerate(pool.imap_unordered(work, tasks, chunksize=16), 1):
            logf.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if rec.get("ok"):
                n_ok += 1
            else:
                n_bad += 1
                print("FAIL", rec["src"], rec.get("error"), flush=True)
            if i % 1000 == 0:
                logf.flush()
                print(f"  {i}/{len(tasks)}  ok={n_ok} bad={n_bad}  {time.time()-t0:.0f}s", flush=True)
    print(f"完成：ok={n_ok} bad={n_bad}  用时 {time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    main()
