const SPEECH_RMS = 0.02;
const SILENCE_FINAL_MS = 2000;

export function createVoiceSession(hooks = {}) {
  const healthUrl = hooks.healthUrl || "/api/v1/voice/health";
  const streamPath = hooks.streamPath || "/api/v1/voice/stream";
  const workletUrl = hooks.workletUrl || "/static/pcm-worklet.js";
  let health = { ready: false, provider: "", model: "", reason: "正在检查语音服务…" };
  let active = false;
  let starting = false;
  let generation = 0;
  let ws = null;
  let audioContext = null;
  let mediaStream = null;
  let workletNode = null;
  let sourceNode = null;
  let serverReady = false;
  let speaking = false;
  let silenceMs = 0;

  function emitStatus(text) {
    if (hooks.onStatus) hooks.onStatus(text);
  }

  function emitError(text) {
    if (hooks.onError) hooks.onError(text || "");
  }

  function wsUrl() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${location.host}${streamPath}`;
  }

  async function refreshHealth() {
    try {
      const response = await fetch(healthUrl);
      const payload = await response.json();
      health = {
        ready: Boolean(payload.ready),
        provider: String(payload.provider || ""),
        model: String(payload.model || ""),
        reason: String(payload.reason || ""),
      };
    } catch (err) {
      health = {
        ready: false,
        provider: "",
        model: "",
        reason: err instanceof Error ? err.message : "无法读取语音服务状态",
      };
    }
    if (hooks.onHealth) hooks.onHealth(health);
    emitError(health.ready ? "" : health.reason);
    return health;
  }

  async function teardown(token) {
    serverReady = false;
    speaking = false;
    silenceMs = 0;
    if (workletNode) {
      workletNode.port.onmessage = null;
      workletNode.disconnect();
      workletNode = null;
    }
    if (sourceNode) {
      sourceNode.disconnect();
      sourceNode = null;
    }
    if (audioContext) {
      const context = audioContext;
      audioContext = null;
      try {
        await context.close();
      } catch (err) {
        /* 关闭音频上下文失败时继续释放麦克风 */
      }
    }
    if (mediaStream) {
      mediaStream.getTracks().forEach((track) => track.stop());
      mediaStream = null;
    }
    if (ws) {
      const socket = ws;
      ws = null;
      socket.onopen = null;
      socket.onmessage = null;
      socket.onerror = null;
      socket.onclose = null;
      if (socket.readyState === WebSocket.OPEN) {
        try {
          socket.send(JSON.stringify({ type: "stop" }));
        } catch (err) {
          /* 通道已不可写 */
        }
      }
      socket.close();
    }
    if (token === generation) {
      active = false;
      starting = false;
      if (hooks.onActive) hooks.onActive(false);
    }
  }

  function onPcm(event) {
    if (!serverReady || !ws || ws.readyState !== WebSocket.OPEN) return;
    const rms = Number(event.data.rms || 0);
    if (rms >= SPEECH_RMS) {
      speaking = true;
      silenceMs = 0;
      emitStatus("正在说话");
    } else if (speaking) {
      silenceMs += 200;
      if (silenceMs >= SILENCE_FINAL_MS) {
        speaking = false;
        silenceMs = 0;
        emitStatus("等待说话");
      }
    }
    if (event.data.pcm) ws.send(event.data.pcm.buffer);
  }

  function normalizeCaptureError(err) {
    const name = err && typeof err === "object" ? String(err.name || "") : "";
    if (name === "NotAllowedError" || name === "PermissionDeniedError") {
      return "浏览器未授权麦克风，请在地址栏权限中允许录音后重试";
    }
    if (name === "NotFoundError" || name === "DevicesNotFoundError") {
      return "未检测到可用麦克风设备";
    }
    if (name === "NotReadableError" || name === "TrackStartError") {
      return "麦克风当前不可用，可能被其他应用占用";
    }
    if (name === "SecurityError") {
      return "当前页面安全策略禁止录音，请改用 HTTPS 或 localhost 访问";
    }
    return err instanceof Error ? err.message : "无法开启语音";
  }

  async function start() {
    if (active || starting) return;
    emitError("");
    if (!health.ready) {
      emitError(health.reason || "语音服务不可用");
      return;
    }
    if (!window.isSecureContext) {
      emitError("当前页面不是安全上下文，请用 http://localhost 或 HTTPS 打开");
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
      emitError("当前浏览器不支持音频采集");
      return;
    }
    const token = generation;
    starting = true;
    emitStatus("连接中…");
    const context = new AudioContext();
    audioContext = context;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      if (token !== generation) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      mediaStream = stream;
      const socket = new WebSocket(wsUrl());
      socket.binaryType = "arraybuffer";
      ws = socket;
      const opened = new Promise((resolve, reject) => {
        socket.onopen = () => resolve();
        socket.onerror = () => reject(new Error("语音通道连接失败"));
      });
      socket.onmessage = (event) => {
        if (token !== generation) return;
        let data = null;
        try {
          data = JSON.parse(event.data);
        } catch (err) {
          return;
        }
        if (data.type === "ready") {
          serverReady = true;
          active = true;
          starting = false;
          if (hooks.onActive) hooks.onActive(true);
          emitStatus("等待说话");
        } else if (data.type === "partial") {
          if (hooks.onPartial) hooks.onPartial(String(data.text || ""));
        } else if (data.type === "final") {
          if (hooks.onFinal) hooks.onFinal(String(data.text || ""));
          if (hooks.onPartial) hooks.onPartial("");
        } else if (data.type === "error") {
          emitError(data.message || "语音识别失败");
          generation += 1;
          void teardown(generation);
          emitStatus("");
        }
      };
      socket.onclose = () => {
        if (token !== generation) return;
        if (!active && !starting) return;
        emitError("语音通道已断开");
        generation += 1;
        void teardown(generation);
        emitStatus("");
      };
      await opened;
      if (token !== generation) return;
      socket.send(JSON.stringify({ type: "start" }));
      await context.resume();
      await context.audioWorklet.addModule(workletUrl);
      if (token !== generation) return;
      sourceNode = context.createMediaStreamSource(stream);
      workletNode = new AudioWorkletNode(context, "pcm-capture");
      workletNode.port.onmessage = onPcm;
      sourceNode.connect(workletNode);
    } catch (err) {
      if (token !== generation) return;
      emitError(normalizeCaptureError(err));
      generation += 1;
      await teardown(generation);
      emitStatus("");
    }
  }

  async function stop() {
    if (!active && !starting && !ws && !audioContext) return;
    generation += 1;
    await teardown(generation);
    emitStatus("已关闭");
    emitError(health.ready ? "" : health.reason);
  }

  async function toggle() {
    if (active || starting) await stop();
    else await start();
  }

  return {
    refreshHealth,
    toggle,
    stop,
    get active() {
      return active;
    },
    get starting() {
      return starting;
    },
  };
}
