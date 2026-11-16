# -*- coding: utf-8 -*-
"""纯文本样本的视觉信息含量量化（三个样例列表分离）"""
import os, csv, json, collections, statistics
import config as C

OUT = C.CLEAN_DIR

FEAT = ["风景","景色","景观","景致","绿树","树荫","绿荫","绿化","倒影","水面","水景","河道","河水","河岸",
        "粉墙","黛瓦","白墙","黑瓦","青石","石板","石桥","小桥","流水","古建筑","老房子","民居","建筑",
        "亭","廊","桥","灯笼","光影","阳光","色彩","灯火","夜景","荷花","园林","庭院","假山","古色古香",
        "古香古色","水墨","飞檐","雕","门楼","牌坊","巷","屋檐","瓦","墙"]

EVAL = ["美","漂亮","好看","出片","养眼","惊艳","震撼","壮观","秀丽","秀美","精致","典雅","有味道",
        "有意境","意境","丑","难看","破败","杂乱","脏","萧瑟","萧条"]

EMO = ["好玩","不错","喜欢","失望","后悔","开心","满意","差","坑","值","推荐","再来","不会","无聊","没意思","一般"]
SPA = ["人多","拥挤","排队","走","累","热","晒","吵","安静","清净","方便","停车","门票","贵","交通","住宿","吃"]
CUL = ["历史","文化","传统","故居","故居","老字号","底蕴","故事","人文","原住民","生活气息","商业化","同质化"]

def cls(t):
    f = [w for w in FEAT if w in t]
    e = [w for w in EVAL if w in t]
    if f: return "A", f
    if e: return "B", e
    return "C", []

rows = []
with open(os.path.join(OUT, "可用UGC.csv"), "r", encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

txt_only = [r for r in rows if json.loads(r.get("image_files") or "[]") == []]
n = len(txt_only)
if not rows:
    raise SystemExit("可用UGC.csv 为空")
if n == 0:
    raise SystemExit("没有纯文本样本，跳过本分析")

buckets = {"A": [], "B": [], "C": []}
for r in txt_only:
    t = (r.get("title_raw") or "") + (r.get("text_clean") or "")
    k, hits = cls(t)
    buckets[k].append((r, t, hits))

print(f"可用 UGC {len(rows)} | 纯文本 {n} ({n/len(rows)*100:.1f}%) | 有图 {len(rows)-n}")
print("纯文本平台:", dict(collections.Counter(r['platform'] for r in txt_only)))
for k in "ABC":
    L = [len(t) for _, t, _ in buckets[k]]
    print(f"  {k} 类 {len(buckets[k]):5d} ({len(buckets[k])/n*100:5.1f}%)   正文长度 中位 {statistics.median(L) if L else 0:6.1f}  <10字 {sum(1 for x in L if x<10)}")

print("\n【A 类样例（文字里点了具体物象）】")
for r, t, h in buckets["A"][:6]:
    print(f"   {r['record_id']:22s} {t[:56]!r}  → {h[:5]}")

print("\n【B 类样例（只下美学判断，没说是什么）】")
for r, t, h in buckets["B"][:8]:
    print(f"   {r['record_id']:22s} {t[:56]!r}  → {h[:5]}")

print("\n【C 类样例（连美学判断都没有）】")
for r, t, h in buckets["C"][:10]:
    print(f"   {r['record_id']:22s} {t[:56]!r}")

# C 类里还有多少能在其他三维留下信号
c_all = buckets["C"]
def has(t, lex): return any(w in t for w in lex)
c_emo = sum(1 for _, t, _ in c_all if has(t, EMO))
c_spa = sum(1 for _, t, _ in c_all if has(t, SPA))
c_cul = sum(1 for _, t, _ in c_all if has(t, CUL))
c_any = sum(1 for _, t, _ in c_all if has(t, EMO) or has(t, SPA) or has(t, CUL))
m = len(c_all)
print(f"\nC 类（{m} 条）里：")
print(f"   含情感线索 {c_emo} ({c_emo/m*100:.1f}%) | 含空间线索 {c_spa} ({c_spa/m*100:.1f}%) | 含文化线索 {c_cul} ({c_cul/m*100:.1f}%)")
print(f"   至少一维有线索 {c_any} ({c_any/m*100:.1f}%)   三维全无线索 {m-c_any} ({(m-c_any)/m*100:.1f}%)")

# 有图对照组
wt = [r for r in rows if json.loads(r.get("image_files") or "[]") != []]
if wt:
    cw = sum(1 for r in wt if cls((r.get("title_raw") or "")+(r.get("text_clean") or ""))[0] == "C")
    print(f"\n对照：有图 {len(wt)} 条里，正文也属 C 类 {cw} ({cw/len(wt)*100:.1f}%) —— 它们的视觉证据来自图片本身")
else:
    print("\n对照：没有有图样本")
