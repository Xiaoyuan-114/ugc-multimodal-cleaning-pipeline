# -*- coding: utf-8 -*-
"""Step 7：把通过校验的临时目录改名为正式输出目录；若正式目录已存在且非空，先整体改名为备份。

安全前提：
  1) 临时目录存在，且含全部 10 个必需文件；
  2) 运行信息.json 中全部校验项 pass=true；
  3) 临时目录不在原始数据集内（绝不碰 ugc数据集_副本）。
"""
import os, sys, json, datetime, shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C

REQUIRED = ["可用UGC.csv", "可用UGC.jsonl", "清洗明细.csv", "排除记录.csv", "重复映射.csv",
            "清洗汇总.csv", "原始记录映射.csv", "图片明细.csv", "输入文件清单.csv", "运行信息.json"]


def main():
    tmp = C.OUT_TMP
    fin = C.OUT_FINAL
    print(f"临时目录: {tmp}")
    print(f"正式目录: {fin}")

    if not os.path.isdir(tmp):
        print("✗ 临时目录不存在，终止。"); return 1
    missing = [f for f in REQUIRED if not os.path.exists(os.path.join(tmp, f))]
    if missing:
        print("✗ 临时目录缺少必需文件，终止：", missing); return 1
    if not os.path.isdir(os.path.join(tmp, "images")):
        print("✗ 临时目录缺少 images/ 目录，终止。"); return 1

    info = json.load(open(os.path.join(tmp, "运行信息.json"), encoding="utf-8"))
    checks = info.get("校验") or []
    failed = [c for c in checks if not c.get("pass")]
    if failed or not checks:
        print(f"✗ 校验未全部通过（失败 {len(failed)} 项 / 共 {len(checks)} 项），终止。")
        for c in failed:
            print(f"   FAIL {c['no']}. {c['check']} — {c['detail']}")
        return 1
    print(f"✓ 校验全部通过（{len(checks)} 项）")

    # 安全检查：临时目录不得位于原始数据集内
    ds = os.path.abspath(C.DATA)
    if os.path.abspath(tmp).startswith(ds):
        print("✗ 临时目录位于原始数据集内，终止。"); return 1

    if os.path.isdir(fin):
        rest = [x for x in os.listdir(fin) if x not in (".", "..")]
        if rest:
            bak = f"{fin}_backup_{C.RUN_ID}"
            if os.path.isdir(bak):
                print(f"✗ 备份目录已存在：{bak}，请先处理。"); return 1
            print(f"→ 正式目录非空（{len(rest)} 项），整体改名为 {os.path.basename(bak)}")
            shutil.move(fin, bak)
        else:
            print("→ 正式目录为空，直接删除后改名")
            os.rmdir(fin)

    shutil.move(tmp, fin)
    print(f"\n✓ 完成：{tmp}\n     → {fin}")

    # 回写实际输出路径
    p = os.path.join(fin, "运行信息.json")
    d = json.load(open(p, encoding="utf-8"))
    d["最终输出路径"] = fin
    d["改名完成时间"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("已回写 运行信息.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
