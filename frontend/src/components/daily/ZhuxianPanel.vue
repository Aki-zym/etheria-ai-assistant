<script setup lang="ts">
import { inject, onMounted, ref, type Ref } from "vue";
import type { RunStatus } from "../../types";

const addLog = inject<(msg: string) => void>("addLog")!;
const status = inject<Ref<RunStatus>>("status")!;
const registerTask = inject<
  (order: number, name: string, fn: () => Promise<boolean>) => void
>("registerTask", () => {});

const enabled = ref(false);
const stopStage = ref("4-7");
const fromHome = ref(true);
const usePotion = ref(false);

function getApi() {
  return window.pywebview?.api as any;
}

async function runOnce(): Promise<boolean> {
  const api = getApi();
  if (!api) return false;
  return api.run_zhuxian_battle(
    stopStage.value,
    "",
    1,
    stopStage.value,
    fromHome.value,
    usePotion.value,
  );
}

onMounted(() => {
  registerTask(12, "主线", async () => {
    if (!enabled.value) return true;
    return runOnce();
  });
});

async function start() {
  if (status.value.busy) return;
  if (!/^\d+\s*[-—]\s*\d+$/.test(stopStage.value.trim())) {
    addLog("停止关格式应为 4-7");
    return;
  }
  status.value = { running: true, busy: true };
  addLog(`主线开始 → 打到 ${stopStage.value}`);
  try {
    const ok = await runOnce();
    addLog(ok ? "主线完成" : "主线失败");
  } catch (e: any) {
    addLog(`主线异常: ${e}`);
  }
  status.value = { running: false, busy: false };
}

async function stopTask() {
  const api = getApi();
  if (!api) return;
  await api.stop_task();
  status.value = { running: false, busy: false };
  addLog("已请求停止");
}
</script>

<template>
  <div class="zhuxian-root">
    <label class="row">
      <input type="checkbox" v-model="enabled" class="check" />
      <span class="name">自动推主线</span>
      <div class="field">
        <label class="fl">打到</label>
        <input
          type="text"
          v-model="stopStage"
          class="stage"
          placeholder="4-7"
        />
      </div>
      <label class="opt">
        <input type="checkbox" v-model="usePotion" class="check" />
        体力不足自动兑换
      </label>
      <label class="from-home">
        <input type="checkbox" v-model="fromHome" class="check" />
        从主界面进入
      </label>
    </label>
    <p class="hint-text">
      从主界面点挑战 → 主线 → 当前章节，按 NEW 节点推进。剧情自动跳过，打完停止关结束。勾上自动兑换时，稳定值弹窗会点红色「兑换稳定值」。后面章节把「打到」改成 5-7 即可。
    </p>
    <div class="start-area">
      <button class="btn btn-primary" @click="start" :disabled="status.busy">
        {{ status.busy ? "执行中..." : "▶ 开始执行" }}
      </button>
      <button class="btn btn-danger" @click="stopTask" :disabled="!status.running">
        停止
      </button>
    </div>
  </div>
</template>

<style scoped>
.row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  background: #f8f9fa;
  border-radius: 10px;
  cursor: pointer;
}
.check {
  width: 18px;
  height: 18px;
  accent-color: #8b5cf6;
  cursor: pointer;
}
.name {
  font-size: 15px;
  font-weight: 600;
  color: #333;
}
.field {
  display: flex;
  align-items: center;
  gap: 6px;
}
.fl {
  font-size: 13px;
  color: #666;
}
.stage {
  width: 72px;
  padding: 6px 10px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 13px;
  text-align: center;
  outline: none;
}
.stage:focus {
  border-color: #8b5cf6;
}
.opt {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #666;
  cursor: pointer;
}
.from-home {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #666;
  cursor: pointer;
}
.hint-text {
  margin: 12px 4px 0;
  font-size: 12px;
  color: #888;
  line-height: 1.5;
}
.start-area {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 20px;
}
.btn {
  padding: 10px 20px;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn-primary {
  background: #8b5cf6;
  color: white;
}
.btn-primary:hover:not(:disabled) {
  background: #7c3aed;
}
.btn-danger {
  background: #ef4444;
  color: white;
}
</style>
