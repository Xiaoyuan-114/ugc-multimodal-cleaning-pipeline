# UGC Multimodal Cleaning Pipeline

A configurable, auditable pipeline for cleaning large user-generated-content (UGC) datasets with a multimodal LLM, plus a second stage that turns the cleaned dataset into LLM-ready stimuli and a delivery package.

**This repository contains code and methodology only. No scraped data, images, prompts, API keys, or project-specific results are included.**

> 中文说明为主，English summary at the bottom. 本仓库是从一个真实研究项目中抽出的通用化版本：所有项目名、地点词、平台名、表名和数量都已移除或改为配置项。

---

## 它做什么

```
原始数据（表格 + 图片文件夹）
        │
        ├─ step1  输入盘点        扫描表/工作表/图片 → 文件清单 + 运行前 manifest
        ├─ step2  图片指纹        SHA-256 / 解码状态 / 全黑全白 / 灰度标准差（可续跑）
        ├─ step3  记录归并        按平台主键合并 → 规范 UGC + 原始行映射
        ├─ step4  校准批          分层抽样 + 定向探针，人工验收判定口径（闸门）
        ├─ step5  全量判定        广告 / 不可用 / 地点无关 / 正文无效（可续跑）
        ├─ step6  出表归档        去重 + 复制图片 + 10 个审计文件 + 守恒校验
        └─ step7  终局改名        18 项校验全部通过才把临时目录改名为正式目录
                │
                ▼
        清洗后数据（主表 + images/）
                │
                ├─ y1  样本清单 + 文本材料
                ├─ y2  图片重编码（长边/质量/剥离 EXIF）
                ├─ y3  requests.jsonl（每行一个样本的材料清单）
                ├─ y4  平台痕迹与泄漏扫描（只扫描、不删改）
                ├─ y5  自检 + 材料台账 + 自检报告
                ├─ y6  打 zip（图片 STORED、文本 DEFLATED）
                ├─ y7  逐文件 size 比对 + 补齐
                ├─ y8  全量 SHA-256 复核
                ├─ y9  token / 成本估算
                └─ y10 分卷 + 拼接哈希
```

核心思想：**把不确定性交给模型，把可判定的边界交给确定性规则，并用守恒校验保证不丢不重。**

## 不是什么

- 不是爬虫：输入数据需要你自己准备。
- 不是评分/建模工具：本流水线只做清洗分类；评分维度与建模不在范围内。
- 不是开箱即用的产品：`config_local.py` 必须按你的数据布局修改，`step3` 的表结构是配置驱动的。
- 没有在你的数据上验证过：仓库只附带合成 demo 的离线验证结果（见下）。

## 目录

```
.
├── config.py                 # 配置加载器：环境变量 > config_local.py > 默认值
├── config.example.py         # 复制为 config_local.py 后修改
├── decisions.py              # 业务决策顺序 + 范围守卫
├── adjudicate.py             # 两级判定（图片级 / 记录级）模型调用
├── smoke_test.py             # 模型端点冒烟测试（文本 + 图片 + thinking 开关）
├── scan_textonly_visual.py   # 纯文本样本的视觉信息含量量化
├── step1_inventory.py ... step7_finalize.py
├── y1_build_samples.py ... y10_split_zip.py
├── docs/
│   ├── cleaning-pipeline.md
│   └── stimuli-packaging.md
└── examples/
    ├── make_demo.py          # 生成合成小数据集（不联网）
    ├── demo_config.py
    └── run_offline_demo.py   # 离线跑通 step1–3 / step6–7 / y1–y10
```

