<template>
  <div class="voice-input">
    <textarea
      class="voice-input__prompt"
      :value="modelValue"
      rows="6"
      placeholder="按住或点击麦克风说话，识别结果会回填到这里，可继续编辑"
      @input="emitText($event.target.value)"
    />
    <div class="voice-input__bar">
      <button
        type="button"
        class="voice-input__mic"
        :class="{ 'is-recording': recording, 'is-busy': loading }"
        :disabled="loading"
        @mousedown.prevent="startHold"
        @mouseup.prevent="stopHold"
        @mouseleave="stopHold"
        @touchstart.prevent="startHold"
        @touchend.prevent="stopHold"
        @click.prevent="toggleClick"
      >
        {{ buttonLabel }}
      </button>
      <span v-if="status" class="voice-input__status">{{ status }}</span>
    </div>
    <p v-if="error" class="voice-input__error">{{ error }}</p>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from "vue";

const props = defineProps({
  modelValue: { type: String, default: "" },
  apiUrl: { type: String, default: "/api/v1/asr/transcribe" },
});

const emit = defineEmits(["update:modelValue", "transcribed"]);

const recording = ref(false);
const loading = ref(false);
const holdMode = ref(false);
const status = ref("");
const error = ref("");
let mediaStream = null;
let recorder = null;
let chunks = [];

const buttonLabel = computed(() => {
  if (loading.value) return "识别中…";
  if (recording.value) return holdMode.value ? "松开结束" : "点击结束";
  return "按住说话 / 点击录音";
});

function emitText(text) {
  emit("update:modelValue", text);
}

function resolveMimeType() {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  if (typeof MediaRecorder === "undefined") return "";
  return candidates.find((item) => MediaRecorder.isTypeSupported(item)) || "";
}

function cleanupStream() {
  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
  }
  recorder = null;
}

async function startRecording(isHold) {
  error.value = "";
  if (recording.value || loading.value) return;
  if (!window.isSecureContext) {
    error.value = "当前页面不是安全上下文，请用 http://localhost 或 HTTPS 打开";
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    error.value = "当前浏览器不支持录音";
    return;
  }
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
    },
  });
  mediaStream = stream;
  chunks = [];
  const mimeType = resolveMimeType();
  recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  recorder.ondataavailable = (event) => {
    if (event.data && event.data.size > 0) chunks.push(event.data);
  };
  recorder.onerror = () => {
    error.value = "语音录制失败，请重试";
    cleanupStream();
    recording.value = false;
  };
  recorder.onstop = () => {
    const blob = new Blob(chunks, { type: recorder?.mimeType || mimeType || "audio/webm" });
    cleanupStream();
    recording.value = false;
    holdMode.value = false;
    if (!blob.size) {
      error.value = "未录到语音内容";
      status.value = "";
      return;
    }
    void uploadBlob(blob);
  };
  recorder.start();
  recording.value = true;
  holdMode.value = isHold;
  status.value = isHold ? "正在录音，松开结束" : "正在录音，再次点击结束";
}

function stopRecording() {
  if (recorder && recorder.state === "recording") {
    recorder.stop();
  }
}

async function startHold() {
  holdMode.value = true;
  try {
    await startRecording(true);
  } catch (err) {
    error.value = normalizeCaptureError(err);
    cleanupStream();
  }
}

function stopHold() {
  if (holdMode.value && recording.value) {
    stopRecording();
  }
}

async function toggleClick() {
  if (holdMode.value) return;
  if (recording.value) {
    stopRecording();
    return;
  }
  try {
    await startRecording(false);
  } catch (err) {
    error.value = normalizeCaptureError(err);
    cleanupStream();
  }
}

async function uploadBlob(blob) {
  loading.value = true;
  status.value = "正在识别…";
  try {
    const form = new FormData();
    form.append("file", blob, "voice.webm");
    const response = await fetch(props.apiUrl, { method: "POST", body: form });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || "语音识别失败，请重试或手动输入");
    }
    const text = String(payload.text || "").trim();
    emitText(text);
    emit("transcribed", payload);
    status.value = text ? `识别完成（${payload.cost_ms || 0}ms）` : "识别完成，但文本为空";
  } catch (err) {
    error.value = err instanceof Error ? err.message : "语音识别失败，请重试或手动输入";
    status.value = "";
  } finally {
    loading.value = false;
  }
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
  return err instanceof Error ? err.message : "无法开始录音";
}

onBeforeUnmount(() => {
  stopRecording();
  cleanupStream();
});
</script>

<style scoped>
.voice-input {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.voice-input__prompt {
  width: 100%;
  box-sizing: border-box;
  padding: 12px;
  border: 1px solid #d8dce3;
  border-radius: 10px;
  font: inherit;
  line-height: 1.6;
  resize: vertical;
}

.voice-input__bar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.voice-input__mic {
  border: 0;
  border-radius: 999px;
  padding: 10px 16px;
  background: #2f6fed;
  color: #fff;
  cursor: pointer;
}

.voice-input__mic.is-recording {
  background: #d4380d;
}

.voice-input__mic.is-busy,
.voice-input__mic:disabled {
  opacity: 0.7;
  cursor: wait;
}

.voice-input__status {
  color: #5b6472;
  font-size: 13px;
}

.voice-input__error {
  margin: 0;
  color: #c0392b;
  font-size: 13px;
}
</style>
