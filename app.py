"""A dependency-free, editable content platform served with Python's WSGI server."""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

DEFAULT_CONTENT = {"site_title": "灵感工作台", "tagline": "把想法整理成清晰、可行动的内容。", "sections": [
    {"id": "welcome", "title": "欢迎来到你的平台", "body": "这里的每一个版块都可以修改。用它发布公告、记录项目进展，或展示你的服务。"},
    {"id": "focus", "title": "本周重点", "body": "选择一件最重要的事，把它写在这里，并持续更新进度。"},
    {"id": "contact", "title": "保持联系", "body": "在这里留下联系渠道、办公时间或下一次活动的信息。"},
]}


def escape(value: str) -> str:
    return html.escape(value, quote=True)


def layout(content: dict[str, Any], page: str, body: str) -> bytes:
    title = escape(content["site_title"])
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title><link rel="stylesheet" href="/static/style.css"></head><body><header class="topbar"><a class="brand" href="/">{title}</a><nav><a href="/">查看平台</a><a class="button small" href="/admin">编辑内容</a></nav></header><main class="{page}">{body}</main></body></html>'''.encode()


def create_app(content_path: str | Path | None = None):
    path = Path(content_path or os.environ.get("CONTENT_PATH", "data/content.json"))

    def save(content: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
            json.dump(content, tmp, ensure_ascii=False, indent=2)
            tmp.write("\n")
            name = tmp.name
        Path(name).replace(path)

    def load() -> dict[str, Any]:
        if not path.exists():
            content = json.loads(json.dumps(DEFAULT_CONTENT))
            save(content)
            return content
        return json.loads(path.read_text(encoding="utf-8"))

    def redirect(start_response, target: str):
        start_response("303 See Other", [("Location", target), ("Content-Length", "0")])
        return [b""]

    def application(environ, start_response):
        method, route = environ["REQUEST_METHOD"], environ["PATH_INFO"]
        if method == "GET" and route == "/static/style.css":
            css = (Path(__file__).parent / "static/style.css").read_bytes()
            start_response("200 OK", [("Content-Type", "text/css; charset=utf-8"), ("Content-Length", str(len(css)))])
            return [css]
        content = load()
        if method == "GET" and route == "/":
            cards = "".join(f'<article class="card"><span>{index:02}</span><h2>{escape(item["title"])}</h2><p>{escape(item["body"])}</p></article>' for index, item in enumerate(content["sections"], 1))
            body = f'<section class="hero"><p class="eyebrow">可修改的平台</p><h1>{escape(content["site_title"])}</h1><p>{escape(content["tagline"])}</p><a class="button" href="/admin">开始编辑</a></section><section class="cards" aria-label="内容版块">{cards}</section>'
            response = layout(content, "", body)
        elif method == "GET" and route == "/admin":
            forms = "".join(f'''<form class="panel" method="post" action="/admin/sections/{escape(item["id"])}"><h2>编辑版块</h2><label>标题<input name="title" value="{escape(item["title"])}" required></label><label>内容<textarea name="body" rows="5">{escape(item["body"])}</textarea></label><div class="actions"><button>保存版块</button><button class="delete" formaction="/admin/sections/{escape(item["id"])}/delete">删除</button></div></form>''' for item in content["sections"])
            body = f'''<section class="editor-heading"><p class="eyebrow">内容管理</p><h1>编辑你的平台</h1><p>保存后，首页会立即显示新内容。</p></section><section class="editor-grid"><form class="panel settings" method="post" action="/admin/settings"><h2>平台设置</h2><label>平台名称<input name="site_title" value="{escape(content["site_title"])}" required></label><label>副标题<textarea name="tagline" rows="3">{escape(content["tagline"])}</textarea></label><button>保存设置</button></form><form class="panel" method="post" action="/admin/sections"><h2>添加版块</h2><label>标题<input name="title" required></label><label>内容<textarea name="body" rows="4"></textarea></label><button>添加版块</button></form>{forms}</section>'''
            response = layout(content, "", body)
        elif method == "POST" and route.startswith("/admin/"):
            length = int(environ.get("CONTENT_LENGTH") or 0)
            form = {key: values[0].strip() for key, values in parse_qs(environ["wsgi.input"].read(length).decode()).items()}
            if route == "/admin/settings":
                content["site_title"] = form.get("site_title") or DEFAULT_CONTENT["site_title"]
                content["tagline"] = form.get("tagline", "")
            elif route == "/admin/sections":
                title = form.get("title", "")
                if title:
                    existing = {item["id"] for item in content["sections"]}
                    base, number = "section-" + "-".join(title.lower().split()), 2
                    section_id = base
                    while section_id in existing: section_id, number = f"{base}-{number}", number + 1
                    content["sections"].append({"id": section_id, "title": title, "body": form.get("body", "")})
            else:
                parts = route.split("/")
                section = next((item for item in content["sections"] if item["id"] == parts[3]), None)
                if section is None:
                    start_response("404 Not Found", [("Content-Type", "text/plain")]); return [b"Not found"]
                if len(parts) == 5 and parts[4] == "delete": content["sections"].remove(section)
                else: section.update(title=form.get("title") or "未命名版块", body=form.get("body", ""))
            save(content)
            return redirect(start_response, "/admin")
        else:
            start_response("404 Not Found", [("Content-Type", "text/plain")]); return [b"Not found"]
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(response)))])
        return [response]
    return application


app = create_app()

if __name__ == "__main__":
    with make_server("127.0.0.1", 5000, app) as server:
        print("打开 http://127.0.0.1:5000")
        server.serve_forever()
