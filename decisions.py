# -*- coding: utf-8 -*-
"""业务决策顺序：广告 → 完全重复 → 不可用。此处只实现前两步的判定落定（广告、不可用）。"""
import config as C


def scope_guard(rec, rv=None):
    """通用范围守卫：只保留“本地内容”，过滤同名通用词召回的异地内容。

    触发条件（须同时满足）：
      a) 该记录的全部来源关键词都含 SCOPE_KEYWORD（即只被这个通用词召回）；
      b) 标题/正文/转发/关键词中找不到任何 LOCAL_TOKENS。
    判定只用记录自身的可核查文本，不采信模型的说明文字（模型结论里常出现
    「非本地」「不含本地内容」这类反向表述，若纳入扫描会把否定句误当成肯定证据）。
    返回 (True, 证据串) 或 (False, "")。
    """
    if not C.SCOPE_GUARD_ENABLED or not C.SCOPE_KEYWORD or not C.LOCAL_TOKENS:
        return False, ""
    ks = [k for k in dict.fromkeys(rec.get("source_keywords") or []) if k]
    if not ks:
        return False, ""
    if any(C.SCOPE_KEYWORD not in k for k in ks):
        return False, ""          # 还挂着其他关键词 → 不适用本守卫
    blob = " ".join([
        rec.get("title_raw") or "",
        rec.get("text_raw") or "",
        rec.get("repost_text_raw") or "",
        " ".join(ks),
    ])
    for t in C.LOCAL_TOKENS:
        if t in blob:
            return False, ""
    return True, (f"来源关键词仅含通用词『{C.SCOPE_KEYWORD}』，"
                  "正文与关键词中均无任何本地相关内容")


def usable_image_count(verdicts):
    n = 0
    for v in verdicts:
        if v.get("__undecodable__"):
            continue
        if (v.get("unusable_type") or ""):
            continue
        n += 1
    return n


def decide_record(rec, rv, verdicts, has_any_image):
    """返回 (cleaning_status, primary_reason_code, reason_list, is_ad_evidence)"""
    reasons = []
    if rv.get("is_ad"):
        code = rv.get("reason_code") or "A001"
        return "exclude_ad", code, [code], rv.get("promotion_evidence", [])
    hit, _ev = scope_guard(rec, rv)
    if hit:
        return "exclude_unusable", "R001", ["R001"], []
    if rv.get("r001"):
        reasons.append("R001")
    if rv.get("r003"):
        reasons.append("R003")
    if rv.get("t001") and usable_image_count(verdicts) == 0:
        reasons.append("T001")
    if reasons:
        return "exclude_unusable", reasons[0], reasons, []
    # 保留：未排除但存在推广迹象的记 flag
    return "keep", "", [], rv.get("promotion_evidence", []) if rv.get("promotion_evidence_present") else []


def decide_image(v):
    """单张图片的处置。返回 (cleaning_status, primary_reason_code, reasons)"""
    if v.get("__undecodable__"):
        return "exclude_unusable", "F001", ["F001"]
    if v.get("is_ad"):
        return "exclude_ad", v.get("reason_code") or "A001", [v.get("reason_code") or "A001"]
    ut = v.get("unusable_type") or ""
    if ut:
        return "exclude_unusable", ut, [ut]
    return "keep", "", []
