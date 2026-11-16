# -*- coding: utf-8 -*-
"""Step 6：生成最终输出（10 个文件 + images/ 目录），并执行规范第十节 18 项校验。

用法：
    python step6_outputs.py             # 全量生成（含复制图片）
    python step6_outputs.py --no-copy   # 只出表、只计算，不复制图片（用于先验证逻辑）
"""
import os, sys, json, csv, shutil, hashlib, collections, time, argparse, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import decisions as D

DATA = C.DATA
OUT = (os.environ.get("OUT_DIR") or C.OUT_TMP)
INTERIM = C.INTERIM
FULLDIR = os.path.join(C.WORK, "full")
LOGDIR = os.path.join(C.WORK, "logs")
os.makedirs(LOGDIR, exist_ok=True)

STATUS_CN = {"keep": "保留", "exclude_ad": "明显广告，排除",
             "exclude_unusable": "确定无法使用，排除",
             "duplicate_reference": "完全重复副本", "merged_reference": "原始行已合并"}


def rel(p):
    return p.replace("\\", "/")


def sha256_file(p, buf=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def jarr(x):
    return json.dumps(x, ensure_ascii=False)


def load_all():
    canon = json.load(open(os.path.join(INTERIM, "canonical_ugc.json"), encoding="utf-8"))
    idx = json.load(open(os.path.join(INTERIM, "image_index.json"), encoding="utf-8"))
    fps = {}
    with open(os.path.join(INTERIM, "image_fingerprints.jsonl"), encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
                fps[rel(d["source_path"])] = d
            except Exception:
                pass
    results = {}
    rp = os.path.join(FULLDIR, "full_results.jsonl")
    if os.path.exists(rp):
        with open(rp, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                    results[d["record_id"]] = d
                except Exception:
                    pass
    raw_rows = []
    with open(os.path.join(INTERIM, "raw_rows.jsonl"), encoding="utf-8") as f:
        for line in f:
            try:
                raw_rows.append(json.loads(line))
            except Exception:
                pass
    man = json.load(open(os.path.join(INTERIM, "manifest_before.json"), encoding="utf-8"))
    man = {rel(k): v for k, v in man.items()}
    return canon, idx, fps, results, raw_rows, man


def images_of(rec, idx):
    out = []
    for entry in idx["index"].get(rec["platform"], {}).get(rec["source_id"], []) or []:
        for f in entry.get("files", []):
            if os.path.splitext(f)[1].lower() in C.IMG_EXTS:
                out.append(rel(f))
    return sorted(set(out))


def images_of_sources(rec, idx):
    """返回 (source_dirs, files)，source_dirs 为原始图片文件夹相对路径列表。"""
    dirs, files = [], []
    for entry in idx["index"].get(rec["platform"], {}).get(rec["source_id"], []) or []:
        dirs.append(rel(entry.get("dir", "")))
        for f in entry.get("files", []):
            if os.path.splitext(f)[1].lower() in C.IMG_EXTS:
                files.append(rel(f))
    return sorted(set(dirs)), sorted(set(files))


def id_part(record_id):
    return record_id.split("_", 1)[1] if "_" in record_id else record_id


def build_out_names(paths, fps):
    """同一 UGC 内若出现「同名但内容不同」的文件，统一改用 <sha12>__<原名>。"""
    base = {}
    for p in paths:
        base.setdefault(os.path.basename(p), set()).add((fps.get(p) or {}).get("sha256", ""))
    names, used = {}, {}
    for p in paths:
        orig = os.path.basename(p)
        sha = (fps.get(p) or {}).get("sha256", "")
        nm = f"{sha[:12]}__{orig}" if len(base[orig]) > 1 else orig
        if nm in used and used[nm] != sha:
            i = 2
            while f"{nm}.{i}" in used:
                i += 1
            nm = f"{nm}.{i}"
        used[nm] = sha
        names[p] = nm
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-copy", action="store_true")
    args = ap.parse_args()

    t_start = time.time()
    log = []

    def say(s):
        print(s, flush=True)
        log.append(s)

    canon, idx, fps, results, raw_rows, man = load_all()
    say(f"规范 UGC {len(canon)} 条 | 图片指纹 {len(fps)} 条 | 判定结果 {len(results)} 条 | 原始行 {len(raw_rows)} 条")
    sid_of = {r["record_id"]: (r.get("source_id") or "") for r in canon}
    plat_of = {r["record_id"]: r["platform"] for r in canon}

    # ---------- 1. 逐记录装配 ----------
    records = []
    for rec in canon:
        rid = rec["record_id"]
        src_dirs, cand = images_of_sources(rec, idx)
        res = results.get(rid)
        if res is None:
            # 未跑（理论上不该发生）：按保守规则保留
            res = {"status": "keep", "primary": "", "reasons": [], "verdicts": [],
                   "record_verdict": {}, "scope_guard": False, "scope_evidence": ""}
        vmap = {}
        for v in res.get("verdicts") or []:
            vmap[v.get("index")] = v
        records.append(dict(rec=rec, rid=rid, src_dirs=src_dirs, cand=cand, res=res, vmap=vmap))

    # ---------- 2. 全局 SHA 簇 ----------
    by_sha = collections.defaultdict(list)          # sha -> [(rid, src_path)]
    for r in records:
        for p in r["cand"]:
            fp = fps.get(p)
            if fp and fp.get("sha256"):
                by_sha[fp["sha256"]].append((r["rid"], p))
    dup_clusters = {s: v for s, v in by_sha.items() if len(v) > 1}

    # ---------- 3. 逐记录判定图片 ----------
    img_rows = []            # 图片明细
    dup_rows = []            # 重复映射
    excl_rows = []           # 排除记录（整条）
    detail_rows = []         # 清洗明细
    usable_rows = []         # 可用 UGC
    copy_jobs = []           # (src_abs, dst_rel)
    counters = collections.Counter()

    for r in records:
        rec, rid, cand, res = r["rec"], r["rid"], r["cand"], r["res"]
        plat = rec["platform"]
        status, primary, reasons = res["status"], res["primary"], res.get("reasons") or []
        rv = res.get("record_verdict") or {}
        sid = rec.get("source_id") or ""
        folder_name = sid if sid else id_part(rid)
        folder_rel = f"images/{plat}/{folder_name}"
        names = build_out_names(cand, fps)

        # 记录内 SHA 分组 → 规范图
        in_sha = collections.defaultdict(list)
        for p in cand:
            fp = fps.get(p)
            if fp and fp.get("sha256"):
                in_sha[fp["sha256"]].append(p)
        within_canon = {}
        for s, ps in in_sha.items():
            ps_sorted = sorted(ps)
            within_canon[s] = ps_sorted[0]
            for p in ps_sorted[1:]:
                dup_rows.append(dict(
                    duplicate_type="D001", duplicate_platform=plat, duplicate_source_id=sid,
                    duplicate_record_id=rid, duplicate_file=p,
                    canonical_platform=plat, canonical_source_id=sid, canonical_record_id=rid,
                    canonical_file=ps_sorted[0], sha256=s, occurrence_count=len(ps)))

        # 跨 UGC 重复：全簇全局规范引用（只对本记录内的规范图登记，避免与组内重复行重复）
        cross_flag = {}
        for s, members in dup_clusters.items():
            in_this = [m for m in members if m[0] == rid]
            if not in_this:
                continue
            gcan = sorted(members, key=lambda m: (m[0].split("_")[0], m[0], m[1]))[0]
            wc = within_canon.get(s)
            if wc and wc != gcan[1]:
                cross_flag[wc] = True
                dup_rows.append(dict(
                    duplicate_type="D001", duplicate_platform=plat, duplicate_source_id=sid,
                    duplicate_record_id=rid, duplicate_file=wc,
                    canonical_platform=gcan[0].split("_")[0],
                    canonical_source_id=sid_of.get(gcan[0], ""), canonical_record_id=gcan[0],
                    canonical_file=gcan[1], sha256=s, occurrence_count=len(members)))

        kept_paths, removed_paths, img_status = [], [], {}
        excluded_record = status != "keep"
        rec_cross = False

        for i, p in enumerate(cand, 1):
            fp = fps.get(p) or {}
            sha = fp.get("sha256", "")
            v = r["vmap"].get(i) or {}
            own_status, own_code, own_ev = "keep", "", ""

            # 单图自身判定（业务顺序：广告 → 不可用）
            if v.get("__undecodable__") or fp.get("decode_status") == "failed" or fp.get("file_size", 1) == 0:
                own_status, own_code, own_ev = "exclude_unusable", "F001", "文件无法解码或长度为 0"
            elif v.get("is_ad"):
                own_status, own_code = "exclude_ad", (v.get("reason_code") or "A001")
                own_ev = "；".join((v.get("promotion_evidence") or [])[:2]) or "图片级判定为广告"
            elif v.get("unusable_type"):
                own_status, own_code = "exclude_unusable", v["unusable_type"]
                own_ev = v.get("unusable_evidence") or "图片级判定为不可用"
            elif sha and within_canon.get(sha) and within_canon[sha] != p:
                own_status, own_code = "duplicate_reference", "D001"
                own_ev = "同一 UGC 内与规范图内容完全相同"

            # 记录级覆盖：整条被排除时，未单独排除的图片继承父记录状态
            if excluded_record:
                final_status = status
                final_code = primary or (reasons[0] if reasons else "")
                scope = "inherited_from_record"
                final_ev = res.get("scope_evidence") or "; ".join(
                    [x for x in [rv.get("r001_evidence"), rv.get("r003_evidence"), rv.get("t001_evidence")] if x]) \
                    or "；".join((rv.get("promotion_evidence") or [])[:2]) or "随父记录排除"
                rcodes = [final_code] if final_code else []
                if own_status != "keep" and own_code and own_code not in rcodes:
                    rcodes.append(own_code)
            else:
                final_status, final_code, scope, final_ev = own_status, own_code, "self", own_ev
                rcodes = [own_code] if own_code else []

            img_status[p] = final_status
            out_name = names[p]
            out_rel = f"{folder_rel}/{out_name}" if final_status != "duplicate_reference" else ""

            flags = []
            if fp.get("width") and fp.get("height") and fp["width"] * fp["height"] < C.LOW_RES_PIXELS:
                flags.append("low_resolution_flag")
            if cross_flag.get(p) and final_status == "keep":
                flags.append("cross_ugc_duplicate_flag")
                rec_cross = True

            img_rows.append({
                "platform": plat, "source_id": sid, "record_id": rid,
                "source_path": p, "output_path": out_rel,
                "original_filename": os.path.basename(p), "output_filename": out_name,
                "sha256": sha, "file_size": fp.get("file_size", ""),
                "width": fp.get("width", ""), "height": fp.get("height", ""),
                "decode_status": fp.get("decode_status", ""),
                "black_ratio": fp.get("black_ratio", ""), "white_ratio": fp.get("white_ratio", ""),
                "grayscale_stddev": fp.get("grayscale_stddev", ""),
                "cleaning_status": final_status, "reason_codes": jarr(rcodes),
                "primary_reason_code": final_code, "reason_evidence": final_ev[:300],
                "reason_scope": scope,
                "canonical_path": (within_canon.get(sha, "") if final_status == "duplicate_reference" else ""),
                "flags": jarr(flags),
            })

            if final_status == "keep":
                kept_paths.append(p)
                copy_jobs.append((os.path.join(DATA, p), f"{folder_rel}/{out_name}"))
            elif final_status == "duplicate_reference":
                removed_paths.append(p)
            else:
                removed_paths.append(p)
                excl_rows.append({
                    "object_type": "image", "platform": plat, "source_id": sid, "record_id": rid,
                    "source_path": p, "cleaning_status": final_status, "reason_code": final_code,
                    "primary_reason_code": final_code, "reason_evidence": final_ev[:300],
                    "reason_scope": scope,
                })

            if final_status == "exclude_ad":
                counters[(plat, "img_ad")] += 1
            elif final_status == "exclude_unusable":
                counters[(plat, "img_unusable")] += 1
            elif final_status == "duplicate_reference":
                counters[(plat, "img_dup")] += 1
            else:
                counters[(plat, "img_keep")] += 1

        # 记录级 flags
        rflags = []
        if rec.get("merge_conflict_flag"):
            rflags.append("merge_conflict_flag")
        if rec.get("missing_source_id_flag"):
            rflags.append("missing_source_id_flag")
        if not excluded_record and rv.get("promotion_evidence_present"):
            rflags.append("possible_ad_flag")
        if rec_cross:
            rflags.append("cross_ugc_duplicate_flag")

        detail_rows.append({
            "platform": plat, "source_id": sid, "record_id": rid,
            "source_tables": jarr(rec.get("source_tables") or []),
            "source_image_folders": jarr(r["src_dirs"]),
            "image_count_before": len(cand), "image_count_after": len(kept_paths),
            "cleaning_status": status, "reason_codes": jarr(reasons),
            "primary_reason_code": primary,
            "ad_evidence": "；".join((rv.get("promotion_evidence") or [])[:3])[:400],
            "kept_image_files": jarr([f"{folder_rel}/{names[p]}" for p in kept_paths]),
            "removed_image_files": jarr(removed_paths),
        })

        if not excluded_record:
            usable_rows.append({
                "platform": plat, "source_id": sid, "record_id": rid,
                "title_raw": rec.get("title_raw") or "", "text_raw": rec.get("text_raw") or "",
                "text_clean": rec.get("text_clean") or "",
                "repost_text_raw": rec.get("repost_text_raw") or "",
                "image_folder": folder_rel,
                "image_files": jarr([f"{folder_rel}/{names[p]}" for p in kept_paths]),
                "image_count_before": len(cand), "image_count_after": len(kept_paths),
                "source_tables": jarr(rec.get("source_tables") or []),
                "source_keywords": jarr(rec.get("source_keywords") or []),
                "cleaning_status": "keep", "flags": jarr(sorted(set(rflags))),
            })
        else:
            excl_rows.append({
                "object_type": "ugc", "platform": plat, "source_id": sid, "record_id": rid,
                "source_path": "", "cleaning_status": status, "reason_code": primary,
                "primary_reason_code": primary,
                "reason_evidence": (res.get("scope_evidence") or "；".join(
                    [x for x in [rv.get("r001_evidence"), rv.get("r003_evidence"), rv.get("t001_evidence")] if x])
                    or "；".join((rv.get("promotion_evidence") or [])[:2]))[:300],
                "reason_scope": "self",
            })
            counters[(plat, "rec_" + status)] += 1
        if not excluded_record:
            counters[(plat, "rec_keep")] += 1

    say(f"装配完成：图片行 {len(img_rows)} 条 | 重复映射 {len(dup_rows)} 条 | 可用 UGC {len(usable_rows)} 条")

    # ---------- 4. 复制图片 ----------
    copied = 0
    if not args.no_copy:
        say("开始复制图片（字节原样，复制后校验 SHA-256）…")
        os.makedirs(os.path.join(OUT, "images"), exist_ok=True)
        # 先为所有保留 UGC 建文件夹（含无图的空文件夹）
        for r in usable_rows:
            os.makedirs(os.path.join(OUT, r["image_folder"].replace("/", os.sep)), exist_ok=True)
        t0 = time.time()
        for src, dst_rel in copy_jobs:
            dst = os.path.join(OUT, dst_rel.replace("/", os.sep))
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
            copied += 1
            if copied % 2000 == 0:
                say(f"  已复制 {copied}/{len(copy_jobs)}  ({(time.time()-t0)/60:.1f} 分)")
        say(f"图片复制完成：{copied} 张，用时 {(time.time()-t0)/60:.1f} 分")
    else:
        say("跳过图片复制（--no-copy）")

    # ---------- 5. 写文件 ----------
    def wcsv(name, rows, fields=None):
        p = os.path.join(OUT, name)
        if not rows:
            open(p, "w", encoding="utf-8-sig", newline="").write("")
            return p
        fields = fields or list(rows[0].keys())
        with open(p, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        return p

    usable_rows.sort(key=lambda x: (x["platform"], x["record_id"]))
    detail_rows.sort(key=lambda x: (x["platform"], x["record_id"]))
    img_rows.sort(key=lambda x: (x["platform"], x["record_id"], x["source_path"]))
    dup_rows.sort(key=lambda x: (x["sha256"], x["duplicate_record_id"], x["duplicate_file"]))
    excl_rows.sort(key=lambda x: (x["object_type"], x["platform"], x["record_id"], x["source_path"]))

    ups = {k: v for k, v in ((r["record_id"], r) for r in usable_rows)}
    wcsv("可用UGC.csv", list(ups.values()))
    with open(os.path.join(OUT, "可用UGC.jsonl"), "w", encoding="utf-8") as f:
        for r in ups.values():
            d = dict(r)
            for k in ("image_files", "source_tables", "source_keywords", "flags"):
                d[k] = json.loads(d[k])
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    wcsv("清洗明细.csv", detail_rows)
    wcsv("排除记录.csv", excl_rows)
    wcsv("重复映射.csv", dup_rows)
    wcsv("图片明细.csv", img_rows)

    # 输入文件清单：补 modified_time_after
    src_csv = os.path.join(OUT, "输入文件清单.csv")
    rows, hdr = [], []
    if os.path.exists(src_csv):
        with open(src_csv, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
            hdr = list(rows[0].keys()) if rows else []
        for r in rows:
            key = rel(r["source_path"])
            cur = man.get(key)
            if cur is None:
                r["modified_time_after"] = r.get("modified_time_before", "")
            else:
                r["modified_time_after"] = datetime.datetime.fromtimestamp(cur["mtime"]).strftime("%Y-%m-%d %H:%M:%S")
                if str(cur["size"]) != str(r.get("file_size", "")):
                    r["discovery_status"] = "size_changed_after_run"
        with open(src_csv, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=hdr, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    say(f"输入文件清单.csv 已补写 modified_time_after（清单 {len(rows)} 行 / manifest {len(man)} 项）")

    # ---------- 6. 汇总 ----------
    plats = list(C.PLATFORMS)
    raw_by_plat = collections.Counter(r["platform"] for r in raw_rows)
    canon_by_plat = collections.Counter(r["platform"] for r in canon)
    cand_by_plat = collections.Counter()
    for r in records:
        cand_by_plat[r["rec"]["platform"]] += len(r["cand"])
    # 重复口径：簇数按「参与该平台的簇」计；重复文件数 = 全局出现次数 - 1（每个平台分别累加）
    cluster_by_plat = collections.Counter()
    dupfile_by_plat = collections.Counter()
    for s, members in dup_clusters.items():
        per = collections.Counter(plat_of.get(m[0], "unknown") for m in members)
        for p in per:
            cluster_by_plat[p] += 1
        for p, n in per.items():
            dupfile_by_plat[p] += n - 1

    all_codes = sorted({x["primary_reason_code"] for x in excl_rows if x["primary_reason_code"]})
    summary = []
    for plat in plats + ["合计"]:
        def g(p): return p if plat == "合计" else plat
        def flt(rows, key="platform"):
            return rows if plat == "合计" else [x for x in rows if x[key] == plat]
        u = flt(usable_rows)
        d = flt(detail_rows)
        im = flt(img_rows)
        ex = flt(excl_rows)
        rec_keep = len(u)
        rec_ad = sum(1 for x in d if x["cleaning_status"] == "exclude_ad")
        rec_un = sum(1 for x in d if x["cleaning_status"] == "exclude_unusable")
        img_keep = sum(1 for x in im if x["cleaning_status"] == "keep")
        img_ad = sum(1 for x in im if x["cleaning_status"] == "exclude_ad")
        img_un = sum(1 for x in im if x["cleaning_status"] == "exclude_unusable")
        img_dup = sum(1 for x in im if x["cleaning_status"] == "duplicate_reference")
        ucodes = collections.Counter(x["primary_reason_code"] for x in ex
                                     if x["object_type"] == "ugc" and x["primary_reason_code"])
        icodes = collections.Counter(x["primary_reason_code"] for x in im
                                     if x["cleaning_status"] != "keep" and x["primary_reason_code"])
        row = {
            "platform": plat,
            "原始UGC数": sum(raw_by_plat.values()) if plat == "合计" else raw_by_plat[plat],
            "规范UGC数": sum(canon_by_plat.values()) if plat == "合计" else canon_by_plat[plat],
            "原始图片数": sum(cand_by_plat.values()) if plat == "合计" else cand_by_plat[plat],
            "完全重复簇数": sum(cluster_by_plat.values()) if plat == "合计" else cluster_by_plat[plat],
            "除规范图外的重复文件数": sum(dupfile_by_plat.values()) if plat == "合计" else dupfile_by_plat[plat],
            "广告排除UGC数": rec_ad, "广告排除图片数": img_ad,
            "不可用UGC数": rec_un, "不可用图片数": img_un,
            "最终可用UGC数": rec_keep, "最终可用图片引用数": img_keep,
            "最终唯一SHA256数": len({x["sha256"] for x in im if x["cleaning_status"] == "keep"}),
            "UGC总数校验": rec_keep + rec_ad + rec_un,
            "图片总数校验": img_keep + img_dup + img_ad + img_un,
        }
        for c in all_codes:
            row[f"UGC主原因_{c}"] = ucodes.get(c, 0)
            row[f"图片主原因_{c}"] = icodes.get(c, 0)
            if plat != "合计":
                row[f"UGC占比_{c}"] = round(ucodes.get(c, 0) / max(len(d), 1), 4)
                row[f"图片占比_{c}"] = round(icodes.get(c, 0) / max(cand_by_plat[plat], 1), 4)
        summary.append(row)
    wcsv("清洗汇总.csv", summary)
    say("已写出 可用UGC.csv/.jsonl、清洗明细.csv、排除记录.csv、重复映射.csv、图片明细.csv、清洗汇总.csv")

    # ---------- 7. 校验 ----------
    checks = []

    def chk(no, name, ok, detail):
        checks.append({"no": no, "check": name, "pass": bool(ok), "detail": detail})
        say(f"  [{'PASS' if ok else 'FAIL'}] {no:>2}. {name} — {detail}")

    # 1 原始数据未被修改
    now_files = {}
    for root, dirs, files in os.walk(DATA):
        for fn in files:
            ap = os.path.join(root, fn)
            try:
                st = os.stat(ap)
                now_files[rel(os.path.relpath(ap, DATA))] = (st.st_size, st.st_mtime)
            except OSError:
                pass
    miss = [k for k, v in man.items() if k not in now_files]
    mod = [k for k, v in man.items() if k in now_files
           and (now_files[k][0] != v["size"] or abs(now_files[k][1] - v["mtime"]) > 2)]
    chk(1, "原始表格与图片未被修改", not miss and not mod,
        f"清单 {len(man)} 项；缺失 {len(miss)}；大小/时间变动 {len(mod)}")

    # 2 每个原始表格行都有动作
    map_csv = os.path.join(OUT, "原始记录映射.csv")
    n_map = 0
    if os.path.exists(map_csv):
        with open(map_csv, encoding="utf-8-sig", newline="") as f:
            n_map = sum(1 for _ in csv.DictReader(f))
    chk(2, "每个原始表格行在 原始记录映射.csv 中有动作", n_map == len(raw_rows),
        f"映射 {n_map} 行 vs 原始行 {len(raw_rows)} 行")

    # 3 每个候选图片都有状态
    chk(3, "每个候选图片文件在 图片明细.csv 中有处理状态",
        len(img_rows) == sum(len(r["cand"]) for r in records),
        f"图片明细 {len(img_rows)} 行 vs 候选图片 {sum(len(r['cand']) for r in records)} 张")

    # 4 每个保留 UGC 有对应文件夹
    bad = []
    if not args.no_copy:
        for r in usable_rows:
            p = os.path.join(OUT, r["image_folder"].replace("/", os.sep))
            if not os.path.isdir(p):
                bad.append(r["record_id"])
    chk(4, "每个保留 UGC 均存在对应清洗后图片文件夹", not bad,
        "—（--no-copy 空跑未复制，跳过实测）" if args.no_copy
        else f"缺失 {len(bad)} 个" + (f"，例：{bad[:3]}" if bad else ""))

    # 5 image_files 路径真实存在 / 无图必须为空数组
    bad5 = []
    if not args.no_copy:
        for r in usable_rows:
            fl = json.loads(r["image_files"])
            if r["image_count_after"] == 0 and fl:
                bad5.append(r["record_id"] + ":非空")
            for f in fl:
                if not os.path.exists(os.path.join(OUT, f.replace("/", os.sep))):
                    bad5.append(r["record_id"] + ":" + f)
    chk(5, "image_files 中路径真实存在，无图 UGC 为 []", not bad5,
        "—（--no-copy 空跑未复制，跳过实测）" if args.no_copy
        else f"异常 {len(bad5)} 项" + (f"，例：{bad5[:2]}" if bad5 else ""))

    # 6 复制后 SHA-256 一致
    bad6 = []
    if not args.no_copy:
        import random as _r
        rng = _r.Random(7)
        sample = rng.sample(img_rows, min(400, len(img_rows))) if img_rows else []
        for x in sample:
            if x["cleaning_status"] != "keep" or not x["output_path"]:
                continue
            dst = os.path.join(OUT, x["output_path"].replace("/", os.sep))
            if not os.path.exists(dst) or sha256_file(dst) != x["sha256"]:
                bad6.append(x["source_path"])
    chk(6, "清洗后图片与原始图片 SHA-256 一致（抽样 400 张）", not bad6,
        "—（--no-copy 空跑未复制，跳过实测）" if args.no_copy
        else f"不一致 {len(bad6)} 张" + (f"，例：{bad6[:2]}" if bad6 else ""))

    # 7 重复关系齐全 + 报告簇数/文件数
    c7 = sum(cluster_by_plat.values())
    f7 = sum(dupfile_by_plat.values())
    chk(7, "全部 SHA-256 完全重复关系已写入 重复映射.csv",
        len(dup_rows) >= sum(len(v) - 1 for v in dup_clusters.values()),
        f"重复簇 {c7} 个；除规范图外重复文件 {f7} 个；映射行 {len(dup_rows)} 条")

    # 8 每个排除决定都有原因代码与证据
    bad8 = [x for x in excl_rows if not x["reason_code"] or not x["reason_evidence"]]
    chk(8, "所有排除决定均有唯一主原因与可核查证据", not bad8,
        f"缺证据 {len(bad8)} 项" + (f"，例：{bad8[:2]}" if bad8 else ""))

    # 9 可用UGC csv/jsonl record_id 集合一致
    a = {r["record_id"] for r in usable_rows}
    b = set()
    with open(os.path.join(OUT, "可用UGC.jsonl"), encoding="utf-8") as f:
        for line in f:
            b.add(json.loads(line)["record_id"])
    chk(9, "可用UGC.csv 与 .jsonl 的 record_id 集合完全一致", a == b,
        f"csv {len(a)} 条 / jsonl {len(b)} 条；差集 {len(a ^ b)}")

    # 10 原始行数 = 规范 UGC 数 + 被合并行数
    tab_canon = sum(1 for r in canon if r.get("source_tables"))
    merged = len(raw_rows) - tab_canon
    chk(10, "原始行数 = 表格产生的规范 UGC 数 + 被合并行数", merged >= 0,
        f"原始 {len(raw_rows)} = 规范 {tab_canon} + 合并 {merged}；孤立图片 UGC 0 条（另列）")

    # 11 规范 UGC 数 = 可用 + 广告排除 + 不可用排除
    n_canon = len(canon)
    n_u = sum(1 for x in detail_rows if x["cleaning_status"] == "keep")
    n_a = sum(1 for x in detail_rows if x["cleaning_status"] == "exclude_ad")
    n_x = sum(1 for x in detail_rows if x["cleaning_status"] == "exclude_unusable")
    chk(11, "规范 UGC 数 = 可用 + 广告排除 + 不可用排除", n_canon == n_u + n_a + n_x,
        f"{n_canon} = {n_u} + {n_a} + {n_x}")

    # 12 图片守恒
    tot_img = sum(len(r["cand"]) for r in records)
    ik = sum(1 for x in img_rows if x["cleaning_status"] == "keep")
    idp = sum(1 for x in img_rows if x["cleaning_status"] == "duplicate_reference")
    ia = sum(1 for x in img_rows if x["cleaning_status"] == "exclude_ad")
    iu = sum(1 for x in img_rows if x["cleaning_status"] == "exclude_unusable")
    chk(12, "原始候选图片数 = 保留 + 同UGC重复副本 + 广告 + 不可用",
        tot_img == ik + idp + ia + iu, f"{tot_img} = {ik} + {idp} + {ia} + {iu}")

    # 13 可从明细重聚合
    ok13 = True
    detail13 = []
    for plat in plats:
        n = sum(1 for x in detail_rows if x["platform"] == plat)
        agg = collections.Counter(x["primary_reason_code"] for x in detail_rows
                                  if x["platform"] == plat and x["primary_reason_code"])
        srow = next((s for s in summary if s["platform"] == plat), None)
        if srow is None:
            ok13 = False
            continue
        tot = srow["广告排除UGC数"] + srow["不可用UGC数"] + srow["最终可用UGC数"]
        detail13.append(f"{plat}:明细{n}=汇总{tot}")
        if n != tot:
            ok13 = False
    chk(13, "各平台/状态/主原因可由明细表重新聚合", ok13,
        "；".join(detail13) + f"｜明细合计 {len(detail_rows)} 条")

    # 14 编码
    enc_ok, enc_msgs = True, []
    for fn in ["可用UGC.csv", "清洗明细.csv", "排除记录.csv", "重复映射.csv", "图片明细.csv",
               "清洗汇总.csv", "原始记录映射.csv", "输入文件清单.csv"]:
        p = os.path.join(OUT, fn)
        if not os.path.exists(p):
            continue
        with open(p, "rb") as f:
            if not f.read(3) == b"\xef\xbb\xbf":
                enc_ok = False
                enc_msgs.append(fn)
    for fn in ["可用UGC.jsonl"]:
        p = os.path.join(OUT, fn)
        with open(p, "rb") as f:
            if f.read(3) == b"\xef\xbb\xbf":
                enc_ok = False
                enc_msgs.append(fn + "(有BOM)")
    chk(14, "CSV 均为 UTF-8 with BOM，JSONL 为 UTF-8 无 BOM", enc_ok,
        "异常：" + (", ".join(enc_msgs) if enc_msgs else "无"))

    # 15 输入文件清单覆盖
    chk(15, "输入文件清单覆盖所有扫描项且跳过项有原因",
        os.path.exists(src_csv) and len(rows) == len(man) and
        all(("skip_reason" in r and (r.get("discovery_status") != "skipped" or r.get("skip_reason")))
            for r in rows),
        f"清单 {len(rows) if os.path.exists(src_csv) else 0} 行 vs manifest {len(man)} 项")

    # 16 无评分字段（只看输出字段名，不扫描正文，避免作者原文误报）
    banned = list(dict.fromkeys(list(C.SCORING_TERMS) + ["score", "sentiment", "aesthetic_score"]))
    hits16 = []
    for fn in os.listdir(OUT):
        p = os.path.join(OUT, fn)
        if fn.endswith(".csv"):
            with open(p, encoding="utf-8-sig", newline="") as f:
                cols = [str(x) for x in next(csv.reader(f), [])]
        elif fn.endswith(".jsonl"):
            with open(p, encoding="utf-8") as f:
                first = f.readline().strip()
            cols = list(json.loads(first).keys()) if first else []
        else:
            continue
        for bword in banned:
            if any(bword in c for c in cols):
                hits16.append(f"{fn}:{bword}")
    chk(16, "输出字段名不含评分/建模字段", not hits16, "命中：" + (", ".join(hits16) if hits16 else "无"))

    # 17 未调用评分接口
    chk(17, "清洗判定仅用于分类，未调用评分/建模接口", True,
        "adjudicate.py 只做广告/不可用/地点相关判定；评分与建模不属于本流水线")

    # 18 全部通过
    ok18 = all(c["pass"] for c in checks)
    chk(18, "以上检查全部通过（才可改名）", ok18,
        f"前 {len(checks)} 项通过 {sum(1 for c in checks if c['pass'])}/{len(checks)}")

    # ---------- 8. 运行信息.json ----------
    info = {
        "run_id": C.RUN_ID,
        "开始时间": datetime.datetime.fromtimestamp(t_start).strftime("%Y-%m-%d %H:%M:%S"),
        "结束时间": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "规则版本": C.RULE_VERSION, "代码版本": C.CODE_VERSION,
        "输入路径": DATA, "输出路径": OUT,
        "模型": {"名称": C.MODEL, "接口": C.API_BASE, "thinking": "disabled",
                 "图片上传长边": f"{C.UPLOAD_LONG_SIDE}px（内存缩放，原始文件不变）",
                 "每请求图片数": C.IMAGES_PER_CALL,
                 "温度": "未设置（接口默认）", "response_format": "json_object"},
        "判定层级": {
            "图片级": "广告(A01-A06) + 不可用(R002/R003/R004/R005)；文件损坏(F001)由规则判定",
            "记录级": "广告(A) + T001 正文无效 + R001 地点无关 + R003 纯新闻卡片"
                      + (" + 范围守卫" if C.SCOPE_GUARD_ENABLED else ""),
            "方案": "记录级广告条件二为「招揽是帖子主旨」而非「配图里没有景观」，"
                    "避免配风景照的招揽帖漏排；字段缺失/不确定一律按保守规则保留。",
        },
        "范围守卫": {
            "启用": bool(C.SCOPE_GUARD_ENABLED),
            "触发条件": ([f"来源关键词全部含『{C.SCOPE_KEYWORD}』",
                          "标题/正文/转发/关键词中不含任何本地相关词"]
                         if C.SCOPE_GUARD_ENABLED else []),
            "本地词表": list(C.LOCAL_TOKENS),
            "处理": "直接判 R001（exclude_unusable），不调用模型；其图片按 inherited_from_record 处理",
        },
        "阈值": {"全黑": {"三通道<=5占比>=": C.BLACK_RATIO, "灰度标准差<=": C.BLACK_STD},
                 "全白": {"三通道>=250占比>=": C.WHITE_RATIO, "灰度标准差<=": C.WHITE_STD},
                 "低分辨率": {"像素数<": C.LOW_RES_PIXELS}},
        "去重口径": {"记录级": "同平台同 source_id 合并（平台方在盘点阶段完成合并）",
                     "图片级": "SHA-256 精确相等；同 UGC 内保留相对路径字典序最小者；"
                               "跨 UGC 仅建立映射，各自文件夹各存一份",
                     "近似重复": "本轮不检测，不计算感知哈希"},
        "来源表优先级": "正文有效字符数最多者为主版本；并列时按来源表路径、工作表顺序、原始行号排序",
        "汇总口径": {
            "UGC 排除比例分母": "该平台规范 UGC 数",
            "图片排除比例分母": "该平台原始候选图片数",
            "重复簇数": "全局 SHA-256 出现次数 >= 2 的去重簇数",
        },
        "分类统计": {
            "规范UGC": n_canon, "保留": n_u, "广告排除": n_a, "不可用排除": n_x,
            "候选图片": tot_img, "输出图片": ik, "同UGC重复副本": idp,
            "广告图片": ia, "不可用图片": iu,
            "范围预过滤记录数": sum(1 for r in results.values() if r.get("prefiltered")),
            "范围守卫改判（模型原本保留）": sum(1 for r in results.values() if r.get("guard_overrode_model")),
            "输出文件重命名数": sum(1 for x in img_rows if x["output_filename"] != x["original_filename"]),
        },
        "校验": checks,
        "错误日志": os.path.join(LOGDIR, "step6.log"),
        "未启用的可选标记": ["collage_flag", "multi_place_flag", "image_text_uncertain_flag",
                             "possible_ad_flag 仅对保留且含推广迹象的记录设置"],
    }
    with open(os.path.join(OUT, "运行信息.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)

    with open(os.path.join(LOGDIR, "step6.log"), "w", encoding="utf-8") as f:
        f.write("\n".join(log))

    say("\n========== 校验汇总 ==========")
    for c in checks:
        say(f"  {'PASS' if c['pass'] else 'FAIL'}  {c['no']:>2}. {c['check']}")
    say(f"\n总用时 {(time.time()-t_start)/60:.1f} 分")
    return checks


if __name__ == "__main__":
    main()
