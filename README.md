# 粤智安 · 联网政务问办智能体平台

一个仅使用 Python 标准库构建的政务智能体演示平台，包含：安全认证、提示词注入与敏感信息防护、联网公开信息检索、可选的大模型生成答复、普通用户自主事项查询，以及管理员表格导入发布。

> 原型不应用于真实政务数据。真实部署需使用经过评测的模型服务、政务统一身份认证、HTTPS/MFA/RBAC、数据分级分类、加密和受控审计存储。

## 运行与账号

```bash
python app.py
```

服务默认监听 `0.0.0.0:5000`，同一 Wi‑Fi/内网中的手机和电脑可用浏览器访问 `http://<电脑局域网 IP>:5000`。例如电脑 IP 为 `192.168.1.20` 时，手机访问 `http://192.168.1.20:5000/service`。如需更改监听地址或端口：

```bash
HOST=0.0.0.0 PORT=8080 python app.py
```

页面已采用响应式布局；在手机浏览器中可通过“添加到主屏幕”安装为类 App 体验。Service Worker 仅缓存公开页面外壳，不缓存登录会话和政务问答 API 响应。对外网或真实政务数据部署时，必须置于 HTTPS 反向代理、身份认证网关和防火墙之后，**不要**直接暴露此演示服务器或默认演示账号。

### 使用 Cloudflare Tunnel 让手机通过公网访问

先在电脑上启动平台：

```bash
python app.py
```

#### 临时演示（无需域名）

安装 `cloudflared` 后，在另一个终端运行：

```bash
cloudflared tunnel --url http://127.0.0.1:5000
```

命令会输出一个临时的 `https://*.trycloudflare.com` 地址。将该 HTTPS 地址发到手机，在手机浏览器打开即可。此方式适合演示；地址会变化、进程退出即失效，且不应暴露默认演示账号或真实政务数据。

#### 固定域名（推荐）

1. 将域名托管到 Cloudflare，并在 Cloudflare Zero Trust 中创建 Tunnel，获取连接器令牌。
2. 在运行本平台的电脑/服务器上执行：

   ```bash
   cloudflared tunnel run --token <TUNNEL_TOKEN>
   ```

3. 在 Tunnel 的 Public Hostname 中设置域名（例如 `ai.example.gov.cn`），服务地址填写 `http://127.0.0.1:5000`。
4. 在该公网域名上配置 Cloudflare Access：要求政务统一身份认证或至少指定人员登录后才能访问；再将本平台的 `operator`/`admin` 演示账号替换为实际身份系统。

Tunnel 从本机主动建立到 Cloudflare 的出站连接，因此通常无需在路由器上做端口映射。生产环境请把应用进程、`cloudflared` 和数据目录部署到受控服务器，并限制管理入口；不要把 `admin` 登录页直接公开给互联网。

| 账号 | 密码 | 权限 |
| --- | --- | --- |
| `operator` | `Gd12345!` | 联网问办智能体、安全运营台 |
| `admin` | `AdminGd!2026` | 上述权限 + 政务事项表格导入发布 |

访问：

* `http://127.0.0.1:5000/login`：认证后进入联网问办智能体。
* `http://127.0.0.1:5000/service`：普通用户自主查询页面，无需登录。
* `http://127.0.0.1:5000/admin`：管理员导入政务事项表格，发布后会立即更新普通用户查询内容。

## 联网智能体

`POST /api/agent` 需要已认证会话。请求依次经过安全审查、公开网络检索和受限答复：高危请求不会被发送到外部搜索或大模型；安全请求返回答复和可点击的来源。

默认通过 DuckDuckGo HTML 检索公开网页。若配置以下环境变量，平台会调用兼容 OpenAI Chat Completions 协议的大模型（可替换为企业内网模型网关）：

```bash
export LLM_API_URL="https://your-model-gateway/v1/chat/completions"
export LLM_API_KEY="your-key"
export LLM_MODEL="your-model"
```

未配置模型时，智能体不会伪造答案，而是提供检索来源并提示用户核验官方办事指南。

## 政务表格导入

管理员在 `/admin` 上传 `.csv` 或 `.xlsx`。首行支持以下列名（二选一）：

| 标准列 | 中文列 | 必填 |
| --- | --- | --- |
| `title` | `事项名称` | 是 |
| `category` | `分类` | 否 |
| `description` | `简介` | 否 |
| `link` | `链接` | 否 |

导入将原子化更新 `data/services.json`，普通用户在 `/service` 的检索结果会随即切换至新内容。

## 测试

```bash
python -m unittest discover -s tests
```
