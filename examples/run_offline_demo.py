# -*- coding: utf-8 -*-
"""离线跑通 demo：step1–step3 → 伪判定结果 → step6/7 → y1–y10。

不调用任何模型。step4/step5 的真实模型判定不在本 demo 范围内。
用法：
    python examples/run_offline_demo.py
"""
import os, sys, json, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CONFIG = os.path.join(HERE, "demo_config.py")
DEMO = os.path.join(HERE, "demo")
ENV = dict(os.environ, UGC_CONFIG=CONFIG, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")


def run(script, *args, env=None):
    print(f"\n=== {script} {' '.join(args)} ===", flush=True)
    e = dict(ENV)
    e.update(env or {})
    r = subprocess.run([sys.executable, os.path.join(REPO, script), *args], env=e, cwd=REPO)
    if r.returncode != 0:
        raise SystemExit(f"{script} 失败，退出码 {r.returncode}")


def fabricate_results():
    interim = os.path.join(DEMO, "work", "interim")
    canon = json.load(open(os.path.join(interim, "canonical_ugc.json"), encoding="utf-8"))
    full = os.path.join(DEMO, "work", "full")
    os.makedirs(full, exist_ok=True)
    out = os.path.join(full, "full_results.jsonl")
    keep_rv = {"is_ad": False, "reason_code": "", "promotion_evidence": [],
               "promotion_evidence_present": False, "record_is_travel_experience": True,
               "landscape_content_present": True, "landscape_evidence": ["demo"],
               "t001": False, "t001_evidence": "", "r001": False, "r001_evidence": "",
               "r003": False, "r003_evidence": "", "confidence": "high", "notes": "demo keep"}
    with open(out, "w", encoding="utf-8") as f:
        for rec in canon:
            rid = rec["record_id"]
            if rid.endswith("_1002"):
                rv = dict(keep_rv, is_ad=True, reason_code="A001",
                          promotion_evidence=["正文末尾联系方式"], promotion_evidence_present=True,
                          record_is_travel_experience=False, notes="demo ad")
                status, primary, reasons = "exclude_ad", "A001", ["A001"]
            elif rid.endswith("_2002"):
                rv = dict(keep_rv, r001=True, r001_evidence="正文含异地城市名", notes="demo r001")
                status, primary, reasons = "exclude_unusable", "R001", ["R001"]
            else:
                rv = keep_rv
                status, primary, reasons = "keep", "", []
            f.write(json.dumps({
                "record_id": rid, "platform": rec["platform"],
                "verdicts": [], "record_verdict": rv,
                "usage": {}, "money": {"offpeak_cny": 0.0, "peak_cny": 0.0},
                "seconds": 0.0, "status": status, "primary": primary, "reasons": reasons,
                "scope_guard": False, "scope_evidence": "", "guard_overrode_model": False,
            }, ensure_ascii=False) + "\n")
    print("fabricated:", out)


def main():
    run(os.path.join("examples", "make_demo.py"))
    run("step1_inventory.py")
    run("step2_images.py")
    run("step3_records.py")
    fabricate_results()

    # 先用 --no-copy 空跑校验逻辑，再真实复制图片
    run("step6_outputs.py", "--no-copy")
    run("step6_outputs.py")
    run("step7_finalize.py")

    # Y 侧：先准备提示词占位文件，再跑交付流水线
    prompt_dir = os.path.join(DEMO, "delivery", "01_提示词")
    os.makedirs(prompt_dir, exist_ok=True)
    with open(os.path.join(prompt_dir, "prompt.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("请根据材料给出评价。这是 demo 占位提示词，不是完整评分规格。\n")
    run("y1_build_samples.py")
    run("y2_reencode_images.py")
    run("y3_build_requests.py")
    run("y4_scan_platform_traces.py")
    run("y5_selfcheck.py")
    run("y7_verify_copy.py")
    run("y8_sha256_copy.py")
    run("y9_cost_estimate.py")
    run("y6_zip.py")
    run("y10_split_zip.py")
    print("\n离线 demo 全部完成：", DEMO)


if __name__ == "__main__":
    main()