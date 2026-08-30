"""模板渲染测试：变量提取/替换/默认值、Markdown→HTML、纯文本降级。"""

from __future__ import annotations

from app.services.renderer import (
    extract_variables,
    html_to_text,
    make_text_version,
    markdown_to_html,
    render_body,
    substitute_variables,
)


def test_extract_variables_ordered_unique():
    body = "你好 {{name}}，{{ name }} 与 {{name}}、{{order_id}}"
    assert extract_variables(body) == ["name", "order_id"]


def test_substitute_escapes_html():
    out = substitute_variables("hi {{name}}", {"name": "<b>evil</b>"})
    assert "<b>" not in out and "&lt;b&gt;" in out


def test_substitute_default_value():
    out = substitute_variables("亲爱的 {{name|朋友}}，{{missing|N/A}}", {})
    assert "亲爱的 朋友，N/A" in out


def test_render_markdown_mode():
    html = render_body("# 标题\n\n你好 {{name}}", "markdown", {"name": "小明"})
    assert "<h1>" in html and "小明" in html


def test_render_html_mode_passthrough():
    html = render_body("<p>{{name}}</p>", "rich", {"name": "A"})
    assert html == "<p>A</p>"


def test_markdown_to_html_table():
    md = "| a | b |\n|---|---|\n| 1 | 2 |"
    html = markdown_to_html(md)
    assert "<table>" in html


def test_html_to_text():
    text = html_to_text("<p>第一行</p><br><style>.x{}</style><p>第二行</p>")
    assert "第一行" in text and ".x{}" not in text
    lines = [l for l in text.splitlines() if l.strip()]
    assert lines[0] == "第一行"


def test_make_text_version_strips_tags():
    text = make_text_version("<h3>Hi</h3><p>内容 <a href='#'>链接</a></p>")
    assert "Hi" in text and "<" not in text
