<script setup lang="ts">
import { inject, onMounted, ref } from "vue";
import type { Character } from "../../types";
import CharacterList from "../CharacterList.vue";

const charListRef = ref<any>(null);
const registerTask = inject<
  (order: number, name: string, fn: () => Promise<boolean>) => void
>("registerTask", () => {});

onMounted(() => {
  registerTask(30, "RTA每周", async () => {
    const list = charListRef.value;
    const ch = characters.find((c) => c.id === list?.selected);
    if (!ch) return true;
    const api = window.pywebview?.api as any;
    if (!api) return false;
    for (let i = 0; i < ch.totalCount; i++) {
      const ok = await api.run_rta_weekly(ch.name, ch.difficulty, ch.streak);
      if (!ok) return false;
    }
    return true;
  });
});

const characters: Character[] = [
  {
    id: "rta_weekly",
    name: "RTA每周",
    difficulty: "普通",
    streak: 1,
    totalCount: 1,
  },
];
</script>

<template>
  <CharacterList
    ref="charListRef"
    title="rta_weekly"
    :characters="characters"
    :show-difficulty="false"
    :show-total-count="false"
    :show-stamina="false"
    :stamina-per-battle="0"
    :max-count="99"
  />
</template>
