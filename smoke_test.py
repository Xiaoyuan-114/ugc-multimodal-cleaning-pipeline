# -*- coding: utf-8 -*-
"""冒烟测试：确认模型名、图片输入、thinking 开关是否可用。

优先从 config_local.IMAGE_DIRS 里找一张 20KB–120KB 的 JPG 做视觉测试；
找不到图片时只跑文本测试。
"""
import os, sys, base64, json, time
import requests
import config as C

KEY = C.API_KEY
if not KEY:
    print("未配置 API key：请设置环境变量 UGC_API_KEY 或 DS_API_KEY")
    sys.exit(2)

cands = []
for dirs in C.IMAGE_DIRS.values():
    for d in dirs:
        for dp, dn, fn in os.walk(os.path.join(C.DATA, d)):
            for f in fn:
                if f.lower().endswith((".jpg", ".jpeg")):
                    p = os.path.join(dp, f)
                    s = os.path.getsize(p)
                    if 20000 < s < 120000:
                        cands.append((s, p))
        if len(cands) > 5:
            break
    if len(cands) > 5:
        break
cands.sort()
img_path = cands[0][1] if cands else None
if img_path:
    print("测试图:", img_path, os.path.getsize(img_path), "bytes")
else:
    print("[warn] 没找到 20KB–120KB 的 JPG，跳过视觉测试")

b64 = ""
if img_path:
    with open(img_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

BASE = C.API_BASE
HDR = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}


def call(payload, tag):
    t0 = time.time()
    try:
        r = requests.post(BASE, headers=HDR, json=payload, timeout=C.API_TIMEOUT)
    except Exception as e:
        print(f"[{tag}] 请求异常: {e}")
        return None
    dt = time.time() - t0
    print(f"[{tag}] HTTP {r.status_code}  {dt:.1f}s")
    if r.status_code != 200:
        print("   body:", r.text[:500])
        return None
    d = r.json()
    print("   usage:", json.dumps(d.get("usage", {}), ensure_ascii=False))
    msg = d["choices"][0]["message"]
    print("   content:", (msg.get("content") or "")[:300].replace("\n", " "))
    if msg.get("reasoning_content"):
        print("   reasoning 长度:", len(msg["reasoning_content"]))
    return d


def user_msg(text, with_img=True):
    c = [{"type": "text", "text": text}]
    if with_img and b64:
        c.append({"type": "image_url",
                  "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"}})
    return [{"role": "user", "content": c}]


PROMPT = ('判断这张图是否属于"纯商业推广广告"（二维码/联系方式/价格促销/招募海报等，'
          '且不含真实游览或景观内容）。只输出JSON：{"is_ad": true/false, "evidence": "证据类型与位置"}')

print("\n--- 1) 纯文本，测试模型名与 thinking 开关 ---")
call({"model": C.MODEL,
      "messages": [{"role": "user", "content": "回答两个字：可用"}],
      "max_tokens": 64,
      "thinking": {"type": "disabled"}}, "text/thinking=disabled")

if b64:
    print("\n--- 2) 图片输入 + detail=low ---")
    call({"model": C.MODEL,
          "messages": user_msg(PROMPT),
          "max_tokens": 200,
          "thinking": {"type": "disabled"}}, "vision/detail=low")

    print("\n--- 3) 图片输入 + detail=high ---")
    call({"model": C.MODEL,
          "messages": user_msg(PROMPT),
          "max_tokens": 200,
          "thinking": {"type": "disabled"}}, "vision/detail=high")