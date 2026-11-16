# -*- coding: utf-8 -*-
"""Configuration loader.

优先级：环境变量 > config_local.py > 本文件默认值。

用法：
    cp config.example.py config_local.py
    # 编辑 config_local.py 里的 ROOT / TABLES / IMAGE_DIRS 等
    python step1_inventory.py

也可以不复制文件，直接设置 `UGC_CONFIG` 指向任意配置文件：
    UGC_CONFIG=/path/to/my_config.py python step1_inventory.py
"""
import os
import datetime
import importlib.util

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- 默认值
ROOT = ""
DATA = ""
WORK = os.path.join(BASE_DIR, ".work")
OUTPUT_ROOT = ""
OUT_TMP = ""
OUT_FINAL = ""

RUN_ID = os.environ.get("RUN_ID") or datetime.datetime.now().strftime("%Y%m%d_%H%M")
RULE_VERSION = "ugc-cleaning-pipeline v1.0"
CODE_VERSION = "pipeline v1.0"

PLATFORMS = []
PREFIX = {}
IMAGE_DIRS = {}
TABLES = []
REPOST_SPLIT = {}          # platform -> 转发分隔正则，例如 {"pb": r"//\s*@"}
SKIP_FILES = {}            # 相对 DATA 的路径（小写） -> 跳过原因
SKIP_TABLES = {}           # 表文件名（小写） -> 跳过原因

IMG_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")
SYSTEM_FILES = {".ds_store", "thumbs.db", "desktop.ini"}

# step1 表类型识别：命中评论表字段 -> 评论表；命中正文 id + 正文字段 -> 正文表
SHEET_COMMENT_COLS = ["comment_id", "parent_comment_id"]
SHEET_BODY_ID_COLS = ["note_id", "commentId", "id"]
SHEET_BODY_TEXT_COLS = ["desc", "content", "text", "正文"]

# ---------------------------------------------------------------- 模型
MODEL = "deepseek-flash"
API_BASE = "https://api.deepseek.com/chat/completions"
API_KEY = (os.environ.get("UGC_API_KEY") or os.environ.get("DS_API_KEY") or "").strip()
UPLOAD_LONG_SIDE = 1568
IMAGES_PER_CALL = 8
API_TIMEOUT = 180
MAX_RETRY = 3
# 清洗判定的价格（CNY / 1M tokens，高峰价；空闲价按 0.5 倍计算）
PRICE_INPUT_CNY = 2.0
PRICE_CACHE_CNY = 0.04
PRICE_OUTPUT_CNY = 8.0

# ---------------------------------------------------------------- 业务上下文（脱敏后为空/占位，按你的数据填写）
DOMAIN_CONTEXT = "目标研究区域"
LOCAL_TOKENS = []                 # 本地地名/景点名，用于 R001 判定与范围守卫
SCOPE_GUARD_ENABLED = False       # 是否启用“通用词只保留本地内容”的确定性守卫
SCOPE_KEYWORD = ""                # 触发守卫的通用关键词（须是来源关键词的子串）
SAME_NAME_PLACE_HINT = ""         # 写给模型的同名地点提示，例如“XX 是全国多地同名街道”

# 广告/服务招揽的文本正则。默认是通用的中文推广词，可按领域增删。
AD_KEYWORDS_REGEX = (
    r"(微信|weixin|wechat|vx|V\s*信|加我|私信|私聊|联系我|电话|手机号|QQ|二维码|扫码|扫我|长按识别|"
    r"优惠|折扣|团购|秒杀|特价|元起|预订|预定|招募|招聘|招商|加盟|代理|民宿|客栈|旅拍|写真|跟拍|"
    r"工作室|免费领|限时|福利|客服|下单|购买|链接|1[3-9]\d{9})"
)
SERVICE_KEYWORDS_REGEX = (
    r"(旅拍|跟拍|写真|妆造|汉服|约拍|跟妆|外景|民宿|客栈|预订|预定|预约|套餐|机位)"
)

# 校准批抽样
SAMPLE_TARGET = 120
SAMPLE_PER_CELL = 10
SAMPLE_SEED = 42
SAMPLE_CATEGORIES = ["疑似广告", "疑似不可用", "纯文本无图", "正常图文"]
# 定向探针：每项 {"name": 显示名, "match": lambda rec: bool, "count": 抽样条数}
# 例：{"name": "含服务词且有图", "match": lambda r: r.get("_imgs") and "民宿" in (r.get("text_raw") or ""), "count": 16}
PROBES = []

# ---------------------------------------------------------------- 阈值（清洗规范默认值）
BLACK_MAX = 5
BLACK_STD = 1.0
BLACK_RATIO = 0.999
WHITE_MIN = 250
WHITE_STD = 1.0
WHITE_RATIO = 0.999
LOW_RES_PIXELS = 300_000
STATS_PIXEL_CAP = 64_000_000

# ---------------------------------------------------------------- Y 侧：样本/交付
PROJECT_NAME = "UGC dataset"
TEXT_FIELDS = ["title_raw", "text_clean", "repost_text_raw"]
LANDMARK_TOKENS = []              # 便于分析的地标词表，仅写入样本清单，不喂模型
GENERIC_PLACE_TOKENS = []         # 其中的泛地名（只命中它不算具体地标）
PLATFORM_WORDS = ["微博", "小红书", "抖音", "快手", "B站", "知乎", "豆瓣", "大众点评",
                  "美团", "携程", "去哪儿", "马蜂窝", "飞猪", "途牛", "同程"]
