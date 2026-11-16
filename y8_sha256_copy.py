# -*- coding: utf-8 -*-
"""Y8：对交付目录中的清洗数据副本做源/目标全量 SHA-256 比对。"""
import os, hashlib, json, time
from concurrent.futures import ProcessPoolExecutor
import config as C

SRC = C.CLEAN_DIR
DST = os.path.join(C.DELIVERY_ROOT, C.D_CLEAN_COPY)


def walk_rel(root):
    out = []
    for r, d, fs in os.walk(root):
        for f in fs:
            fp = os.path.join(r, f)
            out.append(os.path.relpath(fp, root))
    return sorted(out)


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def pair(rel):
    try:
        a = sha(os.path.join(SRC, rel))
        b = sha(os.path.join(DST, rel))
        return (rel, a == b, a, b)
    except Exception as e:
        return (rel, False, repr(e), '')


if __name__ == '__main__':
    t0 = time.time()
    rels = walk_rel(SRC)
    print('files=%d' % len(rels))
    bad = []
    with ProcessPoolExecutor(max_workers=8) as ex:
        for i, (rel, ok, a, b) in enumerate(ex.map(pair, rels, chunksize=32), 1):
            if not ok:
                bad.append((rel, a, b))
            if i % 2000 == 0:
                print('  ...%d/%d bad=%d' % (i, len(rels), len(bad)))
    print('SHA256 checked=%d mismatch=%d in %.0fs' % (len(rels), len(bad), time.time() - t0))
    for r, a, b in bad[:20]:
        print('  BAD', r, a[:16], b[:16])
    json.dump({'checked': len(rels), 'mismatch': len(bad), 'bad': bad[:50]},
              open(os.path.join(C.WORK, '_copy_sha256.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)
