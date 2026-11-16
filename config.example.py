# -*- coding: utf-8 -*-
"""复制本文件为 config_local.py，然后按你的数据集修改。

目录约定（可全部改，但 step 脚本依赖下面这些常量）：

    ROOT/
    ├── raw_dataset/                 # 原始数据（只读，脚本不会修改）
    │   ├── platform_a/posts.csv
    │   ├── platform_b/posts.csv
    │   └── images/platform_a/<source_id>/*.jpg
    ├── clean_output/                # 清洗输出（step6 生成）
    └── delivery/                    # Y 侧交付包（y1–y10 生成）

如果你的目录结构不同，只改 DATA / IMAGE_DIRS / TABLES 即可。
"""
import os

# ---------------------------------------------------------------- 路径
ROOT = r"./my_ugc_project"          # 改成你的数据根目录（绝对路径最稳妥）
DATA = os.path.join(ROOT, "raw_dataset")
WORK = os.path.join(ROOT, ".work")
OUT_FINAL = os.path.join(ROOT, "clean_output")
CLEAN_DIR = OUT_FINAL
DELIVERY_ROOT = os.path.join(ROOT, "delivery")

# ---------------------------------------------------------------- 平台
# platform 是内部短码，会出现在 record_id 前缀与输出目录里。
PLATFORMS = ["pa", "pb"]
PREFIX = {"pa": "PA", "pb": "PB"}

# 每个平台的图片根目录（相对 DATA）。脚本只扫描这些目录下的图片。
IMAGE_DIRS = {
    "pa": ["images/platform_a"],
    "pb": ["images/platform_b"],
}

# ---------------------------------------------------------------- 表结构
# 一个 TABLE 对应一个 CSV/XLSX。columns 里的键固定为 id/title/text/keyword，
# 值填你表里的实际列名；没有 title 就写 ""。
#   kind: "csv" 或 "xlsx"（按扩展名自动判断，可省略）
#   sheets: 仅 xlsx 可用，限定工作表名列表
#   repost_regex: 正文里转发内容的分隔正则，例如 r"//\s*@"；命中后前段为作者正文，后段为引用
#   swap_check: 可选。若两列表头可能写反，给 a/b 列名，脚本按“哪列取值种类更多”判断是否对调。
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

# 明确跳过的文件/表（SKIP_FILES 的键为相对路径小写，统一用 "/"；SKIP_TABLES 的键为文件名小写）。
SKIP_FILES = {
    # "images/platform_b/duplicate_archive.zip": "冗余压缩包副本，不提供新数据",
}
SKIP_TABLES = {
    # "comments.xlsx": "评论表，不是作者正文，不进入主 UGC 数据",
}

# ---------------------------------------------------------------- 模型
# 兼容 OpenAI chat/completions 协议的视觉模型端点均可。
MODEL = "deepseek-flash"
API_BASE = "https://api.deepseek.com/chat/completions"
# 密钥也可以直接用环境变量 UGC_API_KEY / DS_API_KEY，优先级更高。
API_KEY = ""

# ---------------------------------------------------------------- 业务上下文
# 这些词只用于“内容是否与目标地点无关”的判定与范围守卫，不喂给模型做评分。
DOMAIN_CONTEXT = "某历史街区"
LOCAL_TOKENS = ["示例地标A", "示例地标B", "示例古镇"]
SCOPE_GUARD_ENABLED = False
SCOPE_KEYWORD = ""
SAME_NAME_PLACE_HINT = ""

# 校准批定向探针（按需启用）
# PROBES = [
#     {"name": "含服务招揽词且有图",
#      "match": lambda r: r.get("_imgs") and bool(__import__("re").search(SERVICE_KEYWORDS_REGEX, (r.get("title_raw") or "") + (r.get("text_raw") or ""))),
#      "count": 16},
# ]

# ---------------------------------------------------------------- Y 侧
PROJECT_NAME = "示例 UGC 数据集"
# 只写入样本清单用于分析，不会进入模型材料。
LANDMARK_TOKENS = ["示例地标A", "示例地标B"]
GENERIC_PLACE_TOKENS = ["示例古镇"]
# 你的评分维度词；用于扫描文本是否误注入。没有就留空。
SCORING_TERMS = ["情感极性", "视觉美学", "空间舒适度", "文化认同"]
TEXT_FIELDS = ["title_raw", "text_clean", "repost_text_raw"]

# 交付目录/压缩包
DELIVERY_TOP_NAME = "ugc_delivery"
DELIVERY_ZIP = os.path.join(ROOT, DELIVERY_TOP_NAME + ".zip")
SPLIT_DIR = os.path.join(ROOT, DELIVERY_TOP_NAME + "_parts")
PROMPT_FILE = os.path.join(DELIVERY_ROOT, "01_提示词", "prompt.txt")
ZIP_REQUIRED_ENTRIES = [
    "03_请求清单/requests.jsonl",
    "05_自检/自检报告.md",
]

# 图片重编码
MAXSIDE = 1568
JPEG_QUALITY = 90
MAX_IMAGE_BYTES = 7 * 1024 * 1024

# 成本估算（USD / 1M tokens）
PRICE_INPUT_USD = 0.75
PRICE_OUTPUT_USD = 3.75
PRICE_DISCOUNT = 1.0
