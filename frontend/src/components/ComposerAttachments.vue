<script setup>
import { FileText, Image as ImageIcon, LoaderCircle, X } from 'lucide-vue-next'

defineProps({ files: { type: Array, default: () => [] } })
const emit = defineEmits(['preview', 'remove'])
</script>

<template>
  <div v-if="files.length" class="composer-attachments" aria-label="待发送附件">
    <div v-for="file in files" :key="file.localId" class="composer-attachment">
      <button type="button" class="composer-attachment-preview" :aria-label="`查看 ${file.name}`" @click="emit('preview', file)">
        <span class="composer-attachment-icon">
          <img v-if="file.type === 'image' && file.previewUrl" :src="file.previewUrl" alt="" />
          <ImageIcon v-else-if="file.type === 'image'" :size="22" />
          <FileText v-else :size="22" />
        </span>
        <span class="composer-attachment-details">
          <strong :title="file.name">{{ file.name }}</strong>
          <small>{{ file.uploading ? '正在添加…' : file.size }}</small>
        </span>
      </button>
      <LoaderCircle v-if="file.uploading" class="composer-attachment-loading" :size="15" />
      <button type="button" class="composer-attachment-remove" :aria-label="`移除 ${file.name}`" @click="emit('remove', file.localId)"><X :size="15" /></button>
    </div>
  </div>
</template>

<style scoped>
.composer-attachments{display:flex;gap:9px;max-width:100%;overflow-x:auto;padding:9px 2px 12px;scrollbar-width:thin}
.composer-attachment{display:flex;align-items:center;flex:0 0 auto;min-width:0;max-width:235px;padding:5px 6px;border:1px solid #daccec;border-radius:12px;background:#f8f4fc;box-shadow:0 3px 10px rgba(69,34,112,.055)}
.composer-attachment-preview{display:flex;align-items:center;gap:9px;min-width:0;padding:0;border:0;background:transparent;color:#3f295b;text-align:left;cursor:pointer}
.composer-attachment-icon{display:grid;place-items:center;flex:none;width:42px;height:42px;overflow:hidden;border-radius:9px;background:#e7dcf5;color:#4d0aa0}
.composer-attachment-icon img{width:100%;height:100%;object-fit:cover}
.composer-attachment-details{display:grid;gap:2px;min-width:0}
.composer-attachment-details strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;font-weight:700}
.composer-attachment-details small{color:#7d669a;font-size:11px;white-space:nowrap}
.composer-attachment-loading{flex:none;margin:0 5px;color:#5817a8;animation:spin 1s linear infinite}
.composer-attachment-remove{display:grid;place-items:center;flex:none;width:24px;height:24px;margin-left:5px;border:0;border-radius:7px;background:transparent;color:#7f6b97;cursor:pointer}
.composer-attachment-remove:hover{background:#ebe3f5;color:#b74456}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
