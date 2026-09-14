# 语音独立原型（一期 STT · 二期 TTS）

按住说话 → 松手识别 → 文本回填提示词框，用户再编辑。二期：把「平台输出」文本合成为语音并朗读。本仓库不改现有 AI 平台，接口形状对齐后续接入。正式项目接入时：识别文本写入对话输入框供编辑，**禁止识别完自动进 Agent**；平台回复**不要自动朗读**，由用户点播放。后续接入 wx-iecm 时，助手气泡在流式结束或句边界调用 `frontend/src/components/VoiceOutput.vue`。

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

另开终端一次拉起 **一份** ASR + **一份** TTS（`launch-asr-model.ps1` / `launch-tts-model.ps1` 都指向同一合并脚本）：

```powershell
& D:\Users\Worker\code\voice-rec-system\scripts\launch-models.ps1
```

ASR 官方名是小写 `seaco-paraformer-zh`（支持热词）；TTS 默认档 A 是 `CosyVoice-300M-SFT`。脚本用 `/v1/models` 判断是否已在跑，已存在就跳过，多出来的副本会 terminate。不要再手打第二次 `xinference launch seaco-paraformer-zh`，否则会出现 `seaco-paraformer-zh-xxxx` 第二份，把内存占满，CosyVoice 子进程起不来。

CLI 报 100% / 给出 UID **不代表模型还活着**。以 `xinference list` 或 `GET /api/v1/tts/health` 的 `current_launched` 为准。失败看 `XINFERENCE_HOME\logs\xinference.log`（常见：`Start sub pool failed`）。

### B. 本仓库 FastAPI（`backend/.env`）

复制 `backend/.env.example` 为 `backend/.env`。

| 变量 | 必填 | 推荐值 | 作用 |
|------|------|--------|------|
| `XINFERENCE_URL` | 是 | `http://127.0.0.1:9997` | 推理根地址 |
| `XINFERENCE_API_KEY` | 否 | 空 | 一期鉴权关闭则留空 |
| `ASR_MODEL` | 是 | `seaco-paraformer-zh` | 必须与 `xinference list` 的 uid 一致 |
| `ASR_TIMEOUT_SECONDS` | 否 | `60` | 调用超时 |
| `ASR_HOTWORDS_DIR` | 否 | `data/hotwords` | 三层热词目录（platform / industry / tenant） |
| `ASR_REPLACEMENTS_FILE` | 否 | `data/replacements.yaml` | 后处理谐音/大小写映射 |
| `ASR_POSTPROCESS_ENABLED` | 否 | `1` | 关后处理则原样返回识别文本 |
| `ASR_ITN_ENABLED` | 否 | `1` | 中文数字串转阿拉伯数字 |
| `FFMPEG_PATH` | 否 | `D:\Users\Worker\Program\services\ffmpeg\bin\ffmpeg.exe` | ffmpeg 绝对路径 |
| `TTS_PROFILE` | 否 | `A` | TTS 档位，`A` 或 `B`，改完需重启 FastAPI |
| `TTS_MODEL_A` | 否 | `CosyVoice-300M-SFT` | 默认档，预置音色 |
| `TTS_MODEL_B` | 否 | `CosyVoice2-0.5B` | 备用档，音质更好、体积更大 |
| `TTS_VOICE` | 否 | `中文女` | CosyVoice 预置音色 |
| `TTS_TIMEOUT_SECONDS` | 否 | `180` | 合成超时。CosyVoice 一次推理开销大，短文不要拆成很多段 |
| `TTS_READINGS_FILE` | 否 | `data/tts_readings.yaml` | 专名读法表 |
| `APP_HOST` | 否 | `127.0.0.1` | 只绑本机，方便 localhost 录音 |
| `APP_PORT` | 否 | `8000` | FastAPI 端口 |

## 启动本仓库

```powershell
cd D:\Users\Worker\code\voice-rec-system\backend
D:\Users\Worker\code\voice-rec-system\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 http://localhost:8000

## 接口

- `GET /api/v1/asr/health`：检查 ffmpeg、当前模型、热词数量、后处理开关
- `POST /api/v1/asr/transcribe`：`multipart` 字段 `file`，可选 `hotword`（调试覆盖，演示页和 `VoiceInput.vue` 不传）。返回 `{ text, raw_text, model, duration_ms, cost_ms }`。前端只把 `text` 写入可编辑输入框。
- `GET /api/v1/tts/health`：当前 TTS 档位、模型名、Xinference 是否可达、A/B 是否已 launch
- `POST /api/v1/tts/speech`：JSON `{ "text": "...", "voice": "" }`（`voice` 可空，覆盖默认音色）。返回音频字节，响应头带 `X-TTS-Profile` / `X-TTS-Model` / `X-TTS-Cost-Ms`。

热词示例（Xinference 侧，本仓库 FastAPI 会自动带上合并后的词表）：

```bash
curl -X POST "http://127.0.0.1:9997/v1/audio/transcriptions" \
  -F file="@voice.wav" \
  -F model="seaco-paraformer-zh" \
  -F "kwargs={\"hotword\":\"RAG API gateway pgvector\"}"
