# 语音交互模块 Demo（Phase 1：流式字幕）

按最新方案只做 Phase 1：浏览器采集麦克风，经 FastAPI WebSocket 转接到阿里云或火山的流式 ASR，页面实时显示中间字幕和定稿。不接 Agent，也不做语音播报和打断。

本机 Xinference、热词后处理和 CosyVoice 不是这条链路。`scripts/` 里的旧启动脚本可以留着，演示页不会调用它们。

## 语音何时算开启

页面加载后先请求 `GET /api/v1/voice/health`。

- `ready` 为真：云端 ASR 的厂商和密钥已配齐，并且服务能连上云端。这时「开启语音」可以点。
- 用户点击「开启语音」并完成麦克风授权、WebSocket 收到 `ready` 之后，语音才算开启。
- 再点「关闭语音」会停麦、断流。刷新页面后仍是关闭，不会自动开。

`ready` 只表示可以开，不表示已经开着。缺密钥、`ASR_PROVIDER` 不正确或云端连不上时，按键禁用，并在旁边写明原因。

## 环境

- Python 3.11+（`uv` 会按 `pyproject.toml` 选用或下载）
- 包管理：`uv`（`uv --version` 能跑即可）
- 虚拟环境：仓库根目录 `.venv`（`uv sync` 创建）
- 依赖：`pyproject.toml` / `uv.lock`（`backend/requirements.txt` 仅作对照）
- 浏览器必须用 `http://localhost:8000` 或 HTTPS，否则没有麦克风权限

首次在仓库根目录执行：

```powershell
uv sync
```

或跑 `scripts/setup.ps1`（内部也是 `uv sync`）。若还没有 `backend/.env`，脚本会从 `backend/.env.example` 复制一份。

复制 `backend/.env.example` 为 `backend/.env` 后填写密钥。

| 变量 | 作用 |
|------|------|
| `ASR_PROVIDER` | `aliyun` 或 `volcengine`，改完重启 FastAPI |
| `DASHSCOPE_API_KEY` | 阿里云百炼 API Key |
| `ALIYUN_WORKSPACE_ID` | 阿里云百炼业务空间 ID，用于 `wss://{WorkspaceId}.cn-beijing.maas.aliyuncs.com` |
| `ALIYUN_ASR_MODEL` | 默认 `paraformer-realtime-v2` |
| `VOLC_API_KEY` | 火山引擎新版豆包语音控制台的 API Key |
| `VOLC_RESOURCE_ID` | 与已开通能力一致，1.0 小时版为 `volc.bigasr.sauc.duration`，2.0 小时版为 `volc.seedasr.sauc.duration` |
| `ASR_END_WINDOW_MS` | 静音多久后定稿，毫秒。默认 `2000`，范围 500–6000 |

两家都实现了 Adapter。同一页面只换 `ASR_PROVIDER` 并重启，按键和字幕协议不变。

如果本机把代理指到没有在听的 `127.0.0.1`，健康检查会失败，按键保持禁用。跑 FastAPI 的进程需要能直接访问阿里云和火山。

## 启动

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-api.ps1
```

没有 `.venv` 时，`start-api.ps1` 会先跑一遍 `setup.ps1`。也可以手动启动：

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 http://localhost:8000 。默认不要麦克风。点「开启语音」后说话，当前句会刷新，停顿后出现在「已定稿」。

## 接口

- `GET /api/v1/voice/health`：`ready`、`provider`、`model`、`reason`。不返回密钥。
- `WS /api/v1/voice/stream`：客户端先发 `{"type":"start"}`，再发 16 kHz、16-bit、单声道 PCM 二进制帧（约 200 ms 一包），结束发 `{"type":"stop"}`。服务端回 `ready`、`partial`、`final`、`error`。

可复用组件是 `frontend/src/components/VoiceInput.vue`，行为与演示页相同：开启/关闭按键、partial / final。演示页本身不经过 Node 构建。
