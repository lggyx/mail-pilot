"""AI 任务层：代写/改写/体检/退信归因/摘要/草拟回复。全部走 ai_adapter，JSON 约定输出。

「垃圾箱风险体检」= 本地确定性规则 + AI 分析两路合并：
本地规则（触发词/链接/纯文本比/图片占比/ALL CAPS）稳定可控，AI 负责整体语感与整改建议。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..services.ai_adapter import AIError, ChatMessage, chat, extract_json
from .renderer import html_to_text

SYSTEM = (
    "你是邮件送达率专家与文案助手。用户用自己的联系人列表发送合规邮件（有同意关系、"
    "有退订机制）。你的任务是帮助用户把合规邮件写得更容易送达、更容易被阅读。"
    "始终使用简体中文回复（除非用户要求其他语言），输出严格遵守要求的 JSON 格式。"
)

SPAM_TRIGGERS = [
    "免费", "中奖", "恭喜", "速抢", "限时", "最后一天", "点击领取", "立即赚钱",
    "零风险", "稳赚", "包治", "代开发票", "贷款", "返现", "抽奖", "免费领取",
    "free money", "win", "winner", "cash prize", "act now", "limited time",
    "risk free", "click here", "buy now", "viagra", "casino", "loan",
]

URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.I)
SHORTENER_HINTS = ("bit.ly", "t.cn", "url.cn", "dwz.cn", "tinyurl", "is.gd", "goo.gl")


@dataclass
class CheckupResult:
    score: int = 80            # 0-100，越高越好
    level: str = "low"         # low / medium / high
    issues: list[dict] = field(default_factory=list)      # {code, message, severity}
    suggestions: list[str] = field(default_factory=list)
    rule_hits: dict = field(default_factory=dict)          # 本地规则明细

    def as_dict(self) -> dict:
        return {
            "score": self.score, "level": self.level, "issues": self.issues,
            "suggestions": self.suggestions, "rule_hits": self.rule_hits,
        }


# --------------------------------------------------------- 本地规则 ----

def local_checkup(subject: str, html: str) -> CheckupResult:
    result = CheckupResult()
    text = html_to_text(html)
    text_len = len(text)
    issues, sugg = result.issues, result.suggestions

    # 1) 触发词
    lowered = (subject + " " + text).lower()
    hits = [w for w in SPAM_TRIGGERS if w.lower() in lowered]
    result.rule_hits["spam_triggers"] = hits
    if hits:
        sev = "high" if len(hits) >= 3 else "medium"
        result.score -= 8 * len(hits)
        issues.append({"code": "spam_trigger", "severity": sev,
                       "message": f"命中垃圾词触发词: {', '.join(hits[:8])}"})
        sugg.append("移除或改写营销味过重的词（免费/限时/立即赚钱等），用具体事实代替")

    # 2) 链接健康度
    urls = URL_RE.findall(html)
    result.rule_hits["links"] = urls[:20]
    if len(urls) > 10:
        result.score -= 10
        issues.append({"code": "too_many_links", "severity": "medium",
                       "message": f"链接过多（{len(urls)} 个）"})
        sugg.append("减少链接数量（建议 ≤ 5 个），只保留核心行动点")
    if any(any(h in u.lower() for h in SHORTENER_HINTS) for u in urls):
        result.score -= 10
        issues.append({"code": "shortener", "severity": "medium", "message": "使用了短链服务"})
        sugg.append("避免短链，使用自有域名完整链接")

    # 3) 图片占比 / 纯文本比
    img_count = len(re.findall(r"<img\b", html, re.I))
    result.rule_hits["image_count"] = img_count
    if text_len < 40 and img_count > 0:
        result.score -= 15
        issues.append({"code": "image_only", "severity": "high", "message": "正文几乎全是图片，缺少文本"})
        sugg.append("补充足够的文字说明；纯图片邮件是垃圾箱高风险信号")
    if text_len > 0:
        ratio = img_count / max(text_len / 500, 1)
        result.rule_hits["text_length"] = text_len
        if text_len < 120:
            result.score -= 8
            issues.append({"code": "thin_text", "severity": "low", "message": "文本内容偏少"})
            sugg.append("适当充实正文，说明这封邮件为什么值得读")

    # 4) 大写咆哮 / 感叹号
    exclam = (subject or "").count("！") + (subject or "").count("!")
    if exclam >= 2:
        result.score -= 6
        issues.append({"code": "shouting", "severity": "low", "message": "主题包含多个感叹号"})
        sugg.append("主题保持克制，一个感叹号都不用更好")
    if subject and subject.isupper() and len(subject) > 10:
        result.score -= 8
        issues.append({"code": "all_caps", "severity": "medium", "message": "主题全大写"})
        sugg.append("使用正常大小写")

    # 5) 退订信息
    if "退订" not in text and "unsubscribe" not in text.lower():
        result.score -= 12
        issues.append({"code": "no_unsubscribe", "severity": "medium", "message": "正文未包含退订说明"})
        sugg.append("在页脚加入退订方式（发送时会自动附加 List-Unsubscribe 头，但正文说明更友好）")

    result.score = max(5, min(98, result.score))
    result.level = "high" if result.score < 50 else ("medium" if result.score < 75 else "low")
    if not issues:
        sugg.append("内容结构良好，保持现状即可")
    return result


# --------------------------------------------------------- AI 任务 ----

def _get_cfg(cfg: dict) -> dict:
    if not cfg.get("model"):
        raise AIError("未配置模型", "bad_request")
    return cfg


def ai_generate(cfg: dict, *, intent: str, tone: str = "专业友好", mode: str = "rich") -> dict:
    """意图 → {subject, body}。mode=markdown 时正文用 Markdown，否则 HTML。"""
    _get_cfg(cfg)
    fmt = "Markdown 源码" if mode == "markdown" else "HTML（用 <p> <h3> <ul><li> <a> 等基础标签，不要整页 <html> 结构）"
    user = (
        f"写一封邮件。意图：{intent}\n语气：{tone}\n"
        f"正文格式：{fmt}\n"
        "可以用变量占位符如 {{name}}、{{company}}（会按收件人替换）。\n"
        '严格输出 JSON：{"subject": "...", "body": "..."}，不要输出其他内容。'
    )
    out = chat(cfg, [ChatMessage("system", SYSTEM), ChatMessage("user", user)], temperature=0.7)
    data = extract_json(out)
    return {"subject": str(data.get("subject", "")), "body": str(data.get("body", ""))}


def ai_rewrite(cfg: dict, *, subject: str, body: str, instruction: str, mode: str = "rich") -> dict:
    _get_cfg(cfg)
    fmt = "保持 Markdown" if mode == "markdown" else "保持 HTML 标签结构（基础标签）"
    user = (
        f"改写下面这封邮件。改写要求：{instruction or '提升可读性与送达率'}\n"
        f"主题：{subject}\n正文：\n{body}\n"
        f"正文格式：{fmt}。\n"
        '严格输出 JSON：{"subject": "...", "body": "..."}，不要输出其他内容。'
    )
    out = chat(cfg, [ChatMessage("system", SYSTEM), ChatMessage("user", user)], temperature=0.6)
    data = extract_json(out)
    return {"subject": str(data.get("subject", subject)), "body": str(data.get("body", body))}


def ai_checkup(cfg: dict, *, subject: str, html: str, local: CheckupResult) -> dict:
    """AI 复核本地体检结果，输出 {score, level, issues, suggestions}。失败则降级返回本地结果。"""
    text = html_to_text(html)[:4000]
    try:
        _get_cfg(cfg)
        user = (
            "分析这封邮件的垃圾箱风险并给出整改建议。邮件主题与正文如下。\n"
            f"主题：{subject}\n正文（纯文本节选）：\n{text}\n\n"
            f"本地规则初判：{local.as_dict()}\n"
            "综合判断：score 为 0-100（越高越安全），level ∈ low/medium/high，"
            "issues 为 [{code, message, severity}]，suggestions 为字符串数组（按优先级）。"
            '严格输出 JSON：{"score": 0, "level": "low", "issues": [], "suggestions": []}'
        )
        out = chat(cfg, [ChatMessage("system", SYSTEM), ChatMessage("user", user)], temperature=0.3)
        data = extract_json(out)
        data.setdefault("rule_hits", local.rule_hits)
        data["ai_available"] = True
        return data
    except AIError as e:
        merged = local.as_dict()
        merged["ai_error"] = f"{e.kind}: {e}"
        merged["ai_available"] = False
        return merged


def ai_analyze_bounces(cfg: dict, *, subject: str, html: str,
                       bounced: list[dict], complained: list[dict]) -> dict:
    """发送后归因：输入退信/投诉名单与内容，输出分析与整改版。

    返回 {analysis, causes: [], revised_subject, revised_body, excluded_note}
    """
    _get_cfg(cfg)
    sample = bounced[:20] + complained[:10]
    lines = [f"- {r.get('email')}（{r.get('kind')}）: {str(r.get('error'))[:160]}" for r in sample]
    user = (
        f"一批邮件发出后出现退信/被标垃圾。邮件主题：{subject}\n"
        f"正文（纯文本节选）：\n{html_to_text(html)[:3000]}\n"
        f"问题事件（kind=bounced 拒收 / complained 标垃圾）：\n" + "\n".join(lines or ["（无明细）"]) + "\n\n"
        "请分析原因（区分邮箱不存在/域名拒收/内容触发/频率问题），并生成整改版邮件。"
        "整改版应排除已退订与已退信地址的受众视角来写（他们不会收到，供重发活动使用）。"
        '严格输出 JSON：{"analysis": "...", "causes": ["..."], '
        '"revised_subject": "...", "revised_body": "..."}（正文用 HTML 基础标签）。'
    )
    out = chat(cfg, [ChatMessage("system", SYSTEM), ChatMessage("user", user)], temperature=0.4)
    data = extract_json(out)
    return {
        "analysis": str(data.get("analysis", "")),
        "causes": [str(c) for c in (data.get("causes") or [])],
        "revised_subject": str(data.get("revised_subject", "")),
        "revised_body": str(data.get("revised_body", "")),
    }


def ai_summarize(cfg: dict, *, messages: list[dict]) -> str:
    _get_cfg(cfg)
    lines = [f"[{m.get('direction')}] {m.get('from_email')}: {str(m.get('text'))[:500]}" for m in messages]
    user = "总结以下往来邮件（要点 + 待办事项，300 字内）：\n" + "\n".join(lines)
    return chat(cfg, [ChatMessage("system", SYSTEM), ChatMessage("user", user)], temperature=0.3)


def ai_draft_reply(cfg: dict, *, messages: list[dict], instruction: str = "") -> dict:
    _get_cfg(cfg)
    lines = [f"[{m.get('direction')}] {m.get('from_email')}: {str(m.get('text'))[:600]}" for m in messages]
    user = (
        "根据以下往来邮件草拟一封回复。要求：" + (instruction or "礼貌、简洁、切中要点") + "\n"
        + "\n".join(lines)
        + '\n严格输出 JSON：{"subject": "...", "body": "..."}（正文为 HTML 基础标签）。'
    )
    out = chat(cfg, [ChatMessage("system", SYSTEM), ChatMessage("user", user)], temperature=0.6)
    data = extract_json(out)
    return {"subject": str(data.get("subject", "")), "body": str(data.get("body", ""))}