```

## 热词与后处理

三层词表在 `backend/data/hotwords/`：`platform.txt`（产品/技术词）、`industry.txt`（行业包）、`tenant.txt`（客户名，默认空）。一行一词，`#` 开头为注释。**改文件后不必重启 FastAPI**，下一次转写按 mtime 重载。

后处理规则在 `backend/data/replacements.yaml`（谐音映射、英文大小写），同样按 mtime 重载。

前端可复用组件：`frontend/src/components/VoiceInput.vue`（后续接入平台用，只含按住说话并回填输入框，不含高亮/替换芯片）、`frontend/src/components/VoiceOutput.vue`（朗读 / 停止，不含开发者模式和保存按钮）。演示页是同行为的本地 Vue 单页，不需要再装 Node 构建。

演示页右上角「设置 → 开发者模式」是本仓库内测开关（`localStorage` 键 `voice-rec.devMode`）：开启后可选择本地音频文件走 STT，也可把最近一次 TTS 合成结果下载到本机（文件名如 `tts-A-20260914-0949.mp3`）。**接入 wx-iecm 时不要带设置面板、开发者模式、选文件或保存音频；识别结果写入输入框后由用户编辑，不要自动发送；回复不要自动朗读。**

## 二期 TTS（平台输出词朗读）

先启动 Xinference（与一期同一进程），再运行合并脚本。脚本用 `/v1/models` 判断，**每种模型最多一份**：已有 `seaco-paraformer-zh` 就不再 launch；若存在 `seaco-paraformer-zh-xxxx` 这种副本会先 terminate。不要连续跑两次 launch，也不要先单独 launch ASR 再 launch TTS（两个旧脚本都指向这一份合并脚本）。

```powershell
& D:\Users\Worker\code\voice-rec-system\scripts\launch-models.ps1
```

| 档位 | 模型 | 说明 |
|------|------|------|
| A（默认） | `CosyVoice-300M-SFT` | 预置音色，先跑通 |
| B（备用） | `CosyVoice2-0.5B` | 音质更好；改 `.env` 的 `TTS_PROFILE=B` 后重启 FastAPI，再 launch B。页面和路由不用改 |

CosyVoice 首次下载需要外网，磁盘建议再预留数 GB；模型仍进已有 `XINFERENCE_HOME`。B 未 launch 时，`GET /api/v1/tts/health` 会标 `launched: false`，`POST /speech` 返回明确错误，不会空响应。

读法表在 `backend/data/tts_readings.yaml`（`RAG` → `R A G` 等），按 mtime 热更新，与 ASR 谐音表方向相反，不要混用。

验证：

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/tts/speech" ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"打开知识库搜索。\"}" ^
  --output tts-check.mp3
```

## 本机踩坑（已处理）

- 默认 `python` 是 3.6，不能用。本仓库使用 `D:\Users\Worker\Program\services\python312`。
- 新版 NumPy 2.5 需要 X86_V2 指令集，本机 CPU 不支持。`.venv-xinf` 必须钉 `numpy==2.1.3`、`scipy==1.14.1`。
- FunASR 会调系统 `ffmpeg`，启动 Xinference 前要把 `D:\Users\Worker\Program\services\ffmpeg\bin` 加进 PATH。
- Windows 上 Xinference 默认用 `NamedTemporaryFile` 会导致识别 WinError 2，已在 `.venv-xinf` 里改成先落盘再识别。
- 关掉 `XINFERENCE_ENABLE_VIRTUAL_ENV`，避免再装一份会拉高指令集 NumPy 的模型环境。
- CosyVoice 不在 `xinference[transformers]` 里。`.venv-xinf` 按 `backend/requirements-xinf.txt` 补齐。缺依赖或内存不够时，CLI 仍可能报 100% 并给出 UID，但 `xinference list` 没有 TTS；页面上的「合成超时」多半是模型没真正起来，不是文本太长。
- 同一 ASR 只保留一份。旧版合并脚本误判「未启动」会再 launch 一次，Xinference 会生成 `seaco-paraformer-zh-随机后缀`。两份 ASR + CosyVoice 很容易把本机打满，加载卡死。
- 需要优化合成语音速度