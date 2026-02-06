<script setup>
import { computed, ref, watch, reactive, onMounted, onUnmounted } from 'vue'
import { Copy, Sparkles, Loader2, ChevronDown, ChevronUp, Trash2, Maximize2, History, Clipboard, Image as ImageIcon, FileImage, Layers, Square, Eye, EyeOff } from 'lucide-vue-next'

const props = defineProps({
  width: Number,
  meta: Object,
  selectedImage: Object,
  genParams: Object,
  filterData: Object,
  comfyStatus: Object,
  isGenerating: Boolean,
  isRandomSeed: Boolean,
  isMobile: Boolean,
  loading: Boolean
})

const emit = defineEmits([
  'update:genParams',
  'update:isRandomSeed',
  'applyToWorkspace',
  'delete',
  'submit'
])

// --- State ---
const showImageInfo = ref(true)
const showGenParams = ref(true)
const showHistory = ref(false)
const historyType = ref('positive')
const showAdvanced = ref(localStorage.getItem('aimg_show_advanced') === 'true') // Persistence for toggle

watch(showAdvanced, (val) => localStorage.setItem('aimg_show_advanced', val))

// --- Queue Persistence Logic ---
const queueData = ref({ pending: [], history: [], queue_remaining: 0 })
let queueTimer = null

const fetchQueue = async () => {
  try {
    const res = await fetch('/api/comfy/queue')
    if (res.ok) queueData.value = await res.json()
  } catch (e) {}
}

const cancelTask = async (id) => {
  if (!confirm('确定取消该任务吗？')) return
  await fetch('/api/comfy/cancel_task', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt_id: id })
  })
  fetchQueue()
}

const interruptCurrent = async () => {
  if (!confirm('确定中断当前任务吗？')) return
  await fetch('/api/comfy/interrupt', { method: 'POST' })
  fetchQueue()
}

// --- Params Logic ---
const localGenParams = ref({ ...props.genParams })
const localIsRandomSeed = ref(props.isRandomSeed)

const promptHistory = reactive({
    positive: JSON.parse(localStorage.getItem('aimg_prompt_history_pos') || '[]'),
    negative: JSON.parse(localStorage.getItem('aimg_prompt_history_neg') || '[]')
})

const addToHistory = (text, type) => {
    if (!text || !text.trim()) return
    const list = promptHistory[type]
    if (list.length > 0 && list[0].text === text) return
    list.unshift({ id: Date.now(), text, timestamp: Date.now() })
    if (list.length > 50) list.pop()
    localStorage.setItem(`aimg_prompt_history_${type === 'positive' ? 'pos' : 'neg'}`, JSON.stringify(list))
}

const useHistoryItem = (item) => {
    if (historyType.value === 'positive') localGenParams.value.prompt = item.text
    else localGenParams.value.negative_prompt = item.text
    showHistory.value = false
}

// --- AI Optimization ---
const isOptimizing = ref(false)
const aiStatus = ref("")
const promptInput = ref(null)
const negPromptInput = ref(null)

const runAIOptimize = async (mode) => {
    if (isOptimizing.value) return
    let userInput = "", existingPrompt = "", targetInputRef = null
    if (mode === 'optimize') {
        existingPrompt = localGenParams.value.prompt; targetInputRef = promptInput
        userInput = prompt("请输入优化指令", "优化这段提示词")
    } else if (mode === 'negative') {
        existingPrompt = localGenParams.value.negative_prompt; targetInputRef = negPromptInput
        userInput = prompt("请输入反向词优化指令", "补充通用反向词")
    }
    if (!userInput) return
    isOptimizing.value = true
    aiStatus.value = "AI 思考中..."
    try {
        const response = await fetch('/api/ai/optimize', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode, user_input: userInput, existing_prompt: existingPrompt })
        })
        const reader = response.body.getReader(), decoder = new TextDecoder()
        let resultText = ""
        while (true) {
            const { done, value } = await reader.read()
            if (done) break
            const chunk = decoder.decode(value)
            for (const line of chunk.split('\n\n')) {
                if (line.startsWith('data: ')) {
                    const data = JSON.parse(line.slice(6))
                    if (data.chunk) {
                        resultText += data.chunk
                        if (mode === 'negative') localGenParams.value.negative_prompt = resultText
                        else localGenParams.value.prompt = resultText
                        if (targetInputRef.value) targetInputRef.value.scrollTop = targetInputRef.value.scrollHeight
                    }
                }
            }
        }
        addToHistory(resultText, mode === 'negative' ? 'negative' : 'positive')
    } catch (e) { alert("AI 失败: " + e.message) }
    finally { isOptimizing.value = false; aiStatus.value = "" }
}

const handlePaste = async () => {
    // 1. Try modern async clipboard API (requires Secure Context: HTTPS or localhost)
    try {
        if (!navigator.clipboard || !navigator.clipboard.read) throw new Error("Clipboard API unavailable")
        
        const items = await navigator.clipboard.read()
        for (const item of items) {
            // Find image type (e.g., image/png)
            const type = item.types.find(t => t.startsWith('image/'))
            if (type) {
                const blob = await item.getType(type)
                uploadImageForPrompt(blob)
                return
            }
        }
        // If no image found in clipboard items (but read was successful), verify text?
        // Usually prompt text if mixed content?
    } catch (err) {
        // console.warn("Auto-read clipboard failed...", err)
    }

    // 2. Fallback: Listen for manual paste event (Ctrl+V)
    // alert("由于浏览器安全限制，无法自动读取剪切板。\n\n请点击确定后，直接按下键盘 Ctrl+V 即可粘贴图片。")
    
    // Notify user to paste
    const originalStatus = aiStatus.value
    aiStatus.value = "请按 Ctrl+V 粘贴..."
    
    const manualPasteHandler = (e) => {
        const items = e.clipboardData?.items || []
        for (const item of items) {
            if (item.type.startsWith('image/')) {
                e.preventDefault()
                const blob = item.getAsFile()
                uploadImageForPrompt(blob)
                cleanup()
                return
            }
        }
        // If text pasted
        const text = e.clipboardData?.getData('text')
        if (text) {
             localGenParams.value.prompt = text
             alert("已粘贴文本")
             cleanup()
        }
    }

    const cleanup = () => {
        window.removeEventListener('paste', manualPasteHandler)
        if (aiStatus.value === "请按 Ctrl+V 粘贴图片...") aiStatus.value = originalStatus
    }

    window.addEventListener('paste', manualPasteHandler)
    
    // Auto-cancel listener after 10 seconds if no action
    setTimeout(cleanup, 10000)
}

const uploadImageForPrompt = async (blob) => {
    if (isOptimizing.value) return
    isOptimizing.value = true; aiStatus.value = "识图中..."
    try {
        const reader = new FileReader()
        reader.readAsDataURL(blob)
        reader.onloadend = async () => {
            const base64data = reader.result.split(',')[1]
            const response = await fetch('/api/ai/optimize', { method: 'POST', body: JSON.stringify({ mode: 'image', image_b64: base64data }) })
            const streamReader = response.body.getReader(), decoder = new TextDecoder()
            let resultText = ""
            while (true) {
                const { done, value } = await streamReader.read()
                if (done) break
                const chunk = decoder.decode(value)
                for (const line of chunk.split('\n\n')) {
                    if (line.startsWith('data: ')) {
                        const data = JSON.parse(line.slice(6))
                        if (data.chunk) {
                            resultText += data.chunk
                            localGenParams.value.prompt = resultText // Update UI in real-time
                        }
                    }
                }
            }
            if (resultText) { addToHistory(resultText, 'positive') }
            isOptimizing.value = false; aiStatus.value = ""
        }
    } catch (e) { alert("识图失败: " + e.message); isOptimizing.value = false; aiStatus.value = "" }
}

// --- Watchers ---
watch(() => props.genParams, (newVal) => {
  if (JSON.stringify(newVal) !== JSON.stringify(localGenParams.value)) localGenParams.value = { ...newVal }
}, { deep: true })
watch(localGenParams, (newVal) => emit('update:genParams', newVal), { deep: true })
watch(() => props.isRandomSeed, (val) => localIsRandomSeed.value = val)
watch(localIsRandomSeed, (val) => emit('update:isRandomSeed', val))

const getImageDimensions = () => {
  if (props.selectedImage) return `${props.selectedImage.width}x${props.selectedImage.height}`
  if (props.meta?.params?.width && props.meta?.params?.height) return `${props.meta.params.width}x${props.meta.params.height}`
  return ''
}

const baseResolutions = ["512x512", "512x768", "768x512", "768x768", "1024x1024", "832x1216", "1216x832"]
const availableResolutions = computed(() => {
    const current = localGenParams.value.resolution
    if (current && current !== 'custom' && !baseResolutions.includes(current)) return [current, ...baseResolutions]
    return baseResolutions
})

// --- Resizing Logic ---
const imageInfoHeight = ref(300) // Initial height in pixels
const isResizing = ref(false)

const startResize = (e) => {
    isResizing.value = true
    const startY = e.type.includes('mouse') ? e.clientY : e.touches[0].clientY
    const startHeight = imageInfoHeight.value

    const onMove = (e) => {
        const currentY = e.type.includes('mouse') ? e.clientY : e.touches[0].clientY
        const delta = currentY - startY
        // Clamp height between 100px and 80% of window height
        const newHeight = Math.max(100, Math.min(window.innerHeight * 0.8, startHeight + delta))
        imageInfoHeight.value = newHeight
    }

    const onEnd = () => {
        isResizing.value = false
        // Save new height preference
        localStorage.setItem('aimg_image_info_height', imageInfoHeight.value)
        
        window.removeEventListener('mousemove', onMove)
        window.removeEventListener('touchmove', onMove)
        window.removeEventListener('mouseup', onEnd)
        window.removeEventListener('touchend', onEnd)
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('touchmove', onMove, { passive: false })
    window.addEventListener('mouseup', onEnd)
    window.addEventListener('touchend', onEnd)
}

onMounted(() => {
    fetchQueue()
    queueTimer = setInterval(fetchQueue, 3000)
    // Initialize height from localStorage or default to 40% of window
    const savedHeight = localStorage.getItem('aimg_image_info_height')
    if (savedHeight) {
        imageInfoHeight.value = parseFloat(savedHeight)
    } else {
        imageInfoHeight.value = window.innerHeight * 0.4
    }
})
onUnmounted(() => {
    clearInterval(queueTimer)
})
</script>

<template>
  <section :style="{ width: isMobile ? '100%' : width + 'px' }" 
    class="flex-shrink-0 flex flex-col bg-white dark:bg-[#111216] h-full"
    :class="isMobile ? 'overflow-y-auto' : 'overflow-hidden border-l border-black/5 dark:border-white/5'">
    
    <!-- 1. Real-time Queue Section (Always Visible) -->
    <div class="flex-shrink-0 border-b border-black/5 dark:border-white/5 bg-gray-50/50 dark:bg-black/20 overflow-hidden">
        <div class="h-9 px-4 flex items-center justify-between border-b border-black/5 dark:border-white/5">
            <div class="flex items-center gap-2">
                <Layers class="w-3.5 h-3.5 text-indigo-500" />
                <span class="text-xs font-bold uppercase tracking-wider">队列管理</span>
                <span v-if="queueData.queue_remaining > 0" class="text-[10px] bg-indigo-600 text-white px-1.5 rounded-full">{{ queueData.queue_remaining }}</span>
            </div>
            <button v-if="queueData.pending.some(t => t.status === 'running')" @click="interruptCurrent" 
                    class="text-[10px] text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10 px-2 py-0.5 rounded border border-red-200 dark:border-red-500/30 flex items-center gap-1 transition-colors">
                <Square class="w-2.5 h-2.5 fill-current" /> 中断
            </button>
        </div>
        
        <!-- Detailed Queue Items -->
        <div class="max-h-40 overflow-y-auto px-3 py-2 space-y-2">
            <div v-for="task in queueData.pending" :key="task.id" 
                 class="group relative flex flex-col gap-1.5 p-2 rounded bg-white dark:bg-zinc-900 border border-black/5 dark:border-white/5 overflow-hidden">
                
                <!-- Background Progress Fill (Running only) -->
                <div v-if="task.status === 'running'" 
                     class="absolute bottom-0 left-0 h-0.5 bg-indigo-500/50 transition-all duration-300"
                     :style="{ width: task.progress + '%' }"></div>

                <div class="flex items-center justify-between gap-2 relative z-10">
                    <div class="flex-1 min-w-0 flex items-center gap-2">
                        <Loader2 v-if="task.status === 'running'" class="w-3 h-3 text-indigo-500 animate-spin flex-shrink-0" />
                        <span v-else class="text-[9px] font-mono text-gray-400">#{{ queueData.pending.indexOf(task) + 1 }}</span>
                        <span class="text-[10px] font-bold text-gray-700 dark:text-gray-300 truncate">{{ task.prompt || '未知任务' }}</span>
                    </div>
                    
                    <!-- Progress Stats -->
                    <div v-if="task.status === 'running'" class="text-[9px] font-bold text-indigo-600 dark:text-indigo-400 flex items-center gap-1">
                        <span>{{ task.progress_text }}</span>
                        <span>({{ Math.round(task.progress) }}%)</span>
                    </div>
                    
                    <button v-if="task.status === 'pending'" @click="cancelTask(task.id)" 
                            class="opacity-0 group-hover:opacity-100 p-0.5 text-gray-400 hover:text-red-500 transition-opacity">
                        <Trash2 class="w-3 h-3" />
                    </button>
                </div>

                <!-- Secondary Info -->
                <div class="flex items-center justify-between text-[9px] text-gray-400 relative z-10 px-1">
                    <div class="truncate max-w-[70%]">{{ task.lora_info || '无 LoRA' }}</div>
                    <div class="flex-shrink-0 uppercase">{{ task.status }}</div>
                </div>
            </div>

            <div v-if="queueData.pending.length === 0" class="text-center py-4 border-2 border-dashed border-black/5 dark:border-white/5 rounded-lg">
                <span class="text-[10px] text-gray-400 uppercase tracking-widest font-bold italic">Waiting for Magic / 队列空闲</span>
            </div>
        </div>
    </div>

    <!-- 2. Image Info Section (Resizable) -->
    <div class="flex flex-col border-b border-black/5 dark:border-white/5 transition-[height] duration-0 relative"
         :style="{ height: isMobile ? 'auto' : (showImageInfo ? imageInfoHeight + 'px' : '36px') }"
         :class="isResizing ? 'select-none' : (isMobile ? 'overflow-visible flex-shrink-0' : 'overflow-hidden')">
      
      <!-- Header -->
      <div class="h-9 px-4 flex-shrink-0 flex items-center justify-between cursor-pointer hover:bg-gray-50 dark:hover:bg-white/5 select-none"
           @click="showImageInfo = !showImageInfo">
        <h3 class="text-[11px] font-bold uppercase tracking-wide text-indigo-600 dark:text-indigo-400">图片信息</h3>
        <component :is="showImageInfo ? ChevronUp : ChevronDown" class="w-3.5 h-3.5 text-gray-400" />
      </div>

      <!-- Content -->
      <div v-show="showImageInfo" class="flex-1 px-4 pb-4 transition-opacity duration-200" 
           :class="[
               loading ? 'opacity-50 pointer-events-none' : 'opacity-100',
               isMobile ? 'overflow-visible' : 'overflow-y-auto'
           ]">
        <div class="space-y-3">
          <!-- Important: Prompt -->
          <div class="space-y-1 group relative">
             <div class="flex justify-between items-end">
                <label class="text-[9px] font-bold text-gray-400 uppercase">正向提示词</label>
                <button v-if="meta?.prompt" class="opacity-0 group-hover:opacity-100 p-1 text-gray-400 hover:text-indigo-500" title="复制"
                  @click="navigator.clipboard.writeText(meta.prompt)">
                  <Copy class="w-3 h-3" />
                </button>
             </div>
             <div class="text-xs p-2 bg-gray-50 dark:bg-zinc-900 rounded-lg break-words max-h-32 overflow-y-auto border border-transparent hover:border-gray-200 dark:hover:border-white/10 transition-colors">
               {{ meta?.prompt || '暂无数据' }}
             </div>
          </div>
          
          <!-- Important Stats -->
          <div class="grid grid-cols-2 gap-2">
            <div v-for="(v, k) in { 
              '尺寸': getImageDimensions(), 
              '模型': meta?.params?.Model || meta?.params?.model 
            }" :key="k" class="p-2 bg-gray-50 dark:bg-zinc-900 rounded-lg">
              <div class="text-[9px] text-gray-400 uppercase">{{ k }}</div>
              <div class="text-xs font-mono truncate" :title="v">{{ v || '-' }}</div>
            </div>
          </div>

          <!-- Unimportant Stats (Hideable) -->
          <div v-if="showAdvanced" class="grid grid-cols-2 gap-2 border-t border-dashed border-gray-200 dark:border-white/5 pt-2 animate-in slide-in-from-top-1 duration-200">
            <div v-for="(v, k) in { 
              '步数': meta?.params?.Steps || meta?.params?.steps, 
              'CFG': meta?.params?.['CFG scale'] || meta?.params?.cfg, 
              '采样器': meta?.params?.Sampler || meta?.params?.sampler_name, 
              '调度器': meta?.params?.Scheduler || meta?.params?.scheduler,
              '种子': meta?.params?.Seed || meta?.params?.seed
            }" :key="k" class="p-2 bg-gray-50 dark:bg-zinc-900 rounded-lg">
              <div class="text-[9px] text-gray-400 uppercase">{{ k }}</div>
              <div class="text-xs font-mono truncate" :title="v">{{ v || '-' }}</div>
            </div>
          </div>

          <!-- Important: LoRAs -->
          <div v-if="meta?.loras && meta.loras.length > 0" class="p-2 bg-gray-50 dark:bg-zinc-900 rounded-lg">
              <div class="text-[9px] text-gray-400 uppercase mb-1">LoRAs & Weights</div>
              <div class="space-y-1">
                  <div v-for="(lora, idx) in meta.loras" :key="idx" class="text-[11px] font-mono truncate text-indigo-600 dark:text-indigo-400" :title="lora">
                      {{ lora }}
                  </div>
              </div>
          </div>
          
          <div class="flex gap-2 pt-1">
            <button @click="$emit('applyToWorkspace')" class="flex-1 py-1.5 bg-indigo-600/10 text-indigo-600 dark:text-indigo-400 text-xs font-bold rounded-lg flex items-center justify-center gap-1 hover:bg-indigo-600/20 transition-colors">
              <Copy class="w-3 h-3" /> 复写参数
            </button>
            <button @click="$emit('delete')" class="flex-1 py-1.5 bg-red-600/10 text-red-600 text-xs font-bold rounded-lg hover:bg-red-600/20 transition-colors flex items-center justify-center gap-1">
              <Trash2 class="w-3 h-3" /> 删除
            </button>
          </div>
        </div>
      </div>
    </div>



    <!-- Resize Handle (Desktop Only) -->
    <div v-if="showImageInfo && !isMobile"
         @mousedown="startResize" @touchstart.prevent="startResize"
         class="h-2 -mt-1 -mb-1 relative z-20 cursor-row-resize flex items-center justify-center group hover:bg-indigo-500/10 active:bg-indigo-500/20 transition-colors">
        <!-- Visual Indicator line -->
        <div class="w-8 h-1 rounded-full bg-gray-300 dark:bg-white/20 group-hover:bg-indigo-400 transition-colors"></div>
    </div>

    <!-- 3. Generate Params Section (Flexible Height) -->
    <div class="flex flex-col bg-gray-50/50 dark:bg-zinc-900/30 relative"
         :class="isMobile ? 'flex-shrink-0 overflow-visible' : 'flex-1 overflow-hidden'">
      
      <!-- History Overlay Modal (Remains same) -->
      <div v-if="showHistory" class="absolute inset-0 z-20 bg-white dark:bg-[#111216] flex flex-col animate-in fade-in zoom-in-95 duration-200">
          <div class="flex items-center justify-between p-3 border-b border-gray-100 dark:border-white/5">
              <h3 class="text-xs font-bold">{{ historyType === 'positive' ? '正向' : '反向' }}提示词历史</h3>
              <div class="flex gap-2">
                  <button @click="showHistory = false" class="text-gray-500 hover:bg-gray-100 p-1 rounded">✕</button>
              </div>
          </div>
          <div class="flex-1 overflow-y-auto p-2 space-y-2">
              <div v-for="item in promptHistory[historyType]" :key="item.id" 
                   @click="useHistoryItem(item)"
                   class="p-2 bg-gray-50 dark:bg-zinc-900 rounded border border-transparent hover:border-indigo-500 cursor-pointer text-xs break-words">
                  <div class="text-[10px] text-gray-400 mb-1">{{ new Date(item.timestamp).toLocaleString() }}</div>
                  {{ item.text }}
              </div>
          </div>
      </div>

      <!-- Header -->
       <div class="h-10 px-4 flex items-center justify-between border-b border-black/5 dark:border-white/5 bg-gray-100/50 dark:bg-black/20">
        <h3 class="text-[11px] font-bold uppercase tracking-wide text-gray-500">生成参数</h3>
        <div class="flex items-center gap-2">
            <!-- Advanced Toggle Button -->
            <button @click="showAdvanced = !showAdvanced" 
                    class="flex items-center gap-1 px-2 py-1 rounded-full border border-black/5 dark:border-white/5 transition-all text-[9px] font-bold uppercase"
                    :class="showAdvanced ? 'bg-indigo-100 text-indigo-600 border-indigo-200' : 'bg-white dark:bg-white/5 text-gray-500'">
                <component :is="showAdvanced ? Eye : EyeOff" class="w-3 h-3" />
                {{ showAdvanced ? '完整模式' : '精简模式' }}
            </button>
            <div class="flex items-center gap-1 bg-white dark:bg-white/5 px-2 py-1 rounded-full border border-black/5 dark:border-white/5">
                <div class="w-1.5 h-1.5 rounded-full transition-colors" :class="comfyStatus.connected ? 'bg-green-500' : 'bg-red-500'"></div>
                <span class="text-[9px] font-bold text-gray-500 uppercase">{{ comfyStatus.connected ? 'ON' : 'OFF' }}</span>
            </div>
        </div>
      </div>

      <!-- Scrollable Form -->
      <div class="p-4 space-y-4" :class="isMobile ? 'flex-shrink-0 overflow-visible' : 'flex-1 overflow-y-auto'">
        
        <!-- Important: Model & LoRA (Hidden in Simple Mode) -->
        <!-- LoRA (Always Visible) -->
        <div class="space-y-1">
            <label class="text-[10px] font-bold text-gray-400 uppercase">LoRA & 权重</label>
            <div class="flex gap-2">
                 <select v-model="localGenParams.lora" class="flex-[2] h-8 px-2 bg-white dark:bg-zinc-800 border border-gray-200 dark:border-white/10 rounded-md text-xs outline-none focus:border-indigo-500">
                    <option value="">无 LoRA</option>
                    <option v-for="l in filterData.loras" :key="l" :value="l">{{ l }}</option>
                </select>
                <input v-model.number="localGenParams.lora_weight" type="number" step="0.01" placeholder="权重" 
                       class="flex-1 h-8 px-2 bg-white dark:bg-zinc-800 border border-gray-200 dark:border-white/10 rounded-md text-xs outline-none focus:border-indigo-500" 
                       :disabled="!localGenParams.lora"
                       @wheel.prevent="localGenParams.lora_weight = parseFloat(Math.max(0, localGenParams.lora_weight + ($event.deltaY > 0 ? -0.01 : 0.01)).toFixed(2))"
                       />
            </div>
        </div>

        <!-- Model (Advanced Only) -->
        <div v-if="showAdvanced" class="space-y-2 animate-in fade-in zoom-in-95 duration-200">
            <label class="text-[10px] font-bold text-gray-400 uppercase block">模型 Checkpoint</label>
            <select v-model="localGenParams.model" class="w-full h-8 px-2 bg-white dark:bg-zinc-800 border border-gray-200 dark:border-white/10 rounded-md text-xs outline-none focus:border-indigo-500">
                <option value="" disabled>选择模型...</option>
                <option v-for="m in filterData.models" :key="m" :value="m">{{ m }}</option>
            </select>
        </div>

        <!-- Important: Prompts -->
        <div class="space-y-1">
             <div class="flex justify-between items-center mb-1">
                <label class="text-[10px] font-bold text-gray-400 uppercase">正向提示词</label>
                <div class="flex gap-1">
                    <span v-if="aiStatus" class="text-[10px] text-indigo-500 animate-pulse">{{ aiStatus }}</span>
                    <button @click="showHistory = true; historyType='positive'" class="p-1 hover:bg-gray-200 dark:hover:bg-white/10 rounded"><History class="w-3 h-3 text-gray-500"/></button>
                    <button @click="handlePaste" class="p-1 hover:bg-gray-200 dark:hover:bg-white/10 rounded" title="从剪切板读取"><Clipboard class="w-3 h-3 text-gray-500"/></button>
                    <button @click="runAIOptimize('optimize')" class="p-1 hover:bg-gray-200 dark:hover:bg-white/10 rounded"><Sparkles class="w-3 h-3 text-indigo-500"/></button>
                </div>
             </div>
             <textarea v-model="localGenParams.prompt" ref="promptInput"
                       class="w-full min-h-[80px] p-3 bg-white dark:bg-zinc-800 border border-gray-200 dark:border-white/10 rounded-md text-xs resize-y outline-none focus:border-indigo-500 leading-relaxed font-mono"
                       placeholder="输入提示词..."></textarea>
        </div>

        <!-- Seed Control (Always Visible) -->
        <div class="bg-gray-100/50 dark:bg-white/5 p-2 rounded-lg flex items-center justify-between gap-3">
            <div class="flex items-center gap-2 flex-1">
                <span class="text-[10px] font-bold text-gray-400 uppercase">Seed</span>
                <input v-model.number="localGenParams.seed" :disabled="localIsRandomSeed" type="number" 
                    class="flex-1 h-7 px-2 bg-white dark:bg-zinc-800 border border-gray-200 dark:border-white/10 rounded text-[11px] font-mono outline-none focus:border-indigo-500 disabled:opacity-50" />
            </div>
            <label class="flex items-center gap-1.5 cursor-pointer select-none">
                <input type="checkbox" v-model="localIsRandomSeed" class="rounded accent-indigo-600 w-3.5 h-3.5" />
                <span class="text-[11px] font-bold text-indigo-600 dark:text-indigo-400">随机</span>
            </label>
        </div>

        <div class="space-y-1">
             <div class="flex justify-between items-center mb-1">
                <label class="text-[10px] font-bold text-gray-400 uppercase">反向提示词</label>
                <div class="flex gap-1">
                    <button @click="showHistory = true; historyType='negative'" class="p-1 hover:bg-gray-200 dark:hover:bg-white/10 rounded"><History class="w-3 h-3 text-gray-500"/></button>
                    <button @click="runAIOptimize('negative')" class="p-1 hover:bg-gray-200 dark:hover:bg-white/10 rounded"><Sparkles class="w-3 h-3 text-pink-500"/></button>
                </div>
             </div>
             <textarea v-model="localGenParams.negative_prompt" ref="negPromptInput"
                       class="w-full min-h-[60px] p-3 bg-white dark:bg-zinc-800 border border-gray-200 dark:border-white/10 rounded-md text-xs resize-y outline-none focus:border-indigo-500 leading-relaxed font-mono text-pink-600 dark:text-pink-400"
                       placeholder="输入反向提示词..."></textarea>
        </div>

        <!-- Layout Grid -->
        <div class="grid grid-cols-2 gap-3">
             <!-- Important: Resolution & Batch Size -->
             <div class="space-y-1">
                <label class="text-[10px] font-bold text-gray-400 uppercase">分辨率</label>
                <select v-model="localGenParams.resolution" class="w-full h-8 px-2 bg-white dark:bg-zinc-800 border border-gray-200 dark:border-white/10 rounded-md text-xs outline-none focus:border-indigo-500">
                    <option v-for="r in availableResolutions" :key="r" :value="r">{{ r }}</option>
                    <option value="custom">自定义...</option>
                </select>
             </div>
             <div class="space-y-1">
                 <label class="text-[10px] font-bold text-gray-400 uppercase">生成数量</label>
                 <input v-model.number="localGenParams.batch_size" type="number" min="1" max="8" 
                        class="w-full h-8 px-2 bg-white dark:bg-zinc-800 border border-gray-200 dark:border-white/10 rounded-md text-xs outline-none focus:border-indigo-500" 
                        @wheel.prevent="localGenParams.batch_size = Math.max(1, Math.min(8, localGenParams.batch_size + ($event.deltaY > 0 ? -1 : 1)))"
                        />
             </div>

             <!-- Unimportant Params (Show only if showAdvanced is true) -->
             <template v-if="showAdvanced">
                 <div class="space-y-1 animate-in fade-in zoom-in-95 duration-200">
                    <label class="text-[10px] font-bold text-gray-400 uppercase">采样器</label>
                    <select v-model="localGenParams.sampler" class="w-full h-8 px-2 bg-white dark:bg-zinc-800 border border-gray-200 dark:border-white/10 rounded-md text-xs outline-none focus:border-indigo-500">
                      <option v-for="s in filterData.samplers" :key="s" :value="s">{{ s }}</option>
                    </select>
                 </div>
                 <div class="space-y-1 animate-in fade-in zoom-in-95 duration-200">
                    <label class="text-[10px] font-bold text-gray-400 uppercase">调度器</label>
                    <select v-model="localGenParams.scheduler" class="w-full h-8 px-2 bg-white dark:bg-zinc-800 border border-gray-200 dark:border-white/10 rounded-md text-xs outline-none focus:border-indigo-500">
                      <option v-for="s in filterData.schedulers" :key="s" :value="s">{{ s }}</option>
                    </select>
                 </div>
                 <div class="space-y-1 animate-in fade-in zoom-in-95 duration-200">
                     <label class="text-[10px] font-bold text-gray-400 uppercase">步数</label>
                     <input v-model.number="localGenParams.steps" type="number" class="w-full h-8 px-2 bg-white dark:bg-zinc-800 border border-gray-200 dark:border-white/10 rounded-md text-xs outline-none focus:border-indigo-500" />
                 </div>
                 <div class="space-y-1 animate-in fade-in zoom-in-95 duration-200">
                     <label class="text-[10px] font-bold text-gray-400 uppercase">CFG Scale</label>
                     <input v-model.number="localGenParams.cfg" type="number" step="0.5" class="w-full h-8 px-2 bg-white dark:bg-zinc-800 border border-gray-200 dark:border-white/10 rounded-md text-xs outline-none focus:border-indigo-500" />
                 </div>
             </template>
        </div>

      </div>

      <!-- Footer Action -->
      <!-- Spacer for mobile fixed footer -->
      <div v-if="isMobile" class="h-20 flex-shrink-0"></div>
      
      <div class="p-4 border-t border-black/5 dark:border-white/5 bg-white dark:bg-[#111216]"
           :class="isMobile ? 'fixed bottom-0 left-0 right-0 z-[100] shadow-[0_-4px_12px_rgba(0,0,0,0.1)]' : ''">
        <button @click="$emit('submit')" :disabled="!comfyStatus.connected || isGenerating"
            class="w-full h-10 bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-400 disabled:cursor-not-allowed text-white text-sm font-bold rounded-lg flex items-center justify-center gap-2 transition-all shadow-lg shadow-indigo-500/20 active:scale-[0.98]">
            <Sparkles v-if="!isGenerating" class="w-4 h-4" />
            <Loader2 v-else class="w-4 h-4 animate-spin" />
            {{ isGenerating ? '正在渲染...' : '开始渲染' }}
        </button>
      </div>
    </div>
  </section>
</template>
