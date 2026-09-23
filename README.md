# 一期流式语音原型

开启语音 → 实时字幕 → 停顿后定稿。本仓库不改现有 AI 平台。正式接入时：识别文本写入对话输入框供编辑，**禁止识别完自动进 Agent**。

当前 Phase 1 走**云端流式 ASR**（火山引擎或阿里云）。本机只跑 FastAPI + 浏览器，**不需要**本机 Xinference、PyTorch、ffmpeg。浏览器里的 AudioWorklet 直接产出 16 kHz PCM。

## Mac 和 Windows 差在哪

云端这条主路径两边流程相同，差别只在安装和启动命令：

| 内容 | macOS | Windows |
|------|--------|---------|
| 启动脚本 | `scripts/setup-mac.sh`、`scripts/start-api.sh` | `scripts/start-api.ps1` |
| 虚拟环境 Python | `.venv/bin/python` | `.venv\Scripts\python.exe` |
| 系统 Python | 自带常是 3.9，必须另装 3.11+ | 不要用本机过旧的 Python |
| 本机推理栈 | 不需要 | 不需要 |
| 麦克风 | 浏览器向系统要权限；用 `http://localhost:8000` | 同样必须 localhost 或 HTTPS；远程桌面还需开「远程音频录制」 |

这台 Mac 上还缺：Python 3.11+、`uv`、`.venv`、`backend/.env`、演示页的 Vue 静态文件。用下面的 Mac 步骤一次补齐。

旧的 `scripts/*.ps1`（Xinference / 本地 FunASR / CosyVoice）和 `backend/requirements-xinf.txt` 是上一阶段本机推理残留，**当前 `app.main` 已不再挂载那些路由**。不要在 Mac 上按旧 README 去装 Visual C++、钉 NumPy 2.1.3 或拉 15GB 模型。

## Mac 安装

1. 安装 [uv](https://docs.astral.sh/uv/)（会同时管理 Python 3.12，不必先装 Homebrew）：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

新开一个终端，或把 `~/.local/bin` 加进 `PATH`。

2. 在仓库根目录执行：

```bash
chmod +x scripts/setup-mac.sh scripts/start-api.sh
./scripts/setup-mac.sh
```

这会安装 Python 3.12、同步 `pyproject.toml` 依赖，并在没有 `backend/.env` 时从示例复制一份。脚本默认走 npmmirror / 清华 PyPI，避免直连 GitHub 过慢。

3. 编辑 `backend/.env`，选一个云端厂商并填密钥：

```bash
ASR_PROVIDER=volcengine
VOLC_API_KEY=你的密钥
```

或：

```bash
ASR_PROVIDER=aliyun
DASHSCOPE_API_KEY=你的密钥
ALIYUN_WORKSPACE_ID=你的业务空间
```

## 启动

```bash
./scripts/start-api.sh
```

浏览器打开 http://localhost:8000 ，点「开启语音」。必须用 localhost 或 HTTPS，否则浏览器不给麦克风。

手动启动等价于：

```bash
cd backend
../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 接口

- `GET /health`：进程存活
- `GET /api/v1/voice/health`：云端凭证是否齐备、短连是否通
- `WS /api/v1/voice/stream`：浏览器 PCM 上行，中间结果 / 定稿下行

前端可复用：`frontend/src/components/VoiceInput.vue`（后续接入平台用）。演示页是本地 Vue 单页，不需要再装 Node。

## 环境变量

复制 `backend/.env.example` 为 `backend/.env`。

| 变量 | 必填 | 说明 |
|------|------|------|
| `ASR_PROVIDER` | 是 | `volcengine` 或 `aliyun` |
| `VOLC_API_KEY` | 火山必填 | 新版豆包语音控制台的 API Key（[文档 6561/1354869](https://docs.volcengine.com/docs/6561/1354869)） |
| `VOLC_RESOURCE_ID` | 否 | 默认 `volc.seedasr.sauc.duration`（2.0 小时版）。须在控制台开通对应能力，否则握手 403 |
| `VOLC_WS_URL` | 否 | 默认优化双向流 `wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async` |
| `DASHSCOPE_API_KEY` | 阿里必填 | DashScope API Key |
| `ALIYUN_WORKSPACE_ID` | 阿里必填 | 百炼业务空间 |
| `ALIYUN_ASR_MODEL` | 否 | 默认 `paraformer-realtime-v2` |
| `ASR_END_WINDOW_MS` | 否 | 停顿定稿窗口，默认 2000 |
| `APP_HOST` / `APP_PORT` | 否 | 默认 `127.0.0.1:8000` |

## Windows 启动（对照）

依赖同样用仓库根目录 `uv sync`。然后：

```powershell
.\scripts\start-api.ps1
```
