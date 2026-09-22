<template>
  <div class="voice-input">
    <div class="voice-input__bar">
      <button
        type="button"
        class="voice-input__mic"
        :class="{ 'is-on': active }"
        :disabled="!health.ready && !active && !starting"
        @click="toggle"
      >
        {{ buttonLabel }}
      </button>
      <span v-if="status" class="voice-input__status">{{ status }}</span>
    </div>
    <p v-if="error" class="voice-input__error">{{ error }}</p>
    <p class="voice-input__partial" :class="{ 'is-empty': !partial }">{{ partial || "当前句会显示在这里" }}</p>
    <ul v-if="finals.length" class="voice-input__finals">
      <li v-for="(line, index) in finals" :key="index">{{ line }}</li>
    </ul>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { createVoiceSession } from "../../voice-session.js";

const props = defineProps({
  modelValue: { type: String, default: "" },
  healthUrl: { type: String, default: "/api/v1/voice/health" },
  streamPath: { type: String, default: "/api/v1/voice/stream" },
  workletUrl: { type: String, default: "/static/pcm-worklet.js" },
});

const emit = defineEmits(["update:modelValue", "partial", "final"]);

const health = ref({ ready: false, provider: "", model: "", reason: "正在检查语音服务…" });
const active = ref(false);
const starting = ref(false);
const status = ref("");
const error = ref("");
const partial = ref("");
const finals = ref(
  props.modelValue
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean),
);

const session = createVoiceSession({
  healthUrl: props.healthUrl,
  streamPath: props.streamPath,
  workletUrl: props.workletUrl,
  onHealth(next) { health.value = next; },
  onActive(on) {
    active.value = on;
    starting.value = false;
  },
  onStatus(text) {
    status.value = text;
    starting.value = text === "连接中…";
  },
  onError(text) { error.value = text; },
  onPartial(text) {
    partial.value = text;
    emit("partial", text);
  },
  onFinal(text) {
    if (!text) return;
    finals.value = finals.value.concat(text);
    partial.value = "";
    emit("final", text);
    emit("update:modelValue", finals.value.join("\n"));
  },
});

const buttonLabel = computed(() => {
  if (starting.value) return "连接中…";
  if (active.value) return "关闭语音";
  return "开启语音";
});

function toggle() {
  void session.toggle();
}

onMounted(() => {
  void session.refreshHealth();
});

onBeforeUnmount(() => {
  void session.stop();
});
</script>

<style scoped>
.voice-input {
  display: flex;
  flex-direction: column;
  gap: 12px;
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

.voice-input__mic.is-on {
  background: #d4380d;
}

.voice-input__mic:disabled {
  opacity: 0.55;
  cursor: not-allowed;
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

.voice-input__partial {
  margin: 0;
  padding: 12px;
  border-radius: 10px;
  background: #f7f8fb;
  line-height: 1.6;
}

.voice-input__partial.is-empty {
  color: #9aa1ab;
}

.voice-input__finals {
  margin: 0;
  padding-left: 18px;
  line-height: 1.7;
}
</style>
