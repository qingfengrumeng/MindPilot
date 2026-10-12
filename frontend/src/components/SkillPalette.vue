<script setup>

/**
 * 输入框里的「/」能力面板：列出同一会话中可用的全部能力。
 * 键盘上下与回车由调用方在输入框上接管，这里只负责把高亮行和选中事件报回去。
 */
defineProps({
  groups: { type: Array, default: () => [] },
  index: { type: Number, default: 0 },
  total: { type: Number, default: 0 }
})
const emit = defineEmits(['pick', 'hover'])
</script>

<template>
  <div class="assistant-skill-palette" role="listbox" aria-label="选择能力">
    <div class="assistant-skill-scroll">
      <template v-for="group in groups" :key="group.id">
        <p class="assistant-skill-group">{{ group.label }}<small>({{ group.items.length }})</small></p>
        <button
          v-for="item in group.items"
          :key="item.id"
          type="button"
          role="option"
          :aria-selected="index === item.flatIndex"
          :class="{ highlighted: index === item.flatIndex }"
          @mouseenter="emit('hover', item.flatIndex)"
          @click="emit('pick', item)"
        >
          <span class="assistant-skill-tag"><component :is="item.icon" :size="20" />{{ item.label }}</span>
          <span class="assistant-skill-sample">{{ item.description }}</span>
        </button>
      </template>
      <p v-if="!total" class="assistant-skill-empty">没有匹配的能力，换个关键词试试</p>
    </div>

  </div>
</template>
