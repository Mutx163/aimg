<script setup>
import { ref, reactive, onMounted, watch, computed } from 'vue'
import { 
  Search, 
  Settings2, 
  Sparkles, 
  Moon, 
  Sun, 
  Image as ImageIcon, 
  Plus, 
  Send,
  Loader2,
  Trash2,
  Copy,
  LayoutGrid,
  Zap,
  ChevronLeft,
  ChevronRight,
  X,
  History,
  Grid
} from 'lucide-vue-next'

// --- State ---
const activeTab = ref('gallery')
const images = ref([])
const loading = ref(false)
const searchKeyword = ref("")
const page = ref(1)
const hasMore = ref(true)
// Dark Mode Init
const isDark = ref(false)
const initTheme = () => {
    const saved = localStorage.getItem('theme')
    isDark.value = saved === 'dark' || (!saved && window.matchMedia('(prefers-color-scheme: dark)').matches)
    updateThemeClass()
}

// Responsive State
const isDesktop = ref(window.matchMedia('(min-width: 1024px)').matches)
window.matchMedia('(min-width: 1024px)').addEventListener('change', e => {
  isDesktop.value = e.matches
})

// Modal & Detail
const selectedImage = ref(null)
const meta = ref(null)
const imageAnimationClass = ref("")
const detailImageLoading = ref(true)
const detailImageError = ref(false)

// Filters
const showFilters = ref(false)
const filterData = reactive({ folders: [], models: [], loras: [], samplers: [], schedulers: [], resolutions: [] })
const selectedFilters = reactive({ folder: null, model: null, lora: null })

// AI Optimize
const showAIModal = ref(false)
const aiInput = ref("")
const aiLoading = ref(false)
const aiTarget = ref("positive")

// Generation
const isGenerating = ref(false)
const comfyStatus = reactive({ connected: false, queue_remaining: 0 })
const queueData = reactive({ pending: [], history: [], progress: 0 })

const SYSTEM_PROMPTS = {
  GENERATE: "你是一位专业的AI绘画提示词高级专家。你的任务是将用户的需求口语化转换为一段细节丰富、画面清晰、且完全使用中文自然语言书写的提示词。",
  OPTIMIZE: "你是一位专业的AI绘画提示词优化专家。你的任务是根据用户的修改指令，直接重写并优化现有提示词，输出为中文自然语言。",
  NEG_GENERATE: "你是一位专业的AI绘画负向提示词处理专家。要求输出中文关键词列表，使用中文逗号分隔。",
  NEG_OPTIMIZE: "你是一位专业的AI绘画负向提示词优化专家。要求在保留原有内容基础上，根据新指令精准添加关键词。"
}

const genParams = reactive({
  model: "",
  prompt: "",
  negative_prompt: "",
  resolution: "512x768",
  sampler: "",
  scheduler: "",
  steps: 20,
  cfg: 7.0,
  lora: "",
  lora_weight: 1.0,
  seed: -1,
  batch_size: 1
})

const isRandomSeed = ref(true)

// --- Helper Functions ---
const readStream = async (response, onChunk) => {
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ""
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
             const data = JSON.parse(line.slice(6))
             if (data.chunk) onChunk(data.chunk)
          } catch(e) {}
        }
      }
    }
}
const stringToColor = (str) => {
  let hash = 0
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash)
  }
  const c = (hash & 0x00FFFFFF).toString(16).toUpperCase()
  return '#' + '00000'.substring(0, 6 - c.length) + c
}

const getImageDimensions = () => {
    if (selectedImage.value && selectedImage.value.width && selectedImage.value.height) {
        return `${selectedImage.value.width}×${selectedImage.value.height}`
    }
    return ''
}

// --- Sidebar Resize Logic ---
const isResizing = ref(false)
const settingsWidth = ref(parseInt(localStorage.getItem('settingsWidth')) || 420)
const startX = ref(0)
const startSettingsWidth = ref(0)

const startResize = (e) => {
    isResizing.value = true
    startX.value = e.clientX || e.touches[0].clientX
    startSettingsWidth.value = settingsWidth.value
    document.body.classList.add('select-none')
    document.addEventListener('mousemove', doResize)
    document.addEventListener('mouseup', stopResize)
    document.addEventListener('touchmove', doResize)
    document.addEventListener('touchend', stopResize)
}

const doResize = (e) => {
    if (!isResizing.value) return
    const clientX = e.clientX || e.touches[0].clientX
    const delta = clientX - startX.value
    // Dragging left increases width (since panel is on right)
    const newWidth = startSettingsWidth.value - delta 
    settingsWidth.value = Math.max(300, Math.min(window.innerWidth * 0.8, newWidth))
    localStorage.setItem('settingsWidth', settingsWidth.value)
}

const stopResize = () => {
    isResizing.value = false
    document.body.classList.remove('select-none')
    document.removeEventListener('mousemove', doResize)
    document.removeEventListener('mouseup', stopResize)
    document.removeEventListener('touchmove', doResize)
    document.removeEventListener('touchend', stopResize)
}

const onImageLoad = (img) => {
   // Simplified: No logs for homepage grid
}

// Variables for Detail View Timing
const detailMetaStart = ref(0)
const detailImageStart = ref(0)
const onDetailImageLoad = () => {
    detailImageLoading.value = false
    if (detailImageStart.value > 0) {
        const duration = Date.now() - detailImageStart.value
        console.log(`[Detail View] Full Image Render took ${duration}ms`)
    }
}

// --- Image Actions ---
const showNotification = (msg, type = "info") => {
    const container = document.createElement("div")
    container.className = `fixed top-4 right-4 z-[200] px-4 py-3 rounded-xl shadow-lg text-sm font-medium flex items-center gap-2 animate-slide-in ${type === "success" ? "bg-green-500/20 text-green-400 border border-green-500/30" :
        type === "error" ? "bg-red-500/20 text-red-400 border border-red-500/30" :
            "bg-blue-500/20 text-blue-400 border border-blue-500/30"
        }`
    container.innerHTML = msg
    document.body.appendChild(container)
    setTimeout(() => {
        container.style.opacity = "0"
        container.style.transform = "translateX(100px)"
        container.style.transition = "all 0.3s"
        setTimeout(() => container.remove(), 300)
    }, 3000)
}

const confirmDelete = () => {
    if (!selectedImage.value) return
    if (confirm(`确定要将此图片移至回收站吗？\n${selectedImage.value.file_name}`)) {
        deleteImage()
    }
}

