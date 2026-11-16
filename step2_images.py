# -*- coding: utf-8 -*-
"""Step 2：为全部原始候选图片计算 SHA-256、解码状态、全黑/全白比例、灰度标准差。
可中断续跑：结果逐条追加到 image_fingerprints.jsonl。"""
import os, sys, json, hashlib, time, threading, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image, ImageChops

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C

Image.MAX_IMAGE_PIXELS = None
OUT_JSONL = os.path.join(C.INTERIM, "image_fingerprints.jsonl")
LOCK = threading.Lock()
COUNTER = {"done": 0, "ok": 0, "fail": 0, "scaled": 0}


def rel(p):
    return os.path.relpath(p, C.DATA).replace("\\", "/")


def sha256_file(p, chunk=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def analyze(p):
    r = rel(p)
    rec = {"source_path": r, "file_size": os.path.getsize(p)}
    try:
        rec["sha256"] = sha256_file(p)
        with Image.open(p) as im:
            w0, h0 = im.size
            rec["width"], rec["height"] = w0, h0
            rec["format"] = im.format
            rec["mode"] = im.mode
            scaled = False
            if w0 * h0 > C.STATS_PIXEL_CAP and (im.format or "").upper() == "JPEG":
                s = (C.STATS_PIXEL_CAP / (w0 * h0)) ** 0.5
                im.draft("RGB", (max(1, int(w0 * s)), max(1, int(h0 * s))))
                scaled = True
            im.load()
            rgb = im.convert("RGB")
            sw, sh = rgb.size
            sn = sw * sh
            rr, gg, bb = rgb.getchannel("R"), rgb.getchannel("G"), rgb.getchannel("B")
            mx = ImageChops.lighter(ImageChops.lighter(rr, gg), bb)
            mn = ImageChops.darker(ImageChops.darker(rr, gg), bb)
            hmx = mx.histogram()
            hmn = mn.histogram()
            rec["black_ratio"] = round(sum(hmx[: C.BLACK_MAX + 1]) / sn, 6)
            rec["white_ratio"] = round(sum(hmn[C.WHITE_MIN:]) / sn, 6)
            gl = rgb.convert("L").histogram()
            mean = sum(i * c for i, c in enumerate(gl)) / sn
            var = sum((i - mean) ** 2 * c for i, c in enumerate(gl)) / sn
            rec["grayscale_stddev"] = round(var ** 0.5, 4)
            rec["stats_scaled"] = scaled
            rec["decode_status"] = "ok"
            if scaled:
                with LOCK:
                    COUNTER["scaled"] += 1
    except Exception as e:
        rec["sha256"] = rec.get("sha256", "")
        rec["decode_status"] = "failed"
        rec["decode_error"] = f"{type(e).__name__}: {e}"[:200]
        rec.setdefault("width", None)
        rec.setdefault("height", None)
        rec.setdefault("black_ratio", None)
        rec.setdefault("white_ratio", None)
        rec.setdefault("grayscale_stddev", None)
        with LOCK:
            COUNTER["fail"] += 1
    return rec


def collect():
    files = []
    for dirs in C.IMAGE_DIRS.values():
        for d in dirs:
            p = os.path.join(C.DATA, d)
            for dp, dn, fn in os.walk(p):
                for f in fn:
                    if os.path.splitext(f)[1].lower() in C.IMG_EXTS:
                        files.append(os.path.join(dp, f))
    files.sort(key=rel)
    return files


def main():
    files = collect()
    done = set()
    if os.path.exists(OUT_JSONL):
        with open(OUT_JSONL, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["source_path"])
                except Exception:
                    pass
    todo = [p for p in files if rel(p) not in done]
    print(f"候选图片 {len(files)} 张，已完成 {len(done)}，待处理 {len(todo)}", flush=True)
    if not todo:
        print("全部完成", flush=True)
        return

    t0 = time.time()
    n = 0
    fh = open(OUT_JSONL, "a", encoding="utf-8")
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(analyze, p): p for p in todo}
        for fut in as_completed(futs):
            try:
                rec = fut.result()
            except Exception:
                rec = {"source_path": rel(futs[fut]), "decode_status": "failed",
                       "decode_error": traceback.format_exc()[:200]}
            with LOCK:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
                if n % 500 == 0:
                    fh.flush()
                    el = time.time() - t0
                    rate = n / el
                    eta = (len(todo) - n) / rate if rate else 0
                    print(f"  {n}/{len(todo)}  {rate:.1f} 张/秒  已用 {el/60:.1f} 分  "
                          f"预计剩余 {eta/60:.1f} 分  失败 {COUNTER['fail']}  降采样 {COUNTER['scaled']}",
                          flush=True)
    fh.close()
    print(f"\n完成 {n} 张，用时 {(time.time()-t0)/60:.1f} 分", flush=True)
    print(f"解码失败 {COUNTER['fail']} 张，降采样统计 {COUNTER['scaled']} 张", flush=True)


if __name__ == "__main__":
    main()
