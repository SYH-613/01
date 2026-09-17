"""粤智安：政务问办智能体、安全审查、搜索与内容运营演示平台。"""

from __future__ import annotations

import csv
import hashlib
import hmac
import html
import io
import json
import os
import re
import secrets
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

ROOT = Path(__file__).parent
CONTENT_PATH = ROOT / "data" / "services.json"
USERS = {
    "operator": {"password": "Gd12345!", "role": "operator", "name": "政务运营人员"},
    "admin": {"password": "AdminGd!2026", "role": "admin", "name": "平台管理员"},
}
RISK_RULES = {
    "提示词注入": ("high", ["忽略之前", "忽略上述", "system prompt", "提示词", "越过限制", "开发者消息"]),
    "恶意诱导": ("high", ["绕过", "破解", "伪造", "攻击", "删除记录", "后门"]),
    "隐私泄露": ("high", ["身份证", "手机号", "银行卡", "住址", "人脸", "社保卡"]),
    "越权回答": ("medium", ["内部审批", "后台账号", "管理员权限", "保密文件", "执法记录"]),
    "政策误导": ("medium", ["保证通过", "一定能办", "无需材料", "不要审核"]),
}
PII_PATTERNS = {
    "身份证号": re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
    "手机号码": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "银行卡号": re.compile(r"(?<!\d)(?:\d[ -]?){15,18}\d(?!\d)"),
}
DEFAULT_SERVICES = [
    {"title": "生育登记", "category": "社会保障", "description": "查询生育登记办理指南、材料与办理入口。", "link": "https://www.gdzwfw.gov.cn/"},
    {"title": "社保医保服务", "category": "社会保障", "description": "查询社保医保参保、缴费与待遇服务。", "link": "https://www.gdzwfw.gov.cn/"},
    {"title": "企业开办", "category": "企业服务", "description": "查询企业设立、变更和注销办事指引。", "link": "https://www.gdzwfw.gov.cn/"},
]


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def safe_url(value: str) -> str:
    """Prevent imported or searched content from becoming an executable link."""
    return value if urllib.parse.urlparse(value).scheme in {"http", "https"} else "https://www.gdzwfw.gov.cn/"


def password_digest(password: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), b"yuezhi-an-demo-v2", 120_000).hex()


USER_DIGESTS = {username: password_digest(info["password"]) for username, info in USERS.items()}


def redact(text: str) -> tuple[str, list[str]]:
    found: list[str] = []
    for label, pattern in PII_PATTERNS.items():
        if pattern.search(text):
            found.append(label)
            text = pattern.sub(lambda match: match.group(0)[:3] + "*" * max(4, len(match.group(0)) - 7) + match.group(0)[-4:], text)
    return text, found


def audit_text(text: str) -> dict[str, Any]:
    matched = []
    normalized = text.lower()
    for category, (level, keywords) in RISK_RULES.items():
        hits = [word for word in keywords if word.lower() in normalized]
        if hits:
            matched.append({"category": category, "level": level, "evidence": hits})
    masked, pii = redact(text)
    if pii and not any(item["category"] == "隐私泄露" for item in matched):
        matched.append({"category": "隐私泄露", "level": "high", "evidence": pii})
    decision = "通过" if not matched else ("拦截" if any(item["level"] == "high" for item in matched) else "复核")
    guidance = {"通过": "安全审查通过，可进入受控问办流程。", "复核": "已转人工复核政策依据与答复边界。", "拦截": "请求已拦截，请勿提交个人敏感信息或尝试绕过安全边界。"}[decision]
    return {"decision": decision, "risks": matched, "redacted_text": masked, "pii_types": pii, "guidance": guidance,
            "audit_id": "GD-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")}


def load_services() -> list[dict[str, str]]:
    if not CONTENT_PATH.exists():
        save_services(DEFAULT_SERVICES)
        return DEFAULT_SERVICES.copy()
    return json.loads(CONTENT_PATH.read_text(encoding="utf-8"))


def save_services(services: list[dict[str, str]]) -> None:
    CONTENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=CONTENT_PATH.parent, delete=False) as file:
        json.dump(services, file, ensure_ascii=False, indent=2)
        name = file.name
    Path(name).replace(CONTENT_PATH)