const deleteImage = async () => {
    const path = selectedImage.value.file_path
    try {
        const res = await fetch(`/api/image?path=${encodeURIComponent(path)}`, {
            method: 'DELETE'
        })

        if (res.status === 405) {
            alert("删除失败 (405): 服务器拒绝了 DELETE 请求。请重启 Python 后端。")
            return
        }

        const data = await res.json()
        if (data.success) {
            const index = images.value.findIndex(img => img.file_path === path)
            if (index !== -1) {
                images.value.splice(index, 1)
            }
            selectedImage.value = null // Close modal
            showNotification("图片已成功移至回收站", "success")
        } else {
            throw new Error(data.detail || "删除失败")
        }
    } catch (err) {
        console.error("Delete error:", err)
        showNotification("请求删除失败", "error")
    }
}

const applyToWorkspace = () => {
    if (!meta.value) return
    const m = meta.value
    const p = m.params || {}

    // Basic Params
    genParams.prompt = m.prompt || ""
    genParams.negative_prompt = m.negative_prompt || ""
    genParams.model = p.Model || p.model || ""
    genParams.steps = parseInt(p.Steps || p.steps) || 20
    genParams.cfg = parseFloat(p['CFG scale'] || p.cfg || p.CFG) || 7.0
    genParams.sampler = p.Sampler || p.sampler_name || ""
    genParams.scheduler = p.Scheduler || p.scheduler || ""

    // LoRA
    if (m.loras && m.loras.length > 0) {
        const loraStr = m.loras[0]
        const loraName = loraStr.split('(')[0].trim()
        genParams.lora = loraName
        const weightMatch = loraStr.match(/\(([\d.]+)\)/)
        genParams.lora_weight = weightMatch ? parseFloat(weightMatch[1]) : 1.0
    } else {
        genParams.lora = ""
        genParams.lora_weight = 1.0
    }

    // Resolution
    let targetRes = ""
    if (p.width && p.height) targetRes = `${p.width}x${p.height}`
    else if (p.size) targetRes = p.size
    else if (m.size) targetRes = m.size

    if (targetRes) {
        if (!filterData.resolutions.includes(targetRes)) {
            filterData.resolutions.unshift(targetRes)
        }
        genParams.resolution = targetRes
    }

    // Switch Tab
    selectedImage.value = null
    activeTab.value = 'create'
    showNotification("已调用到生图区", "success")
}

// --- Import & Buffer ---
const fileInput = ref(null)

const handleFileImport = () => {
    if (fileInput.value) fileInput.value.click()
}

const onFileChanged = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    processImageToPrompt(file)
}

const processImageToPrompt = (file, targetField = 'prompt') => {
    const reader = new FileReader()
    reader.onload = async (ev) => {
        const b64 = ev.target.result.split(",", 1)[1] || ev.target.result
        aiLoading.value = true
        
        // Clear target field for streaming
        if (targetField === 'prompt') genParams.prompt = "正在分析图片内容..."
        else genParams.negative_prompt = "正在分析图片内容..."
        
        try {
            const resp = await fetch('/api/ai/optimize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mode: 'image', user_input: '', existing_prompt: '', image_b64: b64 })
            })
            
            // Clear placeholder
            if (targetField === 'prompt') genParams.prompt = ""
            else genParams.negative_prompt = ""

            await readStream(resp, (chunk) => {
                if (targetField === 'prompt') genParams.prompt += chunk
                else genParams.negative_prompt += chunk
            })
            
            showNotification("图片识别完成", "success")
        } catch (err) {
            console.error(err)
            showNotification("图片识别失败", "error")
            if (targetField === 'prompt') genParams.prompt = "" // Reset on error
        } finally {
            aiLoading.value = false
        }
    }
    reader.readAsDataURL(file)
}

const handlePromptPaste = async (e, targetField) => {
    const items = e.clipboardData?.items
    if (!items) return

    // 1. Try Image First
    for (const item of items) {
        if (item.type.indexOf('image') !== -1) {
            e.preventDefault()
            const blob = item.getAsFile()
            processImageToPrompt(blob, targetField)
            return
        }
    }
    
    // 2. Default Text Paste (Let browser handle it, or we could intercept for logging, but default is fine)
    // The user specifically asked for "Clipboard Import" button to handle both.
    // But this function is `@paste`. We also need the button logic.
}

const handleClipboardImport = async (targetField) => {
    try {
        const items = await navigator.clipboard.read()
        for (const item of items) {
             // Prefer Image
             if (item.types.some(t => t.startsWith('image/'))) {
                 const blob = await item.getType(item.types.find(t => t.startsWith('image/')))
                 processImageToPrompt(blob, targetField)
                 return
             }
             // Then Text
             if (item.types.includes('text/plain')) {
                 const blob = await item.getType('text/plain')
                 const text = await blob.text()
                 if (targetField === 'prompt') genParams.prompt = text
                 else genParams.negative_prompt = text
                 showNotification("已粘贴剪切板文本", "success")
                 return
             }
        }
        showNotification("剪切板为空或格式不支持", "info")
    } catch (e) {
        // Fallback for Firefox/others relying on Focus
        showNotification("请尝试直接在文本框中使用 Ctrl+V", "info")
    }
}

// Prefetching
const prefetchCache = new Set()
const prefetchAdjacentImages = (currentIndex) => {
    if (currentIndex === -1) return
    [currentIndex + 1, currentIndex - 1].forEach(idx => {
        if (idx >= 0 && idx < images.value.length) {
            const img = images.value[idx]
            const src = `/api/image/raw?path=${encodeURIComponent(img.file_path)}`
            if (!prefetchCache.has(src)) {
                const i = new Image()
                i.src = src
                prefetchCache.add(src)
                if (prefetchCache.size > 20) prefetchCache.delete(prefetchCache.values().next().value)
            }
        }
    })
}

watch(selectedImage, (newVal) => {
    if (newVal) {
        const idx = images.value.findIndex(i => i.file_path === newVal.file_path)
        if (idx !== -1) prefetchAdjacentImages(idx)
    }
})



const updateThemeClass = () => {
  if (isDark.value) {
    document.documentElement.classList.add('dark')
  } else {
    document.documentElement.classList.remove('dark')
  }
}

// Ensure theme toggle works consistently
const toggleTheme = (e) => {
    e?.preventDefault()
    e?.stopPropagation() // Prevent event bubbling issues
    isDark.value = !isDark.value
    localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
    updateThemeClass()

}

