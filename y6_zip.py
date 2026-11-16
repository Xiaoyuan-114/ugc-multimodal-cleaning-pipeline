# -*- coding: utf-8 -*-
"""Y6：把交付根目录打成 zip。图片用 STORED（JPEG 压不动，省时间），文本用 DEFLATED。"""
import os, sys, zipfile, time, hashlib
import config as C

ROOT = C.DELIVERY_ROOT
OUT = C.DELIVERY_ZIP
TOP = C.DELIVERY_TOP_NAME

DEFLATE_EXT = {".txt", ".json", ".jsonl", ".csv", ".md", ".py"}
SKIP_DIRS = {"__pycache__", ".venv", ".git"}

def main():
    os.makedirs(os.path.dirname(os.path.abspath(OUT)) or ".", exist_ok=True)
    if os.path.exists(OUT):
        os.remove(OUT)
    t0 = time.time()
    n = 0
    total = 0
    with zipfile.ZipFile(OUT, "w", allowZip64=True) as z:
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                arc = os.path.join(TOP, os.path.relpath(fp, ROOT)).replace(os.sep, "/")
                ext = os.path.splitext(fn)[1].lower()
                comp = zipfile.ZIP_DEFLATED if ext in DEFLATE_EXT else zipfile.ZIP_STORED
                z.write(fp, arc, compress_type=comp, compresslevel=1 if comp == zipfile.ZIP_DEFLATED else None)
                n += 1
                sz = os.path.getsize(fp)
                total += sz
                if n % 2000 == 0:
                    print(f"  {n} 文件  {total/1024**3:.2f} GB 原始  {time.time()-t0:.0f}s", flush=True)
    zsz = os.path.getsize(OUT)
    print(f"完成：{n} 个文件")
    print(f"原始 {total/1024**3:.2f} GB → 压缩包 {zsz/1024**3:.2f} GB")
    print(f"用时 {time.time()-t0:.0f}s")
    print("路径:", OUT)

    # 校验：能打开、条目数一致、抽样读（读时自动校验 CRC）
    import random
    with zipfile.ZipFile(OUT) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        print("zip 条目数:", len(infos))
        must = [f"{TOP}/{p}" for p in C.ZIP_REQUIRED_ENTRIES]
        miss = [p for p in must if p not in names]
        print("关键条目缺失:", miss if miss else "无")
        # 抽样：必备文件 + 随机 400 条（优先覆盖图片）
        sample = list(dict.fromkeys(must + [i.filename for i in random.sample(infos, min(400, len(infos)))]))
        total_bytes = 0
        err = []
        for nm in sample:
            if nm not in names:
                continue
            try:
                total_bytes += len(z.read(nm))
            except Exception as e:
                err.append((nm, repr(e)))
        print(f"抽样读取 {len(sample)} 条，共 {total_bytes/1024**2:.1f} MB，CRC 错误 {len(err)}")
        for nm, e in err[:10]:
            print("  BAD", nm, e)
        # 顶层目录占比
        print("条目扩展名统计:", end=" ")
        from collections import Counter
        c = Counter(os.path.splitext(n)[1].lower() for n in names)
        print(dict(c.most_common(10)))

if __name__ == "__main__":
    main()