## 快速开始

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cp config.example.py config_local.py
# 编辑 config_local.py：ROOT / DATA / IMAGE_DIRS / TABLES / LOCAL_TOKENS ...
```

配置密钥（二选一）：

```bash
export UGC_API_KEY=...        # Windows PowerShell: $env:UGC_API_KEY="..."
# 或旧变量名：DS_API_KEY
```

冒烟测试：

```bash
python smoke_test.py
```

按顺序运行：

```bash
python step1_inventory.py
python step2_images.py
python step3_records.py
python step4_calibrate.py     # 校准批，人工验收
python step5_full.py          # 全量判定；支持 --limit / --workers
python step6_outputs.py --no-copy   # 先空跑校验逻辑
python step6_outputs.py             # 再真实复制图片
python step7_finalize.py

python y1_build_samples.py
python y2_reencode_images.py
python y3_build_requests.py
python y4_scan_platform_traces.py
python y5_selfcheck.py
python y7_verify_copy.py
python y8_sha256_copy.py
python y9_cost_estimate.py
python y6_zip.py
python y10_split_zip.py <expected_sha256>   # 可选
```

`step4` / `step5` 会调用模型，产生费用。`step1–3`、`step6–7`、`y1–y10` 不调用模型。

## 输入契约

默认布局（全部可在 `config_local.py` 里改）：

```
ROOT/
├── raw_dataset/                       # 原始数据，只读
│   ├── platform_a/posts.csv
│   ├── platform_b/posts.csv
│   └── images/
│       ├── platform_a/<source_id>/*.jpg
│       └── platform_b/<source_id>/*.jpg
├── clean_output/                      # step6/7 生成
└── delivery/                          # y1–y10 生成
```

`TABLES` 是核心配置。一个表一条：

```python
TABLES = [
    {
        "path": "platform_a/posts.csv",
        "platform": "pa",
        "kind": "csv",
        "columns": {
            "id": "note_id",          # 主键列
            "title": "title",         # 没有标题就写 ""
            "text": "desc",           # 正文列
            "keyword": "source_keyword",
        },
        # 可选：正文里转发内容的分隔正则
        # "repost_regex": r"//\s*@",
        # 可选：两列表头可能写反时，按“哪列取值种类更多”自动对调
        # "swap_check": {"a": "关键词", "b": "user_userNick"},
    },
]
```

`IMAGE_DIRS` 把平台短码映射到图片根目录。图片目录下按 `<source_id>/` 分子文件夹；源 ID 与图片文件夹同名是硬约定。

## 输出

清洗阶段（`clean_output/`）：

| 文件 | 内容 |
|---|---|
| `可用UGC.csv` / `.jsonl` | 最终可用记录（CSV 为 UTF-8 with BOM，JSONL 无 BOM） |
| `清洗明细.csv` | 全部规范记录，含保留与排除 |
| `排除记录.csv` | 整条 UGC 与单张图片的排除决定 + 证据 + `reason_scope` |
| `重复映射.csv` | SHA-256 完全重复关系 |
| `清洗汇总.csv` | 分平台统计 + 主原因数量与比例 |
| `原始记录映射.csv` | 每条原始表格行的动作（canonical / merged_reference） |
| `图片明细.csv` | 每张候选图片的状态与程序化检测值 |
| `输入文件清单.csv` | 全部扫描项 + 跳过原因 + 运行前后 size/mtime |
| `运行信息.json` | 模型/参数/阈值/口径/校验结果 |
| `images/<platform>/<source_id>/` | 字节原样复制的保留图片 |

原因码（默认语义，可在提示词里按你的规范调整）：

- `A001–A006`：广告（纯推广 / 优惠券 / 联系方式 / 招募 / 营销模板 / 主题无关）
- `R001`：内容属于其他地点；`R002` 系统界面/错误页；`R003` 纯新闻卡片；`R004` 聊天/订单截图；`R005` 地图/导航
- `T001`：正文无效；`F001`：文件无法解码或 0 字节；`D001`：SHA-256 完全重复

Y 侧交付（`delivery/`）：样本清单、材料台账、`stimuli/text/`、`stimuli/images/`、`requests.jsonl`、自检报告、zip。

## 安全铁律

1. **原始数据只读**：不修改、不移动、不重命名、不删除；复制图片必须字节原样，复制后验 SHA-256。
2. **保守优先**：判断不明确一律 `keep`，只设 flag；排除只用于高置信度情形。
3. **每条排除决定都要有唯一主原因 + 可核查证据**（证据类型和位置，不能只写“模型认为是广告”）。
4. **校验不过不改名，不声称完成**：`step7` 只在 `运行信息.json` 的全部校验项 pass 后才改目录名。
5. **平台信息隔离**：`requests.jsonl` 结构上不包含 `platform` / `source_keywords`，避免误喂给模型。
6. **不提交 `config_local.py` 和任何数据/输出**：`.gitignore` 已覆盖。

## 离线 demo

不需要 API key，也不需要真实数据：

```bash
python examples/run_offline_demo.py
```

它会生成一个包含两个平台、6 条记录、7 张图片（含重复图、0 字节图、低分辨率图）的合成数据集，跑完：

- `step1–3`：盘点、指纹、归并
- 伪判定结果（1 条广告、1 条地点无关、其余保留）
- `step6 --no-copy` 和 `step6`：18 项守恒校验全部通过
- `step7`：改名
- `y1–y10`：样本、重编码、请求清单、痕迹扫描、自检（14/14）、复制校验、SHA-256、成本估算、打包、分卷

**未覆盖**：`step4` / `step5` 的真实模型调用。它们需要你自己的 API key，仓库的离线 demo 不会触发。

## 验证状态

- `python -m py_compile *.py examples/*.py` 通过。
- 合成数据离线 demo 全链路通过；`step6` 18/18、`y5` 14/14。
- 未在真实数据集上复跑（原项目数据未随仓库发布），也未在本仓库中执行过任何模型调用。接入真实数据前，请先用 `step4` 校准批验收口径。

## 成本与性能（设计参考，不是承诺）

- 图片按尺寸归一化计费时，**每张图的 input token 通常有上限**；具体取决于你的服务商。
- 大多数视觉模型默认开启 thinking/reasoning，**若按输出计费会显著抬高成本**，批量任务应显式关闭或降到最低档（以服务商文档为准）。
- 提示词前缀复用会带来缓存命中；同一批提示词重跑会明显便宜。
- 大批量任务排在低峰/夜间/周末执行；峰谷价差可能达到 2 倍。
- 先跑校准批，用实测 token 外推全量，比拍脑袋估算可靠。

## 跨平台

- 内部相对路径统一使用 `/`；设计上兼容 Windows 与 macOS/Linux，但**本仓库只在 Windows 上实跑过**。
- CSV 输出为 UTF-8 with BOM；JSONL/TXT 为 UTF-8 无 BOM、LF。
- macOS 文件系统可能把中文名存成 NFD；跨平台比对文件名前请 `unicodedata.normalize("NFC", name)`。
- 清单里的相对路径一律写 POSIX `/`，接收方用 `os.path.join(ROOT, rel)` 解析。
- 大目录跨位置复制可能被沙箱/权限间断性拦截：不要裸 `copytree` 一把梭，用 `y7` 的“size 比对 + 补齐”与 `y8` 的全量 SHA-256 收口。

## License

MIT. See [LICENSE](LICENSE).

---

## English summary

A configurable, auditable reference implementation for cleaning large UGC datasets with a multimodal LLM: inventory, image fingerprinting, canonical record merging, calibration batch, full two-level adjudication (ad / unusable / off-topic), exact deduplication, image archiving, audit tables and conservation checks. A second stage packages the cleaned data into LLM-ready stimuli, request manifests and a verified delivery zip.

No data, images, prompts, API keys or project-specific results are included. Copy `config.example.py` to `config_local.py`, describe your table/image layout, and run the numbered steps. The offline synthetic demo validates everything except the real model calls; `step4`/`step5` require your own API key. Tested on Windows; internal paths are POSIX-normalized for macOS/Linux compatibility.