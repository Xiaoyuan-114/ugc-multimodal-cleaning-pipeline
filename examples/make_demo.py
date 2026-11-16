# -*- coding: utf-8 -*-
"""生成一个完全合成的小数据集，用于离线验证流水线（不调用任何模型）。

    python examples/make_demo.py

生成目录：examples/demo/raw/
"""
import os, csv, shutil
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.join(HERE, "demo")
RAW = os.path.join(DEMO, "raw")


def jpg(path, color, size=(320, 240), quality=90):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG", quality=quality)


def main():
    if os.path.isdir(DEMO):
        shutil.rmtree(DEMO)
    os.makedirs(RAW, exist_ok=True)
    os.makedirs(os.path.join(RAW, "platform_a"), exist_ok=True)

    with open(os.path.join(RAW, "platform_a", "posts.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["note_id", "title", "desc", "source_keyword"])
        w.writerow(["1001", "A quiet riverside walk",
                    "老石桥、绿树和河面倒影。风景很好，适合慢慢走。", "demo_keyword"])
        w.writerow(["1002", "A post with a duplicate photo",
                    "Another post. 需要咨询请加微信 demo_contact。", "demo_keyword"])
        w.writerow(["1003", "", "短评：还不错。", "demo_keyword"])

    os.makedirs(os.path.join(RAW, "platform_b"), exist_ok=True)
    with open(os.path.join(RAW, "platform_b", "posts.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        # 注意：关键词列与 user_userNick 列的内容是反的，用于验证 swap_check
        w.writerow(["commentId", "content", "关键词", "user_userNick"])
        w.writerow(["2001", "This place is nice. //@someone: reposted text", "nick_alpha", "demo_keyword"])
        w.writerow(["2002", "The photo failed to load. 這是異地城市的內容。", "nick_beta", "demo_keyword"])
        w.writerow(["2003", "A normal comment without image.", "nick_gamma", "demo_keyword"])

    a1 = os.path.join(RAW, "images", "platform_a", "1001", "01.jpg")
    a2 = os.path.join(RAW, "images", "platform_a", "1001", "02.jpg")
    a3 = os.path.join(RAW, "images", "platform_a", "1001", "03.jpg")
    jpg(a1, (40, 120, 200))
    jpg(a2, (60, 180, 90))
    shutil.copyfile(a1, a3)          # 同一 UGC 内完全重复
    os.makedirs(os.path.join(RAW, "images", "platform_a", "1002"), exist_ok=True)
    shutil.copyfile(a1, os.path.join(RAW, "images", "platform_a", "1002", "01.jpg"))  # 跨 UGC 重复

    jpg(os.path.join(RAW, "images", "platform_b", "2001", "01.jpg"), (200, 120, 40))
    os.makedirs(os.path.join(RAW, "images", "platform_b", "2002"), exist_ok=True)
    open(os.path.join(RAW, "images", "platform_b", "2002", "01.jpg"), "wb").close()  # 0 字节
    jpg(os.path.join(RAW, "images", "platform_b", "2003", "01.jpg"), (90, 90, 90), size=(64, 64))  # 低分辨率

    print("demo dataset:", RAW)


if __name__ == "__main__":
    main()