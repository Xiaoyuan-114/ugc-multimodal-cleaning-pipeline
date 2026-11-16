# -*- coding: utf-8 -*-
"""Y7：逐文件比对 源 -> 交付目录，补齐缺失/大小不符的文件。"""
import os, sys, shutil, time, json
import config as C

SRC = C.CLEAN_DIR
DST = os.path.join(C.DELIVERY_ROOT, C.D_CLEAN_COPY)


def walk_rel(root):
    m = {}
    for r, d, fs in os.walk(root):
        for f in fs:
            fp = os.path.join(r, f)
            rel = os.path.relpath(fp, root)
            try:
                m[rel] = os.path.getsize(fp)
            except OSError:
                m[rel] = -1
    return m


t0 = time.time()
s = walk_rel(SRC)
d = walk_rel(DST)
print(f'src files={len(s)} dst files={len(d)}')

missing = [k for k in s if k not in d]
sizemis = [k for k in s if k in d and d[k] != s[k]]
extra = [k for k in d if k not in s]
print(f'missing={len(missing)} sizemis={len(sizemis)} extra={len(extra)}')
for k in missing[:10]:
    print('  MISS', k)
for k in sizemis[:10]:
    print('  SIZE', k, s[k], d[k])
for k in extra[:10]:
    print('  EXTRA', k)

todo = missing + sizemis
ok = 0
fail = []
for i, rel in enumerate(todo, 1):
    sp = os.path.join(SRC, rel)
    dp = os.path.join(DST, rel)
    os.makedirs(os.path.dirname(dp), exist_ok=True)
    try:
        shutil.copyfile(sp, dp)
        if os.path.getsize(dp) == s[rel]:
            ok += 1
        else:
            fail.append((rel, 'size mismatch after copy'))
    except Exception as e:
        fail.append((rel, repr(e)))
    if i % 50 == 0:
        print(f'  ...{i}/{len(todo)}')

print(f'repaired ok={ok} fail={len(fail)} in {time.time()-t0:.0f}s')
for k, e in fail[:20]:
    print('  FAIL', k, e)

# 最终复核
d2 = walk_rel(DST)
still = [k for k in s if k not in d2 or d2[k] != s[k]]
print('FINAL src=%d dst=%d unresolved=%d' % (len(s), len(d2), len(still)))
for k in still[:20]:
    print('  STILL', k)
json.dump({'src': len(s), 'dst': len(d2), 'unresolved': still},
          open(os.path.join(C.WORK, '_copy_verify.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=2)
