# -*- coding: utf-8 -*-
"""离线 demo 的配置。不要复制到项目根目录；通过 UGC_CONFIG 指向本文件运行。"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.join(HERE, "demo")

ROOT = DEMO
DATA = os.path.join(DEMO, "raw")
WORK = os.path.join(DEMO, "work")
OUTPUT_ROOT = DEMO
OUT_TMP = os.path.join(DEMO, "output_tmp")
OUT_FINAL = os.path.join(DEMO, "output")
CLEAN_DIR = OUT_FINAL
DELIVERY_ROOT = os.path.join(DEMO, "delivery")
DELIVERY_TOP_NAME = "demo_delivery"
DELIVERY_ZIP = os.path.join(DEMO, "demo_delivery.zip")
SPLIT_DIR = os.path.join(DEMO, "demo_delivery_parts")
PROMPT_FILE = os.path.join(DELIVERY_ROOT, "01_提示词", "prompt.txt")

PLATFORMS = ["pa", "pb"]
PREFIX = {"pa": "PA", "pb": "PB"}
IMAGE_DIRS = {
    "pa": ["images/platform_a"],
    "pb": ["images/platform_b"],
}
TABLES = [
    {
        "path": "platform_a/posts.csv",
        "platform": "pa",
        "kind": "csv",
        "columns": {"id": "note_id", "title": "title", "text": "desc", "keyword": "source_keyword"},
    },
    {
        "path": "platform_b/posts.csv",
        "platform": "pb",
        "kind": "csv",
        "columns": {"id": "commentId", "title": "", "text": "content", "keyword": "关键词"},
        "swap_check": {"a": "关键词", "b": "user_userNick"},
        "repost_regex": r"//\s*@",
    },
]

PROJECT_NAME = "Demo UGC"
DOMAIN_CONTEXT = "示例水岸"
LOCAL_TOKENS = ["示例水岸", "老石桥"]
SCOPE_GUARD_ENABLED = False
SCOPE_KEYWORD = ""
SAME_NAME_PLACE_HINT = ""

SAMPLE_TARGET = 6
SAMPLE_PER_CELL = 1
SAMPLE_SEED = 7
PROBES = []

LANDMARK_TOKENS = ["老石桥", "示例水岸"]
GENERIC_PLACE_TOKENS = ["示例水岸"]
SCORING_TERMS = ["情感极性", "视觉美学"]

ZIP_REQUIRED_ENTRIES = ["03_请求清单/requests.jsonl", "05_自检/自检报告.md"]
EXPECTED_SHA256 = ""