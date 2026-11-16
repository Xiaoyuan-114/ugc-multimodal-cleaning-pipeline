# -*- coding: utf-8 -*-
"""Y10：把交付 zip 切成两卷（只读原文件，绝不改动）。一次遍历同时算出三份 SHA-256。

用法：
    python y10_split_zip.py [expected_sha256]

不传 expected_sha256 时只报告哈希，不做一致性判断。
"""
import os, sys, hashlib, time
import config as C

SRC = C.DELIVERY_ZIP
OUTD = C.SPLIT_DIR
NAME = os.path.basename(SRC)
P1 = os.path.join(OUTD, NAME + ".part1of2")
P2 = os.path.join(OUTD, NAME + ".part2of2")
BS = 8 * 1024 * 1024

if not os.path.isfile(SRC):
    raise SystemExit(f"找不到待分卷文件：{SRC}")

size = os.path.getsize(SRC)
half = size // 2
half -= half % 512          # 对齐到扇区边界，纯为整洁
os.makedirs(OUTD, exist_ok=True)

h1 = hashlib.sha256()
h2 = hashlib.sha256()
ht = hashlib.sha256()
t0 = time.time()
done = 0
f1 = open(P1, "wb")
f2 = open(P2, "wb")
with open(SRC, "rb") as f:
    while True:
        b = f.read(BS)
        if not b:
            break
        ht.update(b)
        off = done
        done += len(b)
        if off < half:
            n1 = min(len(b), half - off)
            f1.write(b[:n1]); h1.update(b[:n1])
            if n1 < len(b):
                f2.write(b[n1:]); h2.update(b[n1:])
        else:
            f2.write(b); h2.update(b)
f1.close(); f2.close()

s1 = os.path.getsize(P1)
s2 = os.path.getsize(P2)
expected = (sys.argv[1] if len(sys.argv) > 1 else getattr(C, "EXPECTED_SHA256", "")).strip().lower()
print("原文件      : %d bytes (%.3f GB)" % (size, size / 1024 ** 3))
print("part1of2    : %d bytes (%.3f GB)" % (s1, s1 / 1024 ** 3))
print("part2of2    : %d bytes (%.3f GB)" % (s2, s2 / 1024 ** 3))
print("两卷之和一致: %s" % (s1 + s2 == size))
print()
print("part1 SHA256: %s" % h1.hexdigest())
print("part2 SHA256: %s" % h2.hexdigest())
print("拼接后 SHA256: %s" % ht.hexdigest())
print("与预期一致    : %s" % ("未提供预期值" if not expected else ht.hexdigest() == expected))
print("耗时 %.0fs" % (time.time() - t0))

# 写校验文件（每卷一份 + 合并后一份），LF / UTF-8 无 BOM
with open(os.path.join(OUTD, "分卷校验值.sha256"), "w", encoding="utf-8", newline="\n") as w:
    w.write("%s  %s.part1of2\n" % (h1.hexdigest(), NAME))
    w.write("%s  %s.part2of2\n" % (h2.hexdigest(), NAME))
with open(os.path.join(OUTD, NAME + ".sha256"), "w", encoding="utf-8", newline="\n") as w:
    w.write("%s  %s\n" % (ht.hexdigest(), NAME))
print("校验文件已写入")