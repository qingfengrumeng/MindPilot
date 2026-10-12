<script setup>
import {computed,onBeforeUnmount,ref,watch} from 'vue'
import {Check,LoaderCircle,Pause,Volume2} from 'lucide-vue-next'
import ModelNameSelect from './ModelNameSelect.vue'

const props=defineProps({id:String,modelValue:String,model:String,voices:{type:Array,default:()=>[]},previewRequest:Function,placeholder:String,disabled:Boolean})
const emit=defineEmits(['update:modelValue'])
const byId=computed(()=>Object.fromEntries(props.voices.map(voice=>[voice.id,voice])))
const options=computed(()=>props.voices.map(voice=>voice.id))
const labels=computed(()=>Object.fromEntries(props.voices.map(voice=>[voice.id,`${voice.name||''} ${voice.description||''}`])))
const playing=ref(''),loading=ref(''),error=ref('')
let audio=null,version=0,controller=null,objectUrl=null
function stop(){version++;controller?.abort();controller=null;if(audio){audio.pause();audio.onended=null;audio.onerror=null;audio.removeAttribute('src');audio.load();audio=null}if(objectUrl){URL.revokeObjectURL(objectUrl);objectUrl=null}playing.value='';loading.value=''}
async function preview(voice){
  if(playing.value===voice.id || loading.value===voice.id){stop();return}
  stop();error.value=''
  if(!voice.previewUrl&&!props.previewRequest)return
  const epoch=version
  loading.value=voice.id
  try{
    let source=voice.previewUrl
    if(!source){
      controller=new AbortController()
      const blob=await props.previewRequest(voice,controller.signal)
      if(epoch!==version)return
      source=URL.createObjectURL(blob);objectUrl=source
    }
    const player=new Audio(source);audio=player
    player.onended=()=>{if(epoch===version)stop()}
    player.onerror=()=>{if(epoch===version){stop();error.value='试听音频暂时无法播放，请重试。'}}
    await player.play();if(epoch===version){loading.value='';playing.value=voice.id}
  }
  catch{if(epoch===version){stop();error.value='试听音频暂时无法播放，请重试。'}}
}
watch(()=>[props.model,props.voices,props.disabled],()=>{stop();error.value=''})
onBeforeUnmount(stop)
</script>
<template>
  <ModelNameSelect :id="id" :model-value="modelValue" :options="options" :option-labels="labels" :placeholder="placeholder||'音色名称或 ID'" search-placeholder="搜索名称或输入音色 ID" list-label="可用音色" wide :disabled="disabled" @update:model-value="emit('update:modelValue',$event)" @open-change="value=>{if(!value)stop()}">
    <template #option="{optionName:name,index,choose,selected,highlighted,optionId}">
      <div :id="optionId" class="voice-option" :class="{selected,highlighted}" role="option" :aria-selected="selected" :data-index="index">
        <button class="voice-choice" type="button" @pointerdown.prevent @click="choose(name)"><span>{{byId[name]?.name||name}}<template v-if="byId[name]?.name && byId[name].name!==name"> · {{name}}</template></span><small v-if="byId[name]?.description">{{byId[name].description}}</small></button>
        <Check v-if="selected" :size="18" class="voice-check"/>
        <button class="voice-preview" :class="{playing:playing===name}" type="button" :disabled="!byId[name]?.previewUrl&&!previewRequest" :title="byId[name]?.previewUrl?'试听官方示例音频':previewRequest?'使用当前模型合成短句试听':'该音色暂无官方试听音频'" :aria-label="`${playing===name?'暂停试听':'试听'} ${byId[name]?.name||name}`" @pointerdown.prevent @click.stop="preview(byId[name])"><LoaderCircle v-if="loading===name" :size="15" class="voice-preview-spin"/><Pause v-else-if="playing===name" :size="15"/><Volume2 v-else :size="15"/><span>{{loading===name?'加载中':playing===name?'暂停试听':'试听'}}</span></button>
      </div>
    </template>
  </ModelNameSelect>
  <p v-if="error" class="voice-preview-error" role="alert">{{error}}</p>
</template>
<style scoped>
.voice-option{display:flex;align-items:center;gap:12px;padding:5px 7px;border-radius:11px;min-width:0;color:#51455c}.voice-option:hover,.voice-option.highlighted{background:#faf7ff}.voice-option.selected{background:#f3edff;color:#7c3aed}.voice-option .voice-choice{flex:1;min-width:0;display:flex;flex-direction:column;align-items:flex-start;gap:7px;padding:9px 3px;background:transparent;border:0;color:inherit;font:inherit;font-size:14px;text-align:left;cursor:pointer}.voice-choice span{overflow-wrap:anywhere;line-height:1.5}.voice-choice small{color:#9b96a4;font-size:12px;line-height:1.5}.voice-check{flex-shrink:0;color:#7c3aed}.voice-option .voice-preview{display:inline-flex;align-items:center;justify-content:center;gap:6px;width:auto;flex-shrink:0;padding:9px 11px;border:1px solid #ddd5eb;border-radius:10px;background:#fff;color:#7c3aed;cursor:pointer;font:inherit;font-size:12px;white-space:nowrap}.voice-option .voice-preview:hover:not(:disabled){background:#fff;border-color:#ddd5eb;color:#7c3aed}.voice-option .voice-preview.playing,.voice-option .voice-preview.playing:hover:not(:disabled){background:#6415bd;color:#fff;border-color:#6415bd}.voice-option .voice-preview:disabled{opacity:.45;cursor:default}.voice-choice:focus-visible,.voice-preview:focus-visible{outline:2px solid #a78bfa;outline-offset:2px}.voice-preview-error{margin:7px 0 0;font-size:12px;color:#b42345}.voice-preview-spin{animation:voice-preview-spin 1s linear infinite}@keyframes voice-preview-spin{to{transform:rotate(360deg)}}
</style>