const fetchImages = async (isRefresh = false) => {
  if (loading.value) return
  if (isRefresh) {
    page.value = 1
    images.value = []
    hasMore.value = true
  }
  if (!hasMore.value) return

  loading.value = true
  const fetchStart = Date.now()
  try {
    const query = new URLSearchParams({
      keyword: searchKeyword.value,
      page: page.value,
      folder: selectedFilters.folder || "",
      model: selectedFilters.model || "",
      lora: selectedFilters.lora || ""
    })
    const response = await fetch(`/api/images?${query.toString()}`)
    const data = await response.json()
    
    if (data.images.length === 0) {
      hasMore.value = false
    } else {
      const newImages = data.images.map(img => ({
        ...img,
        aspectRatio: (img.width || 512) / (img.height || 768),
        _fetchStart: Date.now()
      }))
      
      // Strict Deduplication based on file_path
      const existingPaths = new Set(images.value.map(i => i.file_path))
      const uniqueNewImages = newImages.filter(i => !existingPaths.has(i.file_path))
      
      if (uniqueNewImages.length > 0) {
        images.value = [...images.value, ...uniqueNewImages]
        page.value++
      }
      
      const duration = ((Date.now() - fetchStart) / 1000).toFixed(2)
      console.log(`[首页] 数据加载完成: 耗时 ${duration}秒 (本页 ${uniqueNewImages.length} 张新图)`)

      hasMore.value = data.has_more
    }
  } catch (err) {
    console.error("Fetch Error:", err)
  } finally {
    loading.value = false
  }
}

const fetchFilters = async () => {
  try {
    const resp = await fetch('/api/filters')
    const data = await resp.json()
    Object.assign(filterData, data)
    
    if (!genParams.model && data.models?.length > 0) genParams.model = data.models[0]
    if (!genParams.sampler && data.samplers?.length > 0) genParams.sampler = data.samplers[0]
    if (!genParams.scheduler && data.schedulers?.length > 0) genParams.scheduler = data.schedulers[0]
    if (!genParams.resolution && data.resolutions?.length > 0) genParams.resolution = data.resolutions[0]
    
    fetchComfyInfo()
  } catch (e) {}
}

const fetchComfyInfo = async () => {
    try {
        const resp = await fetch('/api/comfy/samplers_schedulers')
        const data = await resp.json()
        if (data.samplers && data.samplers.length > 0) {
            const combinedSamplers = new Set([...filterData.samplers, ...data.samplers])
            filterData.samplers = Array.from(combinedSamplers).sort()
        }
        if (data.schedulers && data.schedulers.length > 0) {
            const combinedSchedulers = new Set([...filterData.schedulers, ...data.schedulers])
            filterData.schedulers = Array.from(combinedSchedulers).sort()
        }
    } catch (e) {
        console.error("Failed to fetch comfy info", e)
    }
}

const pollComfyStatus = async () => {
  try {
    const resp = await fetch('/api/comfy/status')
    const data = await resp.json()
    comfyStatus.connected = data.connected !== false
    comfyStatus.queue_remaining = data.status?.exec_info?.queue_remaining || 0

    if (comfyStatus.connected) {
      const qResp = await fetch('/api/comfy/queue')
      const qData = await qResp.json()
      queueData.pending = qData.pending
      queueData.history = qData.history
      
      const hasRunning = queueData.pending.some(t => t.status === 'running')
      queueData.progress = hasRunning ? Math.min(95, queueData.progress + 2) : 0
    }
  } catch (e) {
    comfyStatus.connected = false
  }
  setTimeout(pollComfyStatus, 2000)
}

const submitGeneration = async () => {
  if (!comfyStatus.connected) return
  isGenerating.value = true
  try {
    await fetch('/api/comfy/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(genParams)
    })
  } catch (e) {
    console.error(e)
  } finally {
    isGenerating.value = false
  }
}

const viewDetail = async (img) => {
  console.group(`🔎 Detail View: ${img.file_name}`)
  selectedImage.value = img
  meta.value = null
  detailImageLoading.value = true
  detailImageError.value = false
  
  // Mark start times
  detailMetaStart.value = Date.now()
  detailImageStart.value = Date.now()
  
  console.log(`[Detail] Metadata fetch started at ${detailMetaStart.value}`)
  
  try {
    const response = await fetch(`/api/metadata?path=${encodeURIComponent(img.file_path)}&t=${Date.now()}`)
    meta.value = await response.json()
    const metaDuration = Date.now() - detailMetaStart.value
    console.log(`[Detail] Metadata loaded in ${metaDuration}ms`)
  } catch (err) {
    console.error(`[Detail] Metadata failed:`, err)
    meta.value = { prompt: "无法解析该图片的元数据", params: {} }
  }
}

const runAIOptimize = async () => {
  if (!aiInput.value.trim()) return
  const isNeg = aiTarget.value === "negative"
  const currentPrompt = isNeg ? genParams.negative_prompt : genParams.prompt
  
  showAIModal.value = false
  aiLoading.value = true
  
  if (isNeg) genParams.negative_prompt = "" 
  else genParams.prompt = ""

  try {
    const response = await fetch('/api/ai/optimize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode: isNeg ? 'negative' : (currentPrompt ? 'optimize' : 'generate'),
        user_input: aiInput.value,
        existing_prompt: currentPrompt,
        system_prompt: isNeg ? (currentPrompt ? SYSTEM_PROMPTS.NEG_OPTIMIZE : SYSTEM_PROMPTS.NEG_GENERATE) : (currentPrompt ? SYSTEM_PROMPTS.OPTIMIZE : SYSTEM_PROMPTS.GENERATE)
      })
    })

    await readStream(response, (chunk) => {
        if (isNeg) genParams.negative_prompt += chunk
        else genParams.prompt += chunk
    })
  } catch (e) {
    console.error(e)
  } finally {
    aiLoading.value = false
  }
}

const navigateImage = (dir) => {
  const idx = images.value.findIndex(i => i.file_path === selectedImage.value.file_path)
  const nextIdx = idx + dir
  if (nextIdx >= 0 && nextIdx < images.value.length) {
    viewDetail(images.value[nextIdx])
  }
}

onMounted(() => {
  initTheme()
  fetchImages()
  fetchFilters()
  pollComfyStatus()
  
  // Infinite Scroll
  const observer = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting && !loading.value && hasMore.value) {
      fetchImages()
    }
  }, { rootMargin: '200px' })
  
  if (loadSentinel.value) observer.observe(loadSentinel.value)
})