def web_search(query: str, limit: int = 5) -> list[dict[str, str]]:
    """Search public web through DuckDuckGo HTML. Network errors return an empty list."""
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 YuezhiAn/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            source = response.read().decode("utf-8", "ignore")
    except OSError:
        return []
    results = []
    for href, title, snippet in re.findall(r'nofollow" class="result__a" href="(.*?)">(.*?)</a>.*?result__snippet">(.*?)</', source, re.S):
        link = html.unescape(href)
        if link.startswith("//duckduckgo.com/l/?"):
            link = parse_qs(urllib.parse.urlparse(link).query).get("uddg", [link])[0]
        results.append({"title": re.sub("<.*?>", "", html.unescape(title)).strip(), "url": safe_url(link),
                        "snippet": re.sub("<.*?>", "", html.unescape(snippet)).strip()})
        if len(results) == limit:
            break
    return results


def ask_llm(question: str, sources: list[dict[str, str]]) -> str | None:
    """Optionally call an OpenAI-compatible model when deployment credentials are configured."""
    endpoint, key, model = os.getenv("LLM_API_URL"), os.getenv("LLM_API_KEY"), os.getenv("LLM_MODEL")
    if not all((endpoint, key, model)):
        return None
    context = "\n".join(f"- {item['title']}: {item['snippet']} ({item['url']})" for item in sources)
    prompt = ("你是广东政务问办助手。仅依据下列检索材料回答；材料不足时明确说明并建议用户查看官方链接。"
              "不要索要个人敏感信息，不要承诺审批结果。\n材料：\n" + context + "\n用户问题：" + question)
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2}).encode()
    request = urllib.request.Request(endpoint, body, {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)["choices"][0]["message"]["content"].strip()
    except (OSError, KeyError, IndexError, json.JSONDecodeError):
        return None


def agent_reply(text: str) -> dict[str, Any]:
    report = audit_text(text)
    if report["decision"] != "通过":
        return report | {"answer": report["guidance"], "handoff": True, "sources": []}
    sources = web_search(text)
    answer = ask_llm(text, sources)
    if not answer:
        answer = "已完成公开信息检索。请查看下方来源；办理条件、材料和时限请以主管部门最新公布信息为准。" if sources else "暂未获得可用的公开检索结果。建议前往广东政务服务网自主查询或转人工咨询。"
    return report | {"answer": answer, "handoff": False, "sources": sources}


def parse_table(filename: str, content: bytes) -> list[dict[str, str]]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        rows = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
        parsed = list(rows)
    elif suffix == ".xlsx":
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            shared = []
            if "xl/sharedStrings.xml" in archive.namelist():
                root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                shared = ["".join(node.itertext()) for node in root]
            sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            matrix = []
            for row in sheet.findall(".//{*}row"):
                values = []
                for cell in row.findall("{*}c"):
                    value = cell.findtext("{*}v", "")
                    values.append(shared[int(value)] if cell.get("t") == "s" and value else value)
                matrix.append(values)
        headers = matrix[0] if matrix else []
        parsed = [dict(zip(headers, row)) for row in matrix[1:]]
    else:
        raise ValueError("仅支持 .csv 或 .xlsx 文件")
    services = []
    for row in parsed:
        title = (row.get("title") or row.get("事项名称") or "").strip()
        if title:
            services.append({"title": title, "category": (row.get("category") or row.get("分类") or "政务服务").strip(),
                             "description": (row.get("description") or row.get("简介") or "请查看办事指南。").strip(),
                             "link": safe_url((row.get("link") or row.get("链接") or "https://www.gdzwfw.gov.cn/").strip())})
    if not services:
        raise ValueError("表格中未找到事项；请使用 title/事项名称 列")
    return services


def layout(title: str, body: str) -> bytes:
    return f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#152039"><meta name="apple-mobile-web-app-capable" content="yes"><title>{escape(title)} · 粤智安</title><link rel="manifest" href="/manifest.webmanifest"><link rel="stylesheet" href="/static/style.css"></head><body>{body}<script src="/static/app.js"></script></body></html>'.encode()


def login_page(error: str = "") -> bytes:
    warning = f'<p class="login-error">{escape(error)}</p>' if error else ""
    return layout("安全登录", f'''<div class="login-page"><main class="login-card"><div class="login-mark"><span class="mark-icon">Y</span><span>粤智安</span></div><p class="login-kicker">广东政务智能体安全运营平台</p><h1>安全登录</h1><p class="login-copy">登录后使用联网问办智能体和受控运营功能。</p>{warning}<form method="post" action="/login"><label>账号<input name="username" autocomplete="username" required></label><label>密码<input name="password" type="password" autocomplete="current-password" required></label><button class="primary login-button">安全登录 →</button></form><div class="login-note"><b>演示账号</b><span>operator / Gd12345!（问办）</span><span>admin / AdminGd!2026（内容运营）</span><small>生产环境须对接统一身份认证、MFA、RBAC 与 HTTPS。</small></div></main></div>''')


def service_page(services: list[dict[str, str]], query: str = "") -> bytes:
    selected = [item for item in services if query.lower() in (item["title"] + item["category"] + item["description"]).lower()]
    cards = "".join(f'<article class="service-card"><span>{escape(item["category"])}</span><h2>{escape(item["title"])}</h2><p>{escape(item["description"])}</p><a href="{escape(item["link"])}" target="_blank" rel="noopener">查看官方指南 →</a></article>' for item in selected)
    return layout("自主政务查询", f'''<main class="public"><header><a class="brand" href="/service">粤智安 · 政务服务查询</a><nav><a href="/login">运营登录</a></nav></header><section class="service-hero"><p>广东政务服务 · 自主查询</p><h1>自己查，也可以问 AI</h1><form method="get" action="/service"><input name="q" value="{escape(query)}" placeholder="搜索办事事项、服务分类或关键词"><button class="primary">搜索</button></form><small>查询结果由管理员发布的政务事项内容提供；请以官方办事指南为准。</small></section><section class="service-cards">{cards or '<p>未找到相关事项，请更换关键词或访问广东政务服务网。</p>'}</section></main>''')


def dashboard(user: dict[str, str]) -> bytes:
    admin_link = '<a href="/admin">内容运营</a>' if user["role"] == "admin" else ""
    return layout("安全运营中心", f'''<aside class="sidebar"><div class="mark"><span class="mark-icon">Y</span><span>粤智安</span></div><nav class="side-nav"><a class="active" href="/">安全总览</a><a href="#agent">✦ 联网问办智能体</a><a href="/service">⌕ 自主政务查询</a>{admin_link}</nav><div class="sidebar-bottom"><div class="secure-badge"><span>✓</span><div><b>安全运行中</b><small>输入先审查后联网</small></div></div><div class="profile"><span class="avatar">政</span><div><b>{escape(user["name"])}</b><small>已认证 · {escape(user["role"])}</small></div><a class="logout" href="/logout">退出</a></div></div></aside><main class="workspace"><header class="header"><div><p class="crumb">政务智能体平台 / 安全运营中心</p><h1>可信政务智能体 <em>安全态势</em></h1></div><div class="header-actions"><a class="outline" href="/service">自主查询服务</a><span class="live"><b></b> 实时防护中</span></div></header><section class="notice"><span class="notice-icon">✦</span><p><b>联网检索已开启</b><span>智能体仅在安全审查通过后，检索公开信息并附带来源。</span></p><a href="/service">自主查找 →</a></section><section class="metrics"><article><p>今日安全对话</p><strong>128,694</strong><span class="up">↑ 12.6%</span><div class="bar"><i style="width:72%"></i></div><small>较昨日 +14,386 次</small></article><article><p>风险拦截次数</p><strong>2,847</strong><span class="up">↑ 8.2%</span><div class="bar coral"><i style="width:48%"></i></div><small>高危请求已自动处置</small></article><article><p>敏感信息脱敏</p><strong>6,291</strong><span class="up">↑ 15.3%</span><div class="bar purple"><i style="width:86%"></i></div><small>个人信息已安全处理</small></article><article><p>模型安全评分</p><strong>98.6<small> / 100</small></strong><span class="good">良好</span><div class="score"><i>●</i><span>安全基线达标</span></div></article></section><section class="lower-grid"><div class="panel agent" id="agent"><div class="panel-title"><div><h2>联网政务问办 AI 智能体</h2><p>安全审查 → 公开网络检索 → 有来源的受限答复。</p></div><span class="model">联网模式</span></div><label class="input-label" for="query">群众咨询（不会将个人敏感信息发送到外部搜索）</label><textarea id="query" placeholder="例如：我想咨询生育登记需要什么材料？"></textarea><div class="agent-footer"><span>可配置兼容 OpenAI API 的大模型；未配置时展示检索来源。</span><button class="primary" id="audit-button">向智能体提问 <b>→</b></button></div><div class="audit-result" id="audit-result" hidden></div></div><div class="panel events"><div class="panel-title"><div><h2>公众自主查询</h2><p>不依赖 AI，直接查询发布的政务事项。</p></div></div><p class="event-copy">公众可通过关键词浏览管理员发布的服务内容，打开官方办事指南自行核验。</p><a class="primary service-button" href="/service">进入自主查询 →</a></div></section></main><nav class="mobile-nav"><a href="/">总览</a><a href="#agent">问 AI</a><a href="/service">自主查</a></nav>''')


def admin_page(message: str = "", error: str = "") -> bytes:
    note = f'<p class="notice">{escape(message)}</p>' if message else f'<p class="login-error">{escape(error)}</p>' if error else ""
    return layout("政务内容运营", f'''<main class="admin-page"><header><a class="brand" href="/">粤智安 · 内容运营</a><nav><a href="/service">查看公众平台</a><a href="/logout">退出</a></nav></header><section class="admin-card"><p class="login-kicker">管理员专属功能</p><h1>导入政务事项，更新公众查询平台</h1><p>上传 CSV 或 XLSX 表格，系统将读取 <code>title/事项名称</code>、<code>category/分类</code>、<code>description/简介</code>、<code>link/链接</code> 列并整体更新公众平台内容。</p>{note}<form method="post" action="/admin/import" enctype="multipart/form-data"><input type="file" name="table" accept=".csv,.xlsx" required><button class="primary">导入并发布</button></form><a class="outline" href="/service">打开普通用户查询页</a></section></main>''')


def uploaded_file(environ: dict[str, Any]) -> tuple[str, bytes]:
    """Read the single file field submitted by the admin import form."""
    length = int(environ.get("CONTENT_LENGTH") or 0)
    raw = environ["wsgi.input"].read(length)
    content_type = environ.get("CONTENT_TYPE", "")
    match = re.search(r"boundary=([^;]+)", content_type)
    if not match:
        raise ValueError("未收到有效的文件上传请求")
    boundary = b"--" + match.group(1).strip('"').encode()
    for part in raw.split(boundary):
        headers, separator, body = part.partition(b"\r\n\r\n")
        filename = re.search(br'filename="([^"]+)"', headers)
        if filename and separator:
            return filename.group(1).decode("utf-8", "replace"), body.rsplit(b"\r\n", 1)[0]
    raise ValueError("未找到上传的表格文件")


def create_app():
    sessions: dict[str, dict[str, str]] = {}

    def current_user(environ: dict[str, Any]) -> dict[str, str] | None:
        cookie = SimpleCookie(environ.get("HTTP_COOKIE", ""))
        token = cookie.get("yuezhi_session")
        return sessions.get(token.value) if token else None

    def redirect(start_response, target: str, headers: list[tuple[str, str]] | None = None):
        start_response("303 See Other", [("Location", target), ("Content-Length", "0")] + (headers or []))
        return [b""]

    def json_response(start_response, status: str, value: dict[str, Any]):
        response = json.dumps(value, ensure_ascii=False).encode()
        start_response(status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(response)))])
        return [response]

    def read_form(environ: dict[str, Any]) -> dict[str, str]:
        length = int(environ.get("CONTENT_LENGTH") or 0)
        return {key: values[0] for key, values in parse_qs(environ["wsgi.input"].read(length).decode("utf-8")).items()}

    def application(environ, start_response):
        method, route = environ["REQUEST_METHOD"], environ["PATH_INFO"]
        if method == "GET" and route in {"/static/style.css", "/static/app.js"}:
            filename = route.rsplit("/", 1)[1]
            response = (ROOT / "static" / filename).read_bytes()
            content_type = "text/css; charset=utf-8" if filename.endswith("css") else "application/javascript; charset=utf-8"
            start_response("200 OK", [("Content-Type", content_type), ("Content-Length", str(len(response)))])
            return [response]
        if method == "GET" and route == "/manifest.webmanifest":
            response = json.dumps({"name": "粤智安政务服务", "short_name": "粤智安", "start_url": "/service", "display": "standalone", "background_color": "#f6f8fc", "theme_color": "#152039"}, ensure_ascii=False).encode()
            start_response("200 OK", [("Content-Type", "application/manifest+json; charset=utf-8"), ("Content-Length", str(len(response)))])
            return [response]
        if method == "GET" and route == "/sw.js":
            response = (ROOT / "static" / "sw.js").read_bytes()
            start_response("200 OK", [("Content-Type", "application/javascript; charset=utf-8"), ("Content-Length", str(len(response)))])
            return [response]
        if method == "GET" and route == "/service":
            query = parse_qs(environ.get("QUERY_STRING", "")).get("q", [""])[0].strip()
            response = service_page(load_services(), query)
            start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(response)))])
            return [response]
        if method == "GET" and route == "/login":
            response = login_page()
            start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(response)))])
            return [response]
        if method == "POST" and route == "/login":
            form = read_form(environ)
            username, password = form.get("username", ""), form.get("password", "")
            valid = username in USERS and hmac.compare_digest(password_digest(password), USER_DIGESTS[username])
            if not valid:
                response = login_page("账号或密码错误，请重试。")
                start_response("401 Unauthorized", [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(response)))])
                return [response]
            token = secrets.token_urlsafe(32)
            sessions[token] = {"username": username, "role": USERS[username]["role"], "name": USERS[username]["name"]}
            secure = "; Secure" if environ.get("wsgi.url_scheme") == "https" else ""
            return redirect(start_response, "/", [("Set-Cookie", f"yuezhi_session={token}; HttpOnly; SameSite=Lax; Path=/{secure}")])
        if method == "GET" and route == "/logout":
            cookie = SimpleCookie(environ.get("HTTP_COOKIE", ""))
            if token := cookie.get("yuezhi_session"):
                sessions.pop(token.value, None)
            return redirect(start_response, "/login", [("Set-Cookie", "yuezhi_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")])
        user = current_user(environ)
        if method == "POST" and route in {"/api/audit", "/api/agent", "/api/search"}:
            if not user:
                return json_response(start_response, "401 Unauthorized", {"error": "authentication_required"})
            length = int(environ.get("CONTENT_LENGTH") or 0)
            raw = environ["wsgi.input"].read(length).decode("utf-8")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {key: values[0] for key, values in parse_qs(raw).items()}
            text = str(payload.get("text", ""))
            report = audit_text(text)
            if route == "/api/search":
                return json_response(start_response, "200 OK", report | {"sources": web_search(text) if report["decision"] == "通过" else []})
            return json_response(start_response, "200 OK", report if route == "/api/audit" else agent_reply(text))
        if method == "GET" and route == "/admin":
            if not user or user["role"] != "admin":
                return redirect(start_response, "/login")
            response = admin_page()
            start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(response)))])
            return [response]
        if method == "POST" and route == "/admin/import":
            if not user or user["role"] != "admin":
                start_response("403 Forbidden", [("Content-Type", "text/plain; charset=utf-8")])
                return [b"Administrator role required"]
            try:
                filename, content = uploaded_file(environ)
                services = parse_table(filename, content)
                save_services(services)
                response = admin_page(message=f"已成功发布 {len(services)} 条政务事项；普通用户查询页已更新。")
                start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(response)))])
                return [response]
            except (ValueError, UnicodeDecodeError, zipfile.BadZipFile) as error:
                response = admin_page(error=str(error))
                start_response("400 Bad Request", [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(response)))])
                return [response]
        if method == "GET" and route == "/":
            if not user:
                return redirect(start_response, "/login")
            response = dashboard(user)
            start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(response)))])
            return [response]
        start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"Not found"]
    return application


app = create_app()

if __name__ == "__main__":
    host, port = os.getenv("HOST", "0.0.0.0"), int(os.getenv("PORT", "5000"))
    with make_server(host, port, app) as server:
        print(f"粤智安运行于 http://{host}:{port}")
        server.serve_forever()
