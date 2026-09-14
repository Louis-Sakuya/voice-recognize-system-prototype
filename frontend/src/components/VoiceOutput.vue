<template>
  <div class="voice-output">
    <div class="voice-output__bar">
      <button
        type="button"
        class="voice-output__speak"
        :class="{ 'is-busy': loading }"
        :disabled="loading || !canSpeak"
        @click.prevent="speak"
      >
        {{ speakLabel }}
      </button>
      <button
        type="button"
        class="voice-output__stop"
        :disabled="!playing && !loading"
        @click.prevent="stop"
      >
        停止
      </button>
      <span v-if="status" class="voice-output__status">{{ status }}</span>
    </div>
    <p v-if="error" class="voice-output__error">{{ error }}</p>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from "vue";

const props = defineProps({
  text: { type: String, default: "" },
  apiUrl: { type: String, default: "/api/v1/tts/speech" },
  autoPlay: { type: Boolean, default: false },
});

const emit = defineEmits(["started", "ended", "error", "ready"]);

const loading = ref(false);
const playing = ref(false);
const status = ref("");
const error = ref("");
let player = null;
let playToken = 0;

const canSpeak = computed(() => Boolean(String(props.text || "").trim()));
const speakLabel = computed(() => {
  if (loading.value) return "合成中…";
  if (playing.value) return "朗读中…";
  return "朗读";
});

function detailFromPayload(payload, status) {
  const detail = payload && payload.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail) && detail[0] && detail[0].msg) return String(detail[0].msg);
  if (status) return `语音合成失败（HTTP ${status}）`;
  return "";
}

function stopPlayer() {
  if (player) {
    player.onended = null;
    player.onerror = null;
    player.pause();
    player.src = "";
    player = null;
  }
}

function stop() {
  playToken += 1;
  loading.value = false;
  playing.value = false;
  stopPlayer();
  if (status.value === "合成中…" || status.value.startsWith("朗读中")) {
    status.value = "已停止";
  }
}

function playBlob(blob) {
  return new Promise((resolve, reject) => {
    stopPlayer();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    player = audio;
    audio.onended = () => {
      URL.revokeObjectURL(url);
      if (player === audio) player = null;
      resolve();
    };
    audio.onerror = () => {
      URL.revokeObjectURL(url);
      if (player === audio) player = null;
      reject(new Error("音频播放失败"));
    };
    audio.play().catch((err) => {
      URL.revokeObjectURL(url);
      if (player === audio) player = null;
      reject(err instanceof Error ? err : new Error("音频播放失败"));
    });
  });
}

async function fetchSpeech(sentence) {
  const response = await fetch(props.apiUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: sentence }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(detailFromPayload(payload, response.status) || "语音合成失败，请稍后重试");
  }
  const blob = await response.blob();
  if (!blob.size) throw new Error("语音合成为空");
  return {
    blob,
    profile: response.headers.get("X-TTS-Profile") || "",
    model: response.headers.get("X-TTS-Model") || "",
    costMs: Number(response.headers.get("X-TTS-Cost-Ms") || 0),
    mime: blob.type || "audio/mpeg",
  };
}

async function speak() {
  const source = String(props.text || "").trim();
  if (!source || loading.value || playing.value) return;
  const token = playToken + 1;
  playToken = token;
  error.value = "";
  loading.value = true;
  playing.value = true;
  status.value = "合成中…";
  emit("started");
  try {
    const item = await fetchSpeech(source);
    if (playToken !== token) return;
    loading.value = false;
    status.value = "朗读中…";
    emit("ready", { blob: item.blob, profile: item.profile, model: item.model, mime: item.mime, costMs: item.costMs });
    await playBlob(item.blob);
    if (playToken !== token) return;
    status.value = item.profile ? `朗读完成（${item.profile} · ${item.costMs || 0}ms）` : `朗读完成（${item.costMs || 0}ms）`;
    emit("ended");
  } catch (err) {
    if (playToken !== token) return;
    const message = err instanceof Error ? err.message : "语音合成失败，请稍后重试";
    error.value = message;
    status.value = "";
    emit("error", message);
  } finally {
    if (playToken === token) {
      loading.value = false;
      playing.value = false;
      stopPlayer();
    }
  }
}

onBeforeUnmount(() => {
  stop();
});

if (props.autoPlay) {
  void speak();
}
</script>

<style scoped>
.voice-output__bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.voice-output__speak,
.voice-output__stop {
  border: 0;
  border-radius: 999px;
  padding: 10px 16px;
  cursor: pointer;
}

.voice-output__speak {
  background: #2f6fed;
  color: #fff;
}

.voice-output__stop {
  background: #eef2f7;
  color: #1a1b1c;
}

.voice-output__speak.is-busy,
.voice-output__speak:disabled,
.voice-output__stop:disabled {
  opacity: 0.7;
  cursor: wait;
}

.voice-output__status {
  color: #5b6472;
  font-size: 13px;
}

.voice-output__error {
  margin: 8px 0 0;
  color: #c0392b;
  font-size: 13px;
}
</style>