const loadSentinel = ref(null)

</script>

<template>
  <div class="h-screen flex flex-col overflow-hidden transition-colors duration-300"
       :style="{ backgroundColor: isDark ? '#0b0c10' : '#f3f4f6' }">
    <!-- Top Header -->
    <header class="h-16 flex-shrink-0 flex items-center justify-between px-6 bg-white/80 dark:bg-[#0b0c10]/95 backdrop-blur-xl border-b border-black/5 dark:border-white/5 z-40">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 bg-indigo-600 rounded-2xl flex items-center justify-center shadow-lg shadow-indigo-500/20">
          <Zap class="text-white w-6 h-6" />
        </div>
        <h1 class="text-xl font-bold font-outfit tracking-tight">AIMG <span class="text-indigo-600 dark:text-indigo-400">PRO</span></h1>
      </div>

      <div class="flex items-center gap-2">
        <button @click="showFilters = !showFilters" class="p-2.5 rounded-full hover:bg-black/5 dark:hover:bg-white/5 transition-all text-gray-600 dark:text-gray-300">
          <Settings2 class="w-5 h-5" />
        </button>
        <button @click="toggleTheme" class="p-2.5 rounded-full hover:bg-black/5 dark:hover:bg-white/5 transition-all cursor-pointer select-none">
          <Moon v-if="!isDark" class="w-5 h-5 text-gray-600" />
          <Sun v-else class="w-5 h-5 text-yellow-500" />
        </button>
      </div>
    </header>

    <!-- Navigation Tabs (Mobile Fix) -->
    <nav class="md:hidden flex border-b border-black/5 dark:border-white/5 bg-white dark:bg-[#0b0c10]">
      <button @click="activeTab = 'gallery'" 
        class="flex-1 py-4 text-sm font-bold transition-all relative"
        :class="activeTab === 'gallery' ? 'text-indigo-600' : 'text-gray-400'">
        画廊
        <div v-if="activeTab === 'gallery'" class="absolute bottom-0 left-1/2 -translate-x-1/2 w-8 h-1 bg-indigo-600 rounded-full"></div>
      </button>
      <button @click="activeTab = 'create'" 
        class="flex-1 py-4 text-sm font-bold transition-all relative"
        :class="activeTab === 'create' ? 'text-indigo-600' : 'text-gray-400'">
        生图
        <div v-if="activeTab === 'create'" class="absolute bottom-0 left-1/2 -translate-x-1/2 w-8 h-1 bg-indigo-600 rounded-full"></div>
      </button>
    </nav>

    <!-- Main Content -->
    <main class="flex-1 flex overflow-hidden lg:flex-row flex-col">
      
      <!-- Gallery Column -->
      <section v-show="activeTab === 'gallery' || isDesktop" class="flex-1 overflow-y-auto scroll-smooth p-4 md:p-6 gallery-container">
        <!-- Search & Control -->
        <div class="max-w-7xl mx-auto mb-8">
           <div class="flex flex-col md:flex-row gap-4 items-center">
             <div class="relative flex-1 group w-full">
               <Search class="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400 group-focus-within:text-indigo-500 transition-colors" />
               <input v-model="searchKeyword" @keyup.enter="fetchImages(true)" type="text" placeholder="搜索关键词..." 
                 class="w-full h-14 pl-12 pr-6 bg-white dark:bg-zinc-900/50 rounded-2xl border border-black/5 dark:border-white/5 focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-500 transition-all outline-none text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-600" />
             </div>
           </div>
           
           <!-- Active Filters -->
           <div v-if="selectedFilters.folder || selectedFilters.model" class="mt-4 flex flex-wrap gap-2">
             <span v-if="selectedFilters.folder" @click="selectedFilters.folder = null; fetchImages(true)" class="px-3 py-1.5 bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 rounded-lg text-xs font-bold border border-indigo-200 dark:border-indigo-500/20 cursor-pointer hover:bg-indigo-100 transition-colors">
               文件夹: {{ selectedFilters.folder }} ✕
             </span>
           </div>
        </div>

        <!-- Masonry-like Grid (Now Real Grid) -->
        <div class="max-w-7xl mx-auto grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
          <div v-for="img in images" :key="img.file_path" 
            @click="viewDetail(img)"
            class="relative group rounded-2xl overflow-hidden cursor-zoom-in bg-gray-200 dark:bg-zinc-900 hover:ring-4 hover:ring-indigo-500/20 transition-all duration-300 shadow-sm aspect-[2/3] object-cover will-change-transform transform-gpu">
            <img :src="'/api/image/thumb?size=512&path=' + encodeURIComponent(img.file_path)" 
              loading="lazy"
              @load="onImageLoad(img)"
              decoding="async"
              draggable="false"
              class="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105" />
            <div class="absolute inset-x-0 bottom-0 p-4 bg-gradient-to-t from-black/60 to-transparent opacity-0 group-hover:opacity-100 transition-opacity">
              <p class="text-white text-xs truncate font-medium">{{ img.file_name }}</p>
            </div>
          </div>
        </div>
        
        <!-- Infinite Scroll Sentinel -->
        <div class="flex justify-center py-8" ref="loadSentinel">
          <Loader2 v-if="loading" class="w-8 h-8 animate-spin text-indigo-500" />
          <p v-else-if="!hasMore" class="text-gray-400 text-sm italic">已经到底啦~</p>
        </div>
      </section>

      <!-- Generate Column (Resizable) -->
      <section v-show="activeTab === 'create' || isDesktop" 
        :style="{ width: isDesktop ? settingsWidth + 'px' : '100%' }"
        class="h-full md:h-auto flex-shrink-0 bg-white dark:bg-[#111216] border-l border-black/5 dark:border-white/5 flex flex-col overflow-hidden shadow-2xl z-10 relative">
        
        <!-- Resize Handle (Desktop Only) -->
        <div v-if="isDesktop" @mousedown="startResize" 
             class="absolute left-0 top-0 bottom-0 w-1 bg-transparent hover:bg-indigo-500/50 cursor-ew-resize z-50 flex items-center justify-center group transition-colors">
             <div class="w-[1px] h-8 bg-gray-300 dark:bg-white/20 group-hover:bg-indigo-400"></div>
        </div>

        <!-- Hidden File Input for drag/drop import proxy -->
        <input type="file" ref="fileInput" accept="image/*" class="hidden" @change="onFileChanged" />

        <div class="p-6 flex-1 overflow-y-auto space-y-6 pb-32">
          <div class="flex items-center justify-between">
            <h2 class="text-lg font-black uppercase tracking-widest text-[#6366f1]">参数控制</h2>
             <div class="flex items-center gap-2">
               <div class="w-2 h-2 rounded-full" :class="comfyStatus.connected ? 'bg-green-500' : 'bg-red-500'"></div>
               <span class="text-[10px] font-bold text-gray-400 uppercase">{{ comfyStatus.connected ? '已连接' : '未连接' }}</span>
            </div>
          </div>
          
          <!-- Queue & Progress -->
          <div v-if="queueData.pending.length > 0 || isGenerating" class="bg-indigo-50 dark:bg-indigo-900/10 rounded-xl p-4 border border-indigo-100 dark:border-indigo-500/10 space-y-3">
             <div class="flex justify-between items-center">
                <span class="text-xs font-bold text-indigo-600 dark:text-indigo-400 flex items-center gap-2">
                    <Loader2 class="w-3 h-3 animate-spin" />
                    正在执行任务 ({{ queueData.pending.length }})
                </span>
                <span class="text-[10px] font-mono text-gray-400">{{ queueData.progress }}%</span>
             </div>
             <!-- Progress Bar -->
             <div class="h-1.5 w-full bg-gray-200 dark:bg-white/10 rounded-full overflow-hidden">
                <div class="h-full bg-indigo-500 transition-all duration-300" :style="{ width: queueData.progress + '%' }"></div>
             </div>
             <!-- Task List (Simplified) -->
             <div class="space-y-1.5 pt-1">
                 <div v-for="(task, i) in queueData.pending.slice(0, 3)" :key="i" class="text-[10px] text-gray-500 flex items-start gap-2">
                    <span class="w-4 h-4 rounded-full bg-white dark:bg-white/10 flex-shrink-0 flex items-center justify-center font-mono text-[8px] mt-0.5">{{ i + 1 }}</span>
                    <div class="flex flex-col min-w-0 flex-1">
                        <span class="truncate font-medium text-gray-600 dark:text-gray-300">{{ task.prompt ? (task.prompt.slice(0, 20) + (task.prompt.length > 20 ? '...' : '')) : '生成任务' }}</span>
                        <span v-if="task.lora_info" class="text-[9px] text-indigo-500 truncate font-mono bg-indigo-50 dark:bg-indigo-500/10 px-1 rounded inline-block w-fit mt-0.5">LoRA: {{ task.lora_info }}</span>
                    </div>
                 </div>
                 <div v-if="queueData.pending.length > 3" class="text-[10px] text-gray-400 pl-6">...还有 {{ queueData.pending.length - 3 }} 个任务</div>
             </div>
          </div>

          <!-- Model Select -->
          <div class="space-y-2">
            <label class="text-xs font-black text-gray-500 uppercase">基础模型</label>
            <select v-model="genParams.model" class="w-full h-12 px-4 bg-gray-50 dark:bg-zinc-900 rounded-xl border border-black/5 dark:border-white/5 outline-none focus:border-indigo-500 transition-all font-medium text-gray-900 dark:text-gray-200">
              <option v-for="m in filterData.models" :key="m" :value="m">{{ m }}</option>
            </select>
          </div>

          <!-- LoRA Select & Weight -->
          <div class="space-y-2">
            <label class="text-xs font-black text-gray-500 uppercase">LoRA 模型 & 权重</label>
            <div class="flex gap-2">
                <select v-model="genParams.lora" class="flex-[3] h-12 px-4 bg-gray-50 dark:bg-zinc-900 rounded-xl border border-black/5 dark:border-white/5 outline-none focus:border-indigo-500 transition-all font-medium text-xs text-gray-900 dark:text-gray-200">
                  <option value="">未选择 LoRA</option>
                  <option v-for="l in filterData.loras" :key="l" :value="l">{{ l }}</option>
                </select>
                <input v-model.number="genParams.lora_weight" type="number" step="0.01" min="0" max="2" placeholder="权重" class="flex-1 h-12 px-4 bg-gray-50 dark:bg-zinc-900 rounded-xl border border-black/5 dark:border-white/5 outline-none text-center text-gray-900 dark:text-gray-200" />
            </div>
          </div>

          <!-- Prompt -->
          <div class="space-y-2 relative">
            <div class="flex items-center justify-between">
              <label class="text-xs font-black text-indigo-500 uppercase">正向提示词</label>
              <div class="flex items-center gap-2">
                 <button @click="handleClipboardImport('prompt')" class="text-[10px] font-bold bg-white dark:bg-white/10 px-2 py-1 rounded-md border border-black/5 hover:border-indigo-500/50 transition-all flex items-center gap-1">
                    <ImageIcon class="w-3 h-3" /> 剪切板导入
                 </button>
                 <button @click="aiTarget = 'positive'; showAIModal = true" class="text-[10px] font-bold bg-indigo-500/10 text-indigo-500 px-2 py-1 rounded-md hover:bg-indigo-500/20 transition-all">AI 优化</button>
              </div>
            </div>
            <textarea v-model="genParams.prompt" @paste="(e) => handlePromptPaste(e, 'prompt')" placeholder="描述你想生成的画面... (支持粘贴图片)" 
              class="w-full h-32 p-4 bg-gray-50 dark:bg-zinc-900 rounded-2xl border border-black/5 dark:border-white/5 outline-none focus:border-indigo-500 transition-all resize-none text-sm leading-relaxed text-gray-900 dark:text-gray-200 placeholder-gray-400 dark:placeholder-gray-600"></textarea>
          </div>

          <!-- Negative Prompt -->
          <div class="space-y-2 relative">
             <div class="flex items-center justify-between">
              <label class="text-xs font-black text-red-500 uppercase">反向提示词</label>
              <button @click="aiTarget = 'negative'; showAIModal = true" class="text-[10px] font-bold bg-red-500/10 text-red-500 px-2 py-1 rounded-md hover:bg-red-500/20 transition-all">AI 优化</button>
            </div>
            <textarea v-model="genParams.negative_prompt" placeholder="不想出现的元素..." 
              class="w-full h-24 p-4 bg-gray-50 dark:bg-zinc-900 rounded-2xl border border-black/5 dark:border-white/5 outline-none focus:border-red-500 transition-all resize-none text-sm leading-relaxed italic text-gray-500 dark:text-gray-400"></textarea>
          </div>

          <!-- Grid Params -->
          <div class="grid grid-cols-2 gap-4">
             <div class="space-y-2">
                <label class="text-xs font-black text-gray-500 uppercase">采样器 (Sampler)</label>
                <select v-model="genParams.sampler" class="w-full h-12 px-4 bg-gray-50 dark:bg-zinc-900 rounded-xl border border-black/5 dark:border-white/5 outline-none text-gray-900 dark:text-gray-200">
                  <option v-for="s in filterData.samplers" :key="s" :value="s">{{ s }}</option>
                </select>
             </div>
             <div class="space-y-2">
                <label class="text-xs font-black text-gray-500 uppercase">调度器 (Scheduler)</label>
                <select v-model="genParams.scheduler" class="w-full h-12 px-4 bg-gray-50 dark:bg-zinc-900 rounded-xl border border-black/5 dark:border-white/5 outline-none text-gray-900 dark:text-gray-200">
                  <option v-for="s in filterData.schedulers" :key="s" :value="s">{{ s }}</option>
                </select>
             </div>
             <div class="space-y-2">
                <label class="text-xs font-black text-gray-500 uppercase">渲染步数</label>
                <input v-model.number="genParams.steps" type="number" class="w-full h-12 px-4 bg-gray-50 dark:bg-zinc-900 rounded-xl border border-black/5 dark:border-white/5 outline-none text-gray-900 dark:text-gray-200" />
             </div>
             <div class="space-y-2">
                <label class="text-xs font-black text-gray-500 uppercase">CFG 指数</label>
                <input v-model.number="genParams.cfg" type="number" step="0.5" class="w-full h-12 px-4 bg-gray-50 dark:bg-zinc-900 rounded-xl border border-black/5 dark:border-white/5 outline-none text-gray-900 dark:text-gray-200" />
             </div>
             <div class="space-y-2 col-span-2">
                <label class="text-xs font-black text-gray-500 uppercase">随机种子 (Seed)</label>
                <div class="flex gap-2 items-center">
                    <input v-model.number="genParams.seed" :disabled="isRandomSeed" type="number" class="flex-1 h-12 px-4 bg-gray-50 dark:bg-zinc-900 disabled:opacity-50 rounded-xl border border-black/5 dark:border-white/5 outline-none font-mono text-gray-900 dark:text-gray-200" />
                    <label class="flex items-center gap-2 h-12 px-4 bg-gray-50 dark:bg-zinc-900 rounded-xl border border-black/5 dark:border-white/5 cursor-pointer select-none">
                        <input type="checkbox" v-model="isRandomSeed" @change="genParams.seed = isRandomSeed ? -1 : (genParams.seed === -1 ? 0 : genParams.seed)" class="w-4 h-4 text-indigo-600 rounded focus:ring-indigo-500" />
                        <span class="text-xs font-bold text-gray-500">随机</span>
                    </label>
                </div>
             </div>
             
             <!-- Advanced Settings -->
             <div class="space-y-2">
                <label class="text-xs font-black text-gray-500 uppercase">生成张数 (Batch Count)</label>
                <input v-model.number="genParams.batch_size" type="number" min="1" max="8" class="w-full h-12 px-4 bg-gray-50 dark:bg-zinc-900 rounded-xl border border-black/5 dark:border-white/5 outline-none text-gray-900 dark:text-gray-200" />
             </div>
          </div>
        </div>

        <div class="p-6 bg-white dark:bg-[#111216] border-t border-black/5 dark:border-white/5 fixed bottom-0 left-0 right-0 z-50 md:static md:inset-auto">
           <button @click="submitGeneration" 
            :disabled="!comfyStatus.connected || isGenerating"
            class="w-full h-14 bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-400 text-white rounded-2xl font-black uppercase tracking-widest shadow-xl shadow-indigo-600/20 transition-all active:scale-95 flex items-center justify-center gap-3">
             <Sparkles v-if="!isGenerating" class="w-6 h-6" />
             <Loader2 v-else class="w-6 h-6 animate-spin" />
             {{ isGenerating ? '发送中...' : '开始渲染图像' }}
           </button>
        </div>
      </section>
    </main>

    <!-- Modal: Detail View (Modern Glass Overlay) -->
    <transition name="fade">
      <div v-if="selectedImage" class="fixed inset-0 z-[100] flex flex-col items-center justify-center p-0 md:p-6 overflow-y-auto md:overflow-hidden scroll-smooth">
        <div class="absolute inset-0 bg-black/60 backdrop-blur-xl" @click="selectedImage = null"></div>
        
        <!-- Modal Card: Scrollable on Mobile, Fixed on Desktop -->
        <div class="relative w-full min-h-full md:h-full md:min-h-0 md:max-w-[95vw] md:max-h-[92vh] bg-transparent md:bg-white md:dark:bg-[#0b0c10] md:rounded-[32px] overflow-visible md:overflow-hidden flex flex-col md:flex-row shadow-2xl">
          <!-- Close Button (Fixed on Mobile, Absolute on Desktop) -->
          <button @click="selectedImage = null; console.groupEnd()" class="fixed md:absolute top-4 right-4 z-[60] p-2.5 bg-gray-100 hover:bg-gray-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 rounded-full text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-zinc-700 transition-all active:scale-95 shadow-sm">
            <X class="w-5 h-5" />
          </button>

          <!-- Full Screen Blurred Background (Underlay) -->
          <div class="absolute inset-0 z-0 overflow-hidden pointer-events-none">
             <!-- Removed dimming layer to make typical colors visible -->
             <div class="absolute inset-0 opacity-100 blur-[80px] scale-125 saturate-200 transform-gpu transition-all duration-700"
                  :style="{ backgroundImage: `url(/api/image/thumb?size=512&path=${encodeURIComponent(selectedImage.file_path)})`, backgroundPosition: 'center', backgroundSize: 'cover' }"></div>
          </div>

          <!-- Image Area -->
          <div class="relative flex-none md:flex-1 z-10 flex items-center justify-center overflow-visible md:overflow-hidden w-full min-h-[40vh] md:min-h-0 bg-gray-50 dark:bg-zinc-900/50">
            <!-- Loading State -->
            <!-- Loading Spinner (Overlay on top of blurred thumb if needed, but maybe cleaner without) -->
            <div v-if="detailImageLoading && !detailImageError" class="absolute inset-0 flex items-center justify-center z-20 pointer-events-none">
                <Loader2 class="w-10 h-10 animate-spin text-white/50 drop-shadow-md" />
            </div>
            
            <!-- Error State -->
            <div v-if="detailImageError" class="absolute inset-0 flex flex-col items-center justify-center z-20 gap-2 text-gray-400">
                <ImageIcon class="w-12 h-12 opacity-50" />
                <span class="text-xs font-bold">加载失败</span>
            </div>

            <!-- Progressive Loading Container -->
            <div class="relative w-full h-full flex items-center justify-center">
                <!-- Data: Low Res Placeholder (Instant) -->
                <img :src="'/api/image/thumb?size=512&path=' + encodeURIComponent(selectedImage.file_path)"
                     class="absolute inset-0 w-full h-full object-contain filter blur-sm transform scale-105 transition-opacity duration-700"
                     :class="{ 'opacity-0': !detailImageLoading }" 
                     style="max-width: 100%;" />
                
                <!-- Data: High Res (Fade In) -->
                <img :src="'/api/image/raw?path=' + encodeURIComponent(selectedImage.file_path)" 
                     fetchpriority="high"
                     loading="eager"
                     @load="onDetailImageLoad"
                     @error="detailImageError = true; detailImageLoading = false; console.error('[Detail] Image failed to load')"
                     class="relative z-10 w-full h-auto md:h-full md:object-contain drop-shadow-2xl transition-opacity duration-300"
                     :class="{ 'opacity-0': detailImageLoading, 'opacity-100': !detailImageLoading }"
                     style="max-width: 100%;" />
            </div>
            
            <!-- Navigation -->
            <button @click="navigateImage(-1)" class="absolute left-2 md:left-6 top-1/2 -translate-y-1/2 z-20 p-2 md:p-4 bg-white/10 hover:bg-white/20 rounded-full backdrop-blur-md border border-white/20">
              <ChevronLeft class="w-6 h-6 md:w-8 md:h-8 text-white" />
            </button>
            <button @click="navigateImage(1)" class="absolute right-2 md:right-6 top-1/2 -translate-y-1/2 z-20 p-2 md:p-4 bg-white/10 hover:bg-white/20 rounded-full backdrop-blur-md border border-white/20">
              <ChevronRight class="w-6 h-6 md:w-8 md:h-8 text-white" />
            </button>
          </div>

          <!-- Meta Area -->
          <div class="w-full md:w-[450px] flex-shrink-0 backdrop-blur-md flex flex-col overflow-visible md:overflow-hidden border-t md:border-t-0 md:border-l border-white/10 z-20 transition-colors duration-300 bg-white/95 dark:bg-[#0b0c10]/95 md:bg-transparent"
               :style="{ backgroundColor: isDesktop ? (isDark ? 'rgba(11, 12, 16, 0.95)' : 'rgba(255, 255, 255, 0.95)') : '' }">
            <div class="p-8 pt-8 md:pt-20 flex-1 h-auto md:overflow-y-auto space-y-8 scroll-area">
              <div v-if="!meta" class="h-64 flex flex-col items-center justify-center gap-4">
                <Loader2 class="w-8 h-8 animate-spin text-indigo-500" />
                <span class="text-xs font-black uppercase text-gray-500 tracking-widest">读取元数据...</span>
              </div>
              <div v-else class="space-y-8">
                <div v-if="meta.prompt" class="space-y-3">
                   <label class="text-[10px] font-black text-indigo-500 uppercase tracking-[0.3em] block">正向提示词</label>
                   <div class="text-sm leading-relaxed text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-zinc-900 p-5 rounded-2xl border border-black/5 dark:border-white/5 select-all">{{ meta.prompt }}</div>
                </div>
                <div v-if="meta.negative_prompt" class="space-y-3">
                   <label class="text-[10px] font-black text-red-500 uppercase tracking-[0.3em] block">反向提示词</label>
                   <div class="text-sm leading-relaxed text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-zinc-900 p-5 rounded-2xl border border-black/5 dark:border-white/5 select-all italic">{{ meta.negative_prompt }}</div>
                </div>

                <!-- Param Grid -->
                <div class="pt-8 border-t border-black/5 dark:border-white/10 grid grid-cols-2 lg:grid-cols-3 gap-3">
                   <div v-for="(v, k) in { 
                      '尺寸': getImageDimensions(),
                      '渲染步数': meta.params?.Steps || meta.params?.steps,
                      'CFG': meta.params?.['CFG scale'] || meta.params?.cfg,
                      '采样器': meta.params?.Sampler || meta.params?.sampler_name,
                      '调度器': meta.params?.Scheduler || meta.params?.scheduler,
                      '随机种子': meta.params?.Seed || meta.params?.seed,
                      '基础模型': meta.params?.Model || meta.params?.model,
                      'LoRA': meta.loras ? meta.loras.join(', ') : '-'
                   }" :key="k" class="p-3 bg-gray-50 dark:bg-zinc-900 rounded-xl border border-black/5 dark:border-white/5 flex flex-col justify-center">
                      <div class="text-[8px] font-bold text-gray-400 uppercase mb-0.5 truncate">{{ k }}</div>
                      <div class="text-xs font-mono font-bold truncate" :title="v">{{ v || '-' }}</div>
                   </div>
                </div>
              </div>
            </div>
            
            <!-- Sticky Actions -->
            <div class="p-8 border-t border-black/5 dark:border-white/10 flex flex-col gap-3">
               <button @click="applyToWorkspace" class="w-full h-14 bg-indigo-600 text-white rounded-2xl font-bold flex items-center justify-center gap-3 active:scale-95 transition-all shadow-lg shadow-indigo-500/20">
                 <Copy class="w-5 h-5" />
                 <span>复写至工作区</span>
               </button>
               <button @click="confirmDelete" class="w-full h-14 bg-red-600/10 text-red-600 rounded-2xl font-bold flex items-center justify-center gap-3 hover:bg-red-600 hover:text-white transition-all active:scale-95">
                 <Trash2 class="w-5 h-5" />
                 <span>放入回收站</span>
               </button>
            </div>
          </div>
        </div>
      </div>
    </transition>



    <!-- Modal: Filters (Desktop & Mobile) -->
    <transition name="fade">
      <div v-if="showFilters" class="fixed inset-0 z-[110] flex items-center justify-center p-6">
        <div class="absolute inset-0 bg-black/60 backdrop-blur-sm" @click="showFilters = false"></div>
        <div class="relative w-full max-w-md bg-white dark:bg-[#0b0c10] rounded-[32px] shadow-2xl overflow-hidden flex flex-col max-h-[80vh]">
          <div class="p-6 border-b border-black/5 dark:border-white/5 flex items-center justify-between">
            <h3 class="text-xl font-black uppercase tracking-tight">筛选图片</h3>
            <button @click="showFilters = false" class="p-2 hover:bg-black/5 dark:hover:bg-white/5 rounded-full transition-all">
              <X class="w-5 h-5" />
            </button>
          </div>
          
          <div class="flex-1 overflow-y-auto p-6 space-y-6">
            <!-- Folders -->
            <div class="space-y-3">
              <label class="text-xs font-black text-gray-500 uppercase">文件夹</label>
              <div class="flex flex-wrap gap-2">
                <button v-for="f in filterData.folders" :key="f"
                  @click="selectedFilters.folder = selectedFilters.folder === f ? null : f"
                  class="px-4 py-2 rounded-xl text-xs font-bold border transition-all"
                  :class="selectedFilters.folder === f ? 'bg-indigo-600 text-white border-indigo-600 shadow-lg shadow-indigo-500/30' : 'bg-gray-50 dark:bg-white/5 border-black/5 dark:border-white/10 hover:border-indigo-500/50'">
                  {{ f }}
                </button>
              </div>
            </div>

            <!-- Models -->
            <div class="space-y-3">
              <label class="text-xs font-black text-gray-500 uppercase">生成模型</label>
              <select v-model="selectedFilters.model" class="w-full h-12 px-4 bg-gray-50 dark:bg-zinc-900 rounded-xl border border-black/5 dark:border-white/5 outline-none focus:border-indigo-500 transition-all font-medium text-sm text-gray-900 dark:text-gray-200">
                <option :value="null">全部模型</option>
                <option v-for="m in filterData.models" :key="m" :value="m">{{ m }}</option>
              </select>
            </div>

            <!-- LoRAs -->
            <div class="space-y-3">
              <label class="text-xs font-black text-gray-500 uppercase">LoRA 模型</label>
              <select v-model="selectedFilters.lora" class="w-full h-12 px-4 bg-gray-50 dark:bg-zinc-900 rounded-xl border border-black/5 dark:border-white/5 outline-none focus:border-indigo-500 transition-all font-medium text-sm text-gray-900 dark:text-gray-200">
                <option :value="null">全部 LoRA</option>
                <option v-for="l in filterData.loras" :key="l" :value="l">{{ l }}</option>
              </select>
            </div>
          </div>

          <div class="p-6 border-t border-black/5 dark:border-white/5 flex gap-3">
             <button @click="selectedFilters.folder = null; selectedFilters.model = null; selectedFilters.lora = null; fetchImages(true)" class="flex-1 h-12 rounded-2xl font-bold text-gray-500 hover:bg-gray-100 dark:hover:bg-white/5 transition-all">
               重置
             </button>
             <button @click="showFilters = false; fetchImages(true)" class="flex-[2] h-12 bg-indigo-600 text-white rounded-2xl font-black uppercase tracking-widest shadow-xl shadow-indigo-600/20 active:scale-95 transition-all">
               应用筛选
             </button>
          </div>
        </div>
      </div>
    </transition>

    <!-- Modal: AI Optimize Dialog -->
    <transition name="fade">
        <div v-if="showAIModal" class="fixed inset-0 z-[120] flex items-center justify-center p-6">
            <div class="absolute inset-0 bg-indigo-950/40 backdrop-blur-2xl" @click="showAIModal = false"></div>
            <div class="relative w-full max-w-lg bg-white dark:bg-[#0b0c10] rounded-[32px] shadow-2xl overflow-hidden p-8 space-y-6">
                <div class="flex items-center gap-4">
                  <div class="w-12 h-12 bg-indigo-600 rounded-2xl flex items-center justify-center shadow-indigo-500/20 shadow-xl">
                    <Sparkles class="text-white w-6 h-6" />
                  </div>
                  <div>
                    <h3 class="text-xl font-black uppercase tracking-tight">AI 智能辅助</h3>
                    <p class="text-xs text-gray-400 font-bold uppercase">{{ aiTarget === 'positive' ? '正向画面增强' : '反向精准避雷' }}</p>
                  </div>
                </div>
                
                <textarea v-model="aiInput" @keyup.enter="runAIOptimize" placeholder="输入你的构思或修改要求（支持中文口语）..." 
                    class="w-full h-40 p-6 bg-gray-50 dark:bg-zinc-900 rounded-2xl border border-black/5 dark:border-white/5 outline-none focus:border-indigo-500 transition-all text-sm leading-relaxed text-gray-900 dark:text-gray-200"></textarea>
                
                <div class="flex gap-4">
                  <button @click="showAIModal = false" class="flex-1 h-14 rounded-2xl font-bold text-gray-500 hover:bg-gray-100 dark:hover:bg-zinc-800 transition-all">取消</button>
                  <button @click="runAIOptimize" class="flex-[2] h-14 bg-indigo-600 text-white rounded-2xl font-black uppercase tracking-widest shadow-xl shadow-indigo-600/20 active:scale-95 transition-all flex items-center justify-center gap-2">
                    <Send class="w-5 h-5" />
                    立即处理
                  </button>
                </div>
            </div>
        </div>
    </transition>
  </div>
</template>

<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&family=Outfit:wght@500;700;900&display=swap');

html, body, #app {
  height: 100%;
  transition: background-color 0.3s ease;
}

/* Force Dark Mode Background if Tailwind fails */
html.dark body {
    background-color: #0b0c10 !important;
    color: #ffffff;
}

::-webkit-scrollbar {
  width: 6px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: rgba(0,0,0,0.1);
  border-radius: 10px;
}
.dark ::-webkit-scrollbar-thumb {
  background: rgba(255,255,255,0.1);
}

.fade-enter-active, .fade-leave-active {
  transition: opacity 0.3s ease;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}

.font-outfit {
  font-family: 'Outfit', sans-serif;
}

/* Custom Masonry Column Spacing */
.gallery-container {
  scrollbar-gutter: stable;
}

@keyframes shimmer {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}

.animate-shimmer {
  position: relative;
  overflow: hidden;
}
.animate-shimmer::after {
  content: "";
  position: absolute;
  top: 0; right: 0; bottom: 0; left: 0;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.05), transparent);
  animation: shimmer 1.5s infinite;
}
</style>