SCORING_TERMS = []                # 你的评分维度词；用于扫描文本是否被误注入

CLEAN_DIR = ""                    # 清洗输出目录（默认 = OUT_FINAL）
DELIVERY_ROOT = ""
DELIVERY_TOP_NAME = "ugc_delivery"
DELIVERY_ZIP = ""
SPLIT_DIR = ""
EXPECTED_SHA256 = ""              # 可选：y10 分卷后校验拼接哈希
PROMPT_FILE = ""                  # 提示词文件；y9 成本估算用，不存在时自动跳过

# 交付目录结构（一般不需要改）
D_PROMPT = "01_提示词"
D_SAMPLES = "02_样本"
D_REQUESTS = "03_请求清单"
D_CLEAN_COPY = "04_清洗后数据"
D_QC = "05_自检"
D_SCRIPTS = "06_脚本"
D_STIM_TEXT = "stimuli/text"
D_STIM_IMAGES = "stimuli/images"
SAMPLE_MANIFEST_NAME = "样本清单.csv"
MATERIAL_LEDGER_NAME = "材料台账.csv"
REQUESTS_NAME = "requests.jsonl"
ZIP_REQUIRED_ENTRIES = []         # 例如 ["00_交接说明_HANDOFF.md", "03_请求清单/requests.jsonl"]

MAXSIDE = 1568
JPEG_QUALITY = 90
MAX_IMAGE_BYTES = 7 * 1024 * 1024

# y9 成本估算（USD / 1M tokens，按你的服务商改）
PRICE_INPUT_USD = 0.75
PRICE_OUTPUT_USD = 3.75
PRICE_DISCOUNT = 0.3              # 例如中转站 3 折；1.0 = 不打折
OUTPUT_TOKENS_LOW = 2.0e6
OUTPUT_TOKENS_MID = 3.0e6
OUTPUT_TOKENS_HIGH = 4.0e6

# ---------------------------------------------------------------- 加载本地配置
_LOCAL = os.environ.get("UGC_CONFIG") or os.path.join(BASE_DIR, "config_local.py")
if os.path.isfile(_LOCAL):
    _spec = importlib.util.spec_from_file_location("_ugc_local_config", _LOCAL)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    for _k, _v in vars(_mod).items():
        if not _k.startswith("_"):
            globals()[_k] = _v

# ---------------------------------------------------------------- 环境变量覆盖
ROOT = os.environ.get("UGC_ROOT", ROOT)
if os.environ.get("UGC_DATA_DIR"):
    DATA = os.environ["UGC_DATA_DIR"]
elif not DATA and ROOT:
    DATA = os.path.join(ROOT, "raw_dataset")

WORK = os.environ.get("UGC_WORK_DIR", WORK)
OUTPUT_ROOT = os.environ.get("UGC_OUTPUT_ROOT", OUTPUT_ROOT)
if os.environ.get("UGC_OUT_TMP"):
    OUT_TMP = os.environ["UGC_OUT_TMP"]
if os.environ.get("UGC_OUT_FINAL"):
    OUT_FINAL = os.environ["UGC_OUT_FINAL"]

if not OUT_TMP:
    OUT_TMP = os.path.join(OUTPUT_ROOT or ROOT, f"output_tmp_{RUN_ID}")
if not OUT_FINAL:
    OUT_FINAL = os.path.join(OUTPUT_ROOT or ROOT, "output")
if not CLEAN_DIR:
    CLEAN_DIR = os.environ.get("UGC_CLEAN_DIR", OUT_FINAL)
if not DELIVERY_ROOT:
    DELIVERY_ROOT = os.environ.get("UGC_DELIVERY_DIR", os.path.join(ROOT or OUTPUT_ROOT, DELIVERY_TOP_NAME))
if not DELIVERY_ZIP:
    DELIVERY_ZIP = os.path.join(ROOT or OUTPUT_ROOT, DELIVERY_TOP_NAME + ".zip")
if not SPLIT_DIR:
    SPLIT_DIR = os.path.join(ROOT or OUTPUT_ROOT, DELIVERY_TOP_NAME + "_parts")
if not PROMPT_FILE:
    PROMPT_FILE = os.path.join(DELIVERY_ROOT, D_PROMPT, "prompt.txt")

if not PLATFORMS:
    PLATFORMS = list(dict.fromkeys(
        [t["platform"] for t in TABLES] + list(IMAGE_DIRS.keys())
    ))
for _p in PLATFORMS:
    PREFIX.setdefault(_p, _p.upper())

INTERIM = os.path.join(WORK, "interim")
CALIBRATION = os.path.join(WORK, "calibration")
FULL = os.path.join(WORK, "full")
LOGS = os.path.join(WORK, "logs")
for _d in (WORK, INTERIM):
    try:
        os.makedirs(_d, exist_ok=True)
    except OSError as _e:
        print(f"[warn] 无法创建工作目录 {_d}: {_e}")

if not DATA:
    raise RuntimeError(
        "未配置数据目录。请复制 config.example.py 为 config_local.py 并设置 ROOT/DATA，"
        "或设置环境变量 UGC_ROOT / UGC_DATA_DIR。"
    )

if SCOPE_GUARD_ENABLED and (not SCOPE_KEYWORD or not LOCAL_TOKENS):
    print("[warn] SCOPE_GUARD_ENABLED=True 但 SCOPE_KEYWORD 或 LOCAL_TOKENS 为空，"
          "范围守卫将被跳过（避免误排除全部记录）。")
