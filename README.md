# 一期 STT 独立原型（A1 · Xinference）

按住说话 → 松手识别 → 文本回填提示词框。本仓库不改现有 AI 平台，接口形状对齐后续接入。

本机是远程 Windows，**不用 Docker**。能选安装位置的运行时、服务和模型，一律装到 `D:\Users\Worker\Program\services`。源码仍在 `D:\Users\Worker\code\voice-rec-system`。

## 安装位置

| 内容 | 路径 |
|------|------|
| 服务安装根目录 | `D:\Users\Worker\Program\services` |
| Python 3.12 | `D:\Users\Worker\Program\services\python312` |
| ffmpeg | `D:\Users\Worker\Program\services\ffmpeg` |
| 安装包缓存 | `D:\Users\Worker\Program\services\downloads` |
| Xinference 模型/日志 | `D:\Users\Worker\Program\services\xinference` |
| FastAPI 虚拟环境 | `D:\Users\Worker\code\voice-rec-system\.venv` |
| Xinference 虚拟环境 | `D:\Users\Worker\code\voice-rec-system\.venv-xinf` |

磁盘建议预留 ≥ 15GB。首次拉模型需要外网（默认 ModelScope）。

## 动手前必须装好

1. **Python 3.12（64 位）**，已放到 `D:\Users\Worker\Program\services\python312`。不要用本机默认的 3.6。
2. **Microsoft Visual C++ Redistributable 2015–2022 x64**（缺了 PyTorch 起不来）。
3. **ffmpeg**：`D:\Users\Worker\Program\services\ffmpeg\bin\ffmpeg.exe` 能执行（本机用 `imageio-ffmpeg` 取出官方 essentials 二进制后拷到该路径）。
4. **Xinference + 音频后端**（在 `.venv-xinf`）：`xinference[transformers]`、`torch`、`torchaudio`、`funasr`。不要装 `xinference[all]` / `xinference[vllm]`。
5. **本仓库 FastAPI 依赖**（在 `.venv`）：见 `backend/requirements.txt`。
6. 浏览器录音必须用 `http://localhost:8000` 或 HTTPS。远程桌面需开启「远程音频录制」。

## 环境变量（两套，不要混）

### A. 启动 Xinference 的终端

| 变量 | 必填 | 推荐值 | 作用 |
|------|------|--------|------|
| `XINFERENCE_HOME` | 建议填 | `D:\Users\Worker\Program\services\xinference` | 模型与日志，避免写满 C 盘 |
| `XINFERENCE_MODEL_SRC` | 建议填 | `modelscope` | 国内下载源 |
| `XINFERENCE_ENDPOINT` | 否 | `http://127.0.0.1:9997` | CLI 连接地址 |
| `XINFERENCE_AUTH_ADVANCED` | 一期必填 | `0` | 关掉新版默认鉴权，否则转写 401 |
| `XINFERENCE_ENABLE_VIRTUAL_ENV` | 本机必填 | `0` | 关掉模型独立虚拟环境，复用 `.venv-xinf` 里已钉版本的 NumPy/FunASR |

```powershell
$env:Path = "D:\Users\Worker\Program\services\ffmpeg\bin;" + $env:Path
$env:XINFERENCE_HOME = "D:\Users\Worker\Program\services\xinference"
$env:XINFERENCE_MODEL_SRC = "modelscope"
$env:XINFERENCE_AUTH_ADVANCED = "0"
$env:XINFERENCE_ENABLE_VIRTUAL_ENV = "0"
& D:\Users\Worker\code\voice-rec-system\.venv-xinf\Scripts\xinference-local.exe --host 127.0.0.1 --port 9997
```

另开终端启动模型（官方名是小写 `paraformer-zh`）：

```powershell
$env:XINFERENCE_ENDPOINT = "http://127.0.0.1:9997"
& D:\Users\Worker\code\voice-rec-system\.venv-xinf\Scripts\xinference.exe launch --model-name paraformer-zh --model-type audio
& D:\Users\Worker\code\voice-rec-system\.venv-xinf\Scripts\xinference.exe list
```

### B. 本仓库 FastAPI（`backend/.env`）

复制 `backend/.env.example` 为 `backend/.env`。

| 变量 | 必填 | 推荐值 | 作用 |
|------|------|--------|------|
| `XINFERENCE_URL` | 是 | `http://127.0.0.1:9997` | 推理根地址 |
| `XINFERENCE_API_KEY` | 否 | 空 | 一期鉴权关闭则留空 |
| `ASR_MODEL` | 是 | `paraformer-zh` | 必须与 `xinference list` 的 uid 一致 |
| `ASR_TIMEOUT_SECONDS` | 否 | `60` | 调用超时 |
| `FFMPEG_PATH` | 否 | `D:\Users\Worker\Program\services\ffmpeg\bin\ffmpeg.exe` | ffmpeg 绝对路径 |
| `APP_HOST` | 否 | `127.0.0.1` | 只绑本机，方便 localhost 录音 |
| `APP_PORT` | 否 | `8000` | FastAPI 端口 |

## 启动本仓库

```powershell
cd D:\Users\Worker\code\voice-rec-system\backend
D:\Users\Worker\code\voice-rec-system\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 http://localhost:8000

## 接口

- `GET /api/v1/asr/health`：检查 ffmpeg 与配置
- `POST /api/v1/asr/transcribe`：`multipart` 字段 `file`，返回 `{ text, model, duration_ms, cost_ms }`

前端可复用组件：`frontend/src/components/VoiceInput.vue`（后续接入平台用，只含按住说话）。演示页是同行为的本地 Vue 单页，不需要再装 Node 构建。

演示页右上角「设置 → 开发者模式」是本仓库内测开关（`localStorage` 键 `voice-rec.devMode`）：开启后可选择本地音频文件，当作录制完成的音频走同一条 STT 回填提示词。**接入 wx-iecm 时不要带设置面板、开发者模式或选文件。**

## 本机踩坑（已处理）

- 默认 `python` 是 3.6，不能用。本仓库使用 `D:\Users\Worker\Program\services\python312`。
- 新版 NumPy 2.5 需要 X86_V2 指令集，本机 CPU 不支持。`.venv-xinf` 必须钉 `numpy==2.1.3`、`scipy==1.14.1`。
- FunASR 会调系统 `ffmpeg`，启动 Xinference 前要把 `D:\Users\Worker\Program\services\ffmpeg\bin` 加进 PATH。
- Windows 上 Xinference 默认用 `NamedTemporaryFile` 会导致识别 WinError 2，已在 `.venv-xinf` 里改成先落盘再识别。
- 关掉 `XINFERENCE_ENABLE_VIRTUAL_ENV`，避免再装一份会拉高指令集 NumPy 的模型环境。
