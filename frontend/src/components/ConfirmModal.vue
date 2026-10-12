<script setup>
import { AlertTriangle, X } from 'lucide-vue-next'

defineProps({
  open: Boolean,
  title: String,
  message: String,
  subject: String,
  subjectLabel: { type: String, default: '即将删除' },
  confirmText: { type: String, default: '确认' },
  danger: Boolean
})

defineEmits(['confirm', 'cancel'])
</script>

<template>
  <Transition name="modal">
    <div v-if="open" class="modal-mask" @click.self="$emit('cancel')">
      <section class="modal-card confirm-card" role="alertdialog" aria-modal="true">
        <button class="icon-btn modal-close" type="button" aria-label="关闭" @click="$emit('cancel')">
          <X :size="19" />
        </button>
        <span class="confirm-icon" :class="{ danger }">
          <AlertTriangle :size="25" />
        </span>
        <div class="confirm-copy">
          <h3>{{ title }}</h3>
          <p>{{ message }}</p>
        </div>
        <div v-if="subject" class="confirm-subject">
          <span>{{ subjectLabel }}</span>
          <strong :title="subject">{{ subject }}</strong>
        </div>
        <div class="modal-actions">
          <button class="btn secondary" type="button" @click="$emit('cancel')">取消</button>
          <button class="btn" :class="{ danger }" type="button" @click="$emit('confirm')">
            {{ confirmText }}
          </button>
        </div>
      </section>
    </div>
  </Transition>
</template>
