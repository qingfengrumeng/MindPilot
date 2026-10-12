<script setup>
import { computed, onMounted, ref } from 'vue'
import { X } from 'lucide-vue-next'
import { SKILL_GUIDES } from '@/skillGuides'

const props = defineProps({ skill: { type: Object, required: true } })
const emit = defineEmits(['close'])
const dialog = ref()
const guide = computed(() => SKILL_GUIDES[props.skill.id])
function close() { dialog.value?.close() }
onMounted(() => dialog.value.showModal())
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="skill-info-dialog" aria-labelledby="skill-info-title" aria-describedby="skill-info-description" @close="emit('close')" @click.self="close">
      <article class="skill-info-content">
        <button class="skill-info-close" type="button" aria-label="关闭功能说明" autofocus @click="close"><X :size="22" /></button>
        <header class="skill-info-header">
          <span class="skill-info-icon"><component :is="skill.icon" :size="30" :stroke-width="1.7" /></span>
          <h2 id="skill-info-title">{{ skill.label }}</h2>
          <p id="skill-info-description">{{ skill.description }}</p>
        </header>
        <div v-if="guide" class="skill-info-sections">
          <section>
            <h3>功能介绍</h3>
            <p>{{ guide.about }}</p>
          </section>
          <section>
            <h3>提示词怎么写</h3>
            <p>{{ guide.prompt }}</p>
            <div class="skill-info-example"><span>试着这样说</span><p>{{ skill.example }}</p></div>
          </section>
          <section>
            <h3>你会得到什么</h3>
            <p>{{ guide.result }}</p>
          </section>
          <section>
            <h3>继续追加需求</h3>
            <p>{{ guide.followup }}</p>
            <div class="skill-info-followup">“{{ guide.revision }}”</div>
          </section>
        </div>
      </article>
    </dialog>
  </Teleport>
</template>

<style scoped>
.skill-info-dialog{width:min(640px,calc(100vw - 40px));max-height:min(820px,calc(100dvh - 64px));margin:auto;padding:0;overflow:auto;overscroll-behavior:contain;border:1px solid #e9eaee;border-radius:24px;background:#fff;color:#202124;box-shadow:0 24px 90px #28183b26;text-align:left}
.skill-info-dialog::backdrop{background:rgba(32,25,40,.25);backdrop-filter:blur(3px)}
.skill-info-content{position:relative;padding:32px}
.skill-info-close{position:absolute;top:20px;right:20px;display:grid;place-items:center;width:34px;height:34px;border:0;border-radius:50%;color:#85878c;background:transparent;cursor:pointer}
.skill-info-close:hover{background:#f2f3f5;color:#202124}
.skill-info-close:focus-visible{outline:2px solid #5310a6;outline-offset:3px}
.skill-info-icon{display:grid;place-items:center;width:62px;height:62px;border:1px solid #ece2f9;border-radius:50%;background:#f8f3ff;color:#5310a6}
.skill-info-header h2{margin:18px 0 6px;font-size:24px;font-weight:650;line-height:1.4}
.skill-info-header>p{margin:0;color:#868990;font-size:14px;line-height:1.7}
.skill-info-sections{margin-top:26px;padding:0 24px;border:1px solid #e6e7eb;border-radius:16px;background:#fafafa}
.skill-info-sections section{padding:22px 0}
.skill-info-sections section+section{border-top:1px solid #e9eaee}
.skill-info-sections h3{margin:0 0 9px;color:#22252a;font-size:16px;font-weight:600;line-height:1.5}
.skill-info-sections p{margin:0;color:#62666e;font-size:14px;line-height:1.85;overflow-wrap:anywhere}
.skill-info-example{margin-top:14px;padding:14px 16px;border:1px solid #ebe6f2;border-radius:10px;background:#fff}
.skill-info-example>span{display:block;margin-bottom:6px;color:#8a919e;font-size:12px}
.skill-info-example p{color:#343b47}
.skill-info-followup{margin-top:10px;padding-left:12px;border-left:2px solid #d1b8f0;color:#5d437c;font-size:14px;line-height:1.8}
@media(max-width:600px){.skill-info-dialog{width:calc(100vw - 24px);max-height:calc(100dvh - 32px);border-radius:20px}.skill-info-content{padding:24px 20px}.skill-info-sections{padding:0 16px}.skill-info-header h2{font-size:22px}}
</style>
