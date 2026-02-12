<script setup>
import { ref, reactive, onMounted, onUnmounted, watch } from 'vue'
import { Settings2, Zap, Moon, Sun, Search } from 'lucide-vue-next'

// Components
import ImageList from './components/ImageList.vue'
import ImageViewer from './components/ImageViewer.vue'
import FilterModal from './components/FilterModal.vue'
import InfoPanel from './components/InfoPanel.vue'

// --- State ---
const images = ref([])
const loading = ref(false)
const searchKeyword = ref("")
const page = ref(1)
const hasMore = ref(true)
const isDark = ref(false)
const selectedImage = ref(null)
const meta = ref(null)
const detailImageError = ref(false)
const showFilters = ref(false)
const debugMsg = ref("") // Debugging
const authChecked = ref(false)
const authRequired = ref(false)
const isAuthenticated = ref(false)
const authCode = ref("")
const authError = ref("")
const appInitialized = ref(false)
const lastGallerySyncAt = ref(0)
const syncInProgress = ref(false)

// --- Resize & Mobile State ---
const leftWidth = ref(parseInt(localStorage.getItem('aimg_left_width')) || 240)
const rightWidth = ref(parseInt(localStorage.getItem('aimg_right_width')) || 320)
const gridCols = ref(window.innerWidth < 768 ? 2 : 3)
const isResizingLeft = ref(false)
const isResizingRight = ref(false)
const startX = ref(0)
const startLeftWidth = ref(0)
const startRightWidth = ref(0)

const isMobile = ref(false)
const showMobileInfo = ref(false) // For mobile drawer

const checkMobile = () => {
  isMobile.value = window.innerWidth < 768
}

// Watch sidebar widths for persistence
watch(leftWidth, (v) => localStorage.setItem('aimg_left_width', v))
watch(rightWidth, (v) => localStorage.setItem('aimg_right_width', v))

// --- Filters & Gen Params (Restored) ---
const filterData = reactive({ folders: [], models: [], loras: [], samplers: [], schedulers: [] })
const selectedFilters = reactive({ folder: null, model: null, lora: null })

const isGenerating = ref(false)
const comfyStatus = reactive({ connected: false, queue_remaining: 0, active_count: 0 })

// Default params
const defaultGenParams = {
  model: "", prompt: "", negative_prompt: "",
  resolution: "512x768", sampler: "", scheduler: "",
  steps: 20, cfg: 7.0, lora: "", lora_weight: 1.0, seed: -1, batch_size: 1
}

// Load from localStorage or use defaults
const savedParams = localStorage.getItem('aimg_gen_params')
const initialGenParams = savedParams ? { ...defaultGenParams, ...JSON.parse(savedParams) } : defaultGenParams
const genParams = reactive(initialGenParams)

const isRandomSeed = ref(localStorage.getItem('aimg_is_random_seed') !== 'false') // Default to true if not set
const wheelAction = ref(localStorage.getItem('wheelAction') || 'zoom')

// Watchers for persistence
watch(genParams, (newVal) => {
    localStorage.setItem('aimg_gen_params', JSON.stringify(newVal))
}, { deep: true })

watch(isRandomSeed, (newVal) => {
    localStorage.setItem('aimg_is_random_seed', newVal)
})

watch(wheelAction, (val) => localStorage.setItem('wheelAction', val))

// --- Theme (Restored) ---
const initTheme = () => {
    isDark.value = localStorage.getItem('theme') === 'dark' || (!localStorage.getItem('theme') && window.matchMedia('(prefers-color-scheme: dark)').matches)
    document.documentElement.classList.toggle('dark', isDark.value)
}
const toggleTheme = () => {
    isDark.value = !isDark.value
    localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
    document.documentElement.classList.toggle('dark', isDark.value)
    console.log("Theme toggled. Is Dark?", isDark.value, "HTML class list:", document.documentElement.classList)
}

// --- Resize Functions (Desktop Only) ---
const startResizeLeft = (e) => {
  if (isMobile.value) return
  isResizingLeft.value = true
  startX.value = e.clientX || e.touches[0].clientX
  startLeftWidth.value = leftWidth.value
  document.body.classList.add('select-none')
  document.addEventListener('mousemove', doResizeLeft)
  document.addEventListener('mouseup', stopResizeLeft)
}
const doResizeLeft = (e) => {
  if (!isResizingLeft.value) return
  const delta = (e.clientX || e.touches[0].clientX) - startX.value
  leftWidth.value = Math.max(150, Math.min(1600, startLeftWidth.value + delta))
}
const stopResizeLeft = () => {
  isResizingLeft.value = false
  document.body.classList.remove('select-none')
  document.removeEventListener('mousemove', doResizeLeft)
  document.removeEventListener('mouseup', stopResizeLeft)
}

const startResizeRight = (e) => {
  if (isMobile.value) return
  isResizingRight.value = true
  startX.value = e.clientX || e.touches[0].clientX
  startRightWidth.value = rightWidth.value
  document.body.classList.add('select-none')
  document.addEventListener('mousemove', doResizeRight)
  document.addEventListener('mouseup', stopResizeRight)
}
const doResizeRight = (e) => {
  if (!isResizingRight.value) return
  const delta = startX.value - (e.clientX || e.touches[0].clientX)
  rightWidth.value = Math.max(250, Math.min(1600, startRightWidth.value + delta))
}
const stopResizeRight = () => {
  isResizingRight.value = false
  document.body.classList.remove('select-none')
  document.removeEventListener('mousemove', doResizeRight)
  document.removeEventListener('mouseup', stopResizeRight)
}

const handleAuthRequired = () => {
  if (!authRequired.value) return
  isAuthenticated.value = false
  authError.value = "登录已过期，请重新输入验证码"
}

const syncGallery = async () => {
  if (authRequired.value && !isAuthenticated.value) return
  if (syncInProgress.value) return
  syncInProgress.value = true
  try {
    try {
      await fetch('/api/scan', { method: 'POST' })
    } catch (e) {}
    // 如果当前正在加载，等待片刻避免刷新被跳过
    for (let i = 0; i < 20 && loading.value; i++) {
      await new Promise(r => setTimeout(r, 100))
    }
    await fetchImages(true, true, true)
    lastGallerySyncAt.value = Date.now()
  } finally {
    syncInProgress.value = false
  }
}

const initAppData = () => {
  if (appInitialized.value) return
  appInitialized.value = true
  fetchFilters()
  syncGallery()
  pollComfyStatus()
}

const checkAuthStatus = async () => {
  authError.value = ""
  try {
    const resp = await fetch('/api/auth/status', { cache: 'no-store' })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()
    authRequired.value = !!data.requires_auth
    isAuthenticated.value = authRequired.value ? !!data.authenticated : true
  } catch (e) {
    // 如果后端未实现状态接口，则保持兼容：直接放行
    authRequired.value = false
    isAuthenticated.value = true
  } finally {
    authChecked.value = true
  }
}

const submitAuthLogin = async () => {
  const code = authCode.value.trim()
  if (!code) {
    authError.value = "请输入验证码"
    return
  }
  authError.value = ""
  try {
    const resp = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code })
    })
    if (!resp.ok) {
      authError.value = "验证码错误"
      return
    }
    const data = await resp.json()
    if (data?.authenticated) {
      isAuthenticated.value = true
      authCode.value = ""
      authError.value = ""
      initAppData()
    } else {
      authError.value = "登录失败，请重试"
    }
  } catch (e) {
    authError.value = `登录失败: ${e.message}`
  }
}

// --- API Calls ---
const fetchImages = async (isRefresh = false, skipScan = false, silentRefresh = false) => {
  if (authRequired.value && !isAuthenticated.value) return
  if (loading.value) return

  let requestPage = page.value
  if (isRefresh) {
    if (!skipScan) {
      try {
        await fetch('/api/scan', { method: 'POST' })
      } catch (e) {}
    }
    requestPage = 1
    lastGallerySyncAt.value = Date.now()
  }
  if (!isRefresh && !hasMore.value) return
  loading.value = true
  try {
    const query = new URLSearchParams({
      keyword: searchKeyword.value, page: requestPage,
      folder: selectedFilters.folder || "", model: selectedFilters.model || "", lora: selectedFilters.lora || ""
    })
    const url = `/api/images?${query.toString()}`
    // debugMsg.value = `Fetching: ${url}` // Verbose
    const response = await fetch(url)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const data = await response.json()
    if (isRefresh) {
      const refreshed = Array.isArray(data.images) ? data.images : []
      const selectedPath = selectedImage.value?.file_path || ""
      images.value = refreshed
      hasMore.value = !!data.has_more
      page.value = refreshed.length > 0 ? 2 : 1

      if (!refreshed.length) {
        selectedImage.value = null
        meta.value = null
        debugMsg.value = `暂无数据 (API返回空数组)`
      } else {
        if (selectedPath) {
          const stillExists = refreshed.find(i => i.file_path === selectedPath)
          if (stillExists) {
            // Keep current object reference to avoid resetting zoom/pan while viewing the same image.
            if (selectedImage.value?.file_path !== stillExists.file_path) {
              selectedImage.value = stillExists
            } else {
              Object.assign(selectedImage.value, stillExists)
            }
          } else if (!silentRefresh || !isMobile.value) {
            viewDetail(refreshed[0])
          }
        } else if (!isMobile.value) {
          viewDetail(refreshed[0])
        }
        debugMsg.value = ""
      }
      return
    }

    if (data.images.length === 0) {
      hasMore.value = false
      if (requestPage === 1) debugMsg.value = `暂无数据 (API返回空数组)`
    } else {
      const existingPaths = new Set(images.value.map(i => i.file_path))
      const uniqueNewImages = data.images.filter(i => !existingPaths.has(i.file_path))
      if (uniqueNewImages.length > 0) {
        images.value = [...images.value, ...uniqueNewImages]
        page.value++
      }
      
      // Auto-select first image if none selected and on first page load
      if (!selectedImage.value && images.value.length > 0 && !isMobile.value) {
          viewDetail(images.value[0])
      }

      hasMore.value = data.has_more
      debugMsg.value = "" // Clear error if success
    }
  } catch (err) { 
      console.error("Fetch Error:", err) 
      debugMsg.value = `加载失败: ${err.message}`
  }
  finally { loading.value = false }
}

const fetchFilters = async () => {
  if (authRequired.value && !isAuthenticated.value) return
  try {
    const resp = await fetch('/api/filters')
    const data = await resp.json()
    Object.assign(filterData, data)
    if (!genParams.model && data.models?.[0]) genParams.model = data.models[0]
    if (!genParams.sampler && data.samplers?.[0]) genParams.sampler = data.samplers[0]
    if (!genParams.scheduler && data.schedulers?.[0]) genParams.scheduler = data.schedulers[0]
    fetchComfyInfo()
  } catch (e) {}
}

const fetchComfyInfo = async () => {
  if (authRequired.value && !isAuthenticated.value) return
  try {
    const resp = await fetch('/api/comfy/samplers_schedulers')
    const data = await resp.json()
    if (data.samplers?.length) filterData.samplers = [...new Set([...filterData.samplers, ...data.samplers])].sort()
    if (data.schedulers?.length) filterData.schedulers = [...new Set([...filterData.schedulers, ...data.schedulers])].sort()
  } catch (e) {}
}

const pollComfyStatus = async () => {
  if (authRequired.value && !isAuthenticated.value) {
    setTimeout(pollComfyStatus, 2000)
    return
  }
  try {
    const resp = await fetch('/api/comfy/queue')
    const data = await resp.json()
    comfyStatus.connected = true
    comfyStatus.queue_remaining = data.queue_remaining || 0
    comfyStatus.active_count = data.active_count || 0

    // 与 Python 端对齐：空闲时周期性轻同步，覆盖“外部新增/删除”场景
    if ((comfyStatus.active_count || 0) === 0 && Date.now() - lastGallerySyncAt.value > 12000) {
      syncGallery()
    }
  } catch (e) { 
    comfyStatus.connected = false 
    comfyStatus.queue_remaining = 0
    comfyStatus.active_count = 0
  }
  setTimeout(pollComfyStatus, 2000)
}

const isMetaLoading = ref(false)

const viewDetail = async (img) => {
  if (authRequired.value && !isAuthenticated.value) return
  selectedImage.value = img
  // Don't clear meta immediately to prevent flashing
  // meta.value = null 
  detailImageError.value = false
  isMetaLoading.value = true
  
  try {
    const response = await fetch(`/api/metadata?path=${encodeURIComponent(img.file_path)}&t=${Date.now()}`)
    meta.value = await response.json()
  } catch (err) { 
      meta.value = { prompt: "无法解析该图片的元数据", params: {} } 
  } finally {
      isMetaLoading.value = false
  }
}

const closeDetail = () => {
    selectedImage.value = null
    meta.value = null
}

const deleteImage = async () => {
    if (authRequired.value && !isAuthenticated.value) return
    if (!selectedImage.value) return
    if (!confirm(`确定要将此图片移至回收站吗？\n${selectedImage.value.file_name}`)) return
    
    const path = selectedImage.value.file_path
    try {
        const res = await fetch(`/api/image?path=${encodeURIComponent(path)}`, { method: 'DELETE' })
        const data = await res.json()
        if (data.success) {
            const index = images.value.findIndex(img => img.file_path === path)
            if (index !== -1) {
                // Determine next image to select: prefer the one "before" it (newer), otherwise the one "after" (older)
                let nextIndex = -1
                if (index > 0) nextIndex = index - 1
                else if (images.value.length > 1) nextIndex = 0 // Was first, will become 0
                
                images.value.splice(index, 1)
                
                if (nextIndex !== -1 && images.value.length > 0) {
                    viewDetail(images.value[nextIndex])
                } else {
                    selectedImage.value = null
                    meta.value = null
                }
            }
        }
    } catch (err) { console.error("Delete error:", err) }
}

const applyToWorkspace = () => {
    if (!meta.value) return
    const m = meta.value, p = m.params || {}
    genParams.prompt = m.prompt || ""
    genParams.negative_prompt = m.negative_prompt || ""
    genParams.model = p.Model || p.model || ""
    genParams.steps = parseInt(p.Steps || p.steps) || 20
    genParams.cfg = parseFloat(p['CFG scale'] || p.cfg || p.CFG) || 7.0
    genParams.sampler = p.Sampler || p.sampler_name || ""
    genParams.scheduler = p.Scheduler || p.scheduler || ""
    
    // Resolution
    const w = p.width || p.img_width || (m.tech_info && m.tech_info.width);
    const h = p.height || p.img_height || (m.tech_info && m.tech_info.height);
    
    // Try to parse from resolution string if separate w/h not found
    if ((!w || !h) && m.tech_info && m.tech_info.resolution) {
        const parts = m.tech_info.resolution.split('x');
        if (parts.length === 2) {
            genParams.resolution = m.tech_info.resolution;
        }
    } else if (w && h) {
        genParams.resolution = `${w}x${h}`;
    }
    
    // Seed
    if (p.Seed || p.seed) {
        genParams.seed = Number(p.Seed || p.seed);
        // User requested to keep Random state (don't force set to false)
        // isRandomSeed.value = false; 
    }
    
    // Denoise (Denoising strength)
    if (p.Denoise || p.denoise) {
        // Denoise usually not in simple params but sometimes in tech_info or specific workflows
        // Keep it simple if available
    }
    
    // LoRA (Parse first available LoRA)
    if (m.loras && m.loras.length > 0) {
        // Format usually "Name(Weight)" or "Name:Weight" or just "Name"
        const firstLora = m.loras[0];
        let name = firstLora;
        let weight = 1.0;
        
        // Simple parser
        if (firstLora.includes('(')) {
            const parts = firstLora.split('(');
            name = parts[0].trim();
            const wStr = parts[1].replace(')', '').trim();
            weight = parseFloat(wStr) || 1.0;
        } else if (firstLora.includes(':')) {
            const parts = firstLora.split(':');
            name = parts[0].trim();
            weight = parseFloat(parts[1]) || 1.0;
        }
        
        // Remove extension if present for cleaner matching
        if (name.endsWith('.safetensors') || name.endsWith('.ckpt')) {
            name = name.substring(0, name.lastIndexOf('.'));
        }
        
        // Try to match with available filterData models if possible, or just set it
        // Check if filterData.loras contains a partial match
        if (filterData.loras) {
             const match = filterData.loras.find(l => l.includes(name));
             if (match) name = match;
        }

        genParams.lora = name;
        genParams.lora_weight = weight;
    } else {
        genParams.lora = "";
        genParams.lora_weight = 1.0;
    }
}

const submitGeneration = async () => {
  if (authRequired.value && !isAuthenticated.value) return
  if (!comfyStatus.connected) return
  isGenerating.value = true
  try {
    const payload = { ...genParams, seed: isRandomSeed.value ? -1 : genParams.seed }
    await fetch('/api/comfy/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
  } catch (e) { console.error(e) }
  finally { isGenerating.value = false }
}

const handleImageSwitch = (direction) => {
    if (!selectedImage.value) return
    const currentIndex = images.value.findIndex(img => img.file_path === selectedImage.value.file_path)
    if (currentIndex === -1) return
    
    const newIndex = currentIndex + direction
    
    // Preload if near end (within 5 images) and has more
    if (direction > 0 && newIndex >= images.value.length - 5 && hasMore.value && !loading.value) {
        fetchImages()
    }

    if (newIndex >= 0 && newIndex < images.value.length) {
        viewDetail(images.value[newIndex])
    }
}

onMounted(async () => {
  checkMobile()
  window.addEventListener('resize', checkMobile)
  window.addEventListener('aimg-auth-required', handleAuthRequired)
  initTheme()
  await checkAuthStatus()
  if (isAuthenticated.value) {
    initAppData()
  }
})

onUnmounted(() => {
  window.removeEventListener('resize', checkMobile)
  window.removeEventListener('aimg-auth-required', handleAuthRequired)
})

// Watch for generation completion to refresh list
watch(() => comfyStatus.active_count, async (newVal, oldVal) => {
    if (!appInitialized.value || (authRequired.value && !isAuthenticated.value)) return
    if (oldVal > 0 && newVal === 0) {
        console.log("[App] Generation finished, triggering scan...")
        await new Promise(r => setTimeout(r, 500))
        await syncGallery()
    }
})
</script>

<template>
  <div class="h-screen flex flex-col overflow-hidden text-gray-800 dark:text-gray-100 bg-white dark:bg-[#0b0c10]" :class="isDark ? 'dark' : ''">
    <div v-if="!authChecked" class="flex-1 flex items-center justify-center text-sm text-gray-500 dark:text-gray-400">
      正在检查访问权限...
    </div>
    <template v-else-if="authRequired && !isAuthenticated">
      <div class="flex-1 flex items-center justify-center p-4">
        <div class="w-full max-w-sm rounded-2xl border border-black/10 dark:border-white/10 bg-white dark:bg-[#111216] p-6 shadow-xl">
          <div class="flex items-center gap-3 mb-4">
            <div class="w-9 h-9 bg-indigo-600 rounded-lg flex items-center justify-center shadow-lg shadow-indigo-500/25">
              <Zap class="text-white w-5 h-5" />
            </div>
            <div>
              <div class="font-semibold">远程访问验证</div>
              <div class="text-xs text-gray-500 dark:text-gray-400">请输入桌面端显示的 6 位验证码</div>
            </div>
          </div>
          <input
            v-model="authCode"
            @keyup.enter="submitAuthLogin"
            placeholder="输入验证码"
            class="w-full h-10 px-3 rounded-lg bg-gray-50 dark:bg-zinc-900 border border-black/10 dark:border-white/10 outline-none focus:border-indigo-500/60 mb-3"
          />
          <button
            @click="submitAuthLogin"
            class="w-full h-10 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-medium transition-colors"
          >
            登录
          </button>
          <p v-if="authError" class="text-xs text-red-500 mt-3">{{ authError }}</p>
        </div>
      </div>
    </template>
    <template v-else>
    <!-- Header -->
    <header class="h-12 flex-shrink-0 flex items-center justify-between px-4 bg-white dark:bg-[#0b0c10] border-b border-black/5 dark:border-white/5 z-40">
      <div class="flex items-center gap-2">
        <div class="w-8 h-8 bg-indigo-600 rounded-lg flex items-center justify-center shadow-lg shadow-indigo-500/20">
          <Zap class="text-white w-5 h-5" />
        </div>
        <h1 class="text-lg font-bold tracking-tight">AIMG <span class="text-indigo-600 dark:text-indigo-400">PRO</span></h1>
      </div>
      <div class="flex items-center gap-2">
        <button @click="showFilters = !showFilters" class="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-white/10 transition-colors">
          <Settings2 class="w-5 h-5 text-gray-600 dark:text-gray-300" />
        </button>
        <button @click="toggleTheme" class="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-white/10 transition-colors">
          <Moon v-if="!isDark" class="w-5 h-5 text-gray-600" />
          <Sun v-else class="w-5 h-5 text-yellow-500" />
        </button>
      </div>
    </header>

    <!-- Main Content -->
    <main class="flex-1 flex overflow-hidden relative" :class="isMobile ? 'flex-col' : ''">
      
      <!-- Left Column: Search & List (Full width on mobile) -->
      <section 
        :style="isMobile ? {} : { width: leftWidth + 'px' }" 
        class="flex flex-col overflow-hidden border-r border-black/5 dark:border-white/5 bg-white dark:bg-[#111216] transition-width duration-0"
        :class="isMobile ? 'w-full h-full' : 'flex-shrink-0'">
        
        <div class="p-3 border-b border-black/5 dark:border-white/5 space-y-2">
          <div class="relative group">
            <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 group-focus-within:text-indigo-500 transition-colors" />
            <input v-model="searchKeyword" @keyup.enter="fetchImages(true)" type="text" placeholder="搜索..." 
              class="w-full h-9 pl-10 pr-3 bg-gray-50 dark:bg-zinc-900 rounded-lg text-sm outline-none border border-transparent focus:border-indigo-500/50 transition-all" />
          </div>
          <!-- Grid control hidden on mobile if desired, or kept? Keeping it is fine -->
          
          <!-- Grid control moved to Settings (FilterModal) -->

        </div>
        
        <ImageList 
          :images="images" 
          :loading="loading" 
          :selectedImage="selectedImage" 
          :gridCols="gridCols"
          :debugMsg="debugMsg"
          @viewDetail="viewDetail"
          @loadMore="fetchImages"
        />
      </section>

      <!-- Desktop Only: Left Resize Handle -->
      <div v-if="!isMobile" @mousedown="startResizeLeft" @touchstart="startResizeLeft" 
        class="w-1 cursor-ew-resize hover:bg-indigo-500/50 transition-colors flex-shrink-0 z-10"></div>

      <!-- Viewer: Desktop (Embedded) vs Mobile (Overlay) -->
      <transition :name="isMobile ? 'fade' : ''">
        <div v-if="!isMobile || selectedImage" 
             :class="isMobile ? (isDark ? 'fixed inset-0 z-50 bg-[#1c1c1c]' : 'fixed inset-0 z-50 bg-gray-100') : 'relative flex-1 overflow-hidden'"
             class="flex flex-col">
             
          <!-- Mobile Close Bar -->
          <div v-if="isMobile" class="absolute top-0 left-0 right-0 h-14 bg-black/50 backdrop-blur-md z-[60] flex items-center justify-between px-4">
             <button @click="closeDetail" class="text-white font-bold">✕ 关闭</button>
             <div class="flex gap-4">
                 <button @click="showMobileInfo = !showMobileInfo" class="text-white text-sm bg-white/10 px-3 py-1 rounded-full">信息</button>
             </div>
          </div>

          <ImageViewer 
            :selectedImage="selectedImage"
            :error="detailImageError"
            :wheelAction="wheelAction"
            :class="isMobile ? 'h-full w-full' : 'h-full w-full'"
            @error="detailImageError = true"
            @switch="handleImageSwitch"
          />
        </div>
      </transition>

      <!-- Desktop Only: Right Resize Handle -->
      <div v-if="!isMobile" @mousedown="startResizeRight" @touchstart="startResizeRight" 
        class="w-1 cursor-ew-resize hover:bg-indigo-500/50 transition-colors flex-shrink-0 z-10"></div>

      <!-- Info Panel: Desktop (Sidebar) vs Mobile (Drawer) -->
      <!-- Info Panel: Mobile Drawer -->
      <template v-if="isMobile">
          <div v-if="showMobileInfo" class="fixed inset-0 z-[70] bg-black/50" @click="showMobileInfo = false"></div>
          <div v-if="showMobileInfo" 
               class="fixed inset-x-0 bottom-0 z-[71] bg-white dark:bg-[#111216] rounded-t-2xl shadow-2xl h-[85vh] flex flex-col overflow-hidden transition-transform duration-300">
               <div class="w-12 h-1 bg-gray-300 dark:bg-gray-700 rounded-full mx-auto my-3 flex-shrink-0"></div>
               <InfoPanel 
                 :width="0"
                 :isMobile="true"
                 :loading="isMetaLoading"
                 :style="{ width: '100%' }"
                 :meta="meta"
                 :selectedImage="selectedImage"
                 v-model:genParams="genParams"
                 v-model:isRandomSeed="isRandomSeed"
                 :filterData="filterData"
                 :comfyStatus="comfyStatus"
                 :isGenerating="isGenerating"
                 @applyToWorkspace="applyToWorkspace"
                 @delete="deleteImage"
                 @submit="submitGeneration"
               />
          </div>
      </template>

      <!-- Desktop Sidebar -->
      <InfoPanel v-else
         :width="rightWidth"
         :meta="meta"
         :loading="isMetaLoading"
         :selectedImage="selectedImage"
         v-model:genParams="genParams"
         v-model:isRandomSeed="isRandomSeed"
         :filterData="filterData"
         :comfyStatus="comfyStatus"
         :isGenerating="isGenerating"
         @applyToWorkspace="applyToWorkspace"
         @delete="deleteImage"
         @submit="submitGeneration"
       />
      
    </main>

    <!-- Modals -->
    <FilterModal 
      v-model:show="showFilters"
      :filterData="filterData"
      v-model:selectedFilters="selectedFilters"
      v-model:wheelAction="wheelAction"
      v-model:gridCols="gridCols"
      @apply="() => { showFilters = false; fetchImages(true) }"
      @reset="() => { selectedFilters.folder = null; selectedFilters.model = null; selectedFilters.lora = null; fetchImages(true) }"
    />
    </template>
  </div>
</template>

<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&family=Outfit:wght@500;700;900&display=swap');
html, body, #app { height: 100%; margin: 0; }
body { font-family: 'Inter', sans-serif; }
h1, h2, h3 { font-family: 'Outfit', sans-serif; }
.dark body { background-color: #0b0c10 !important; }

/* Custom Scrollbar */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-thumb { background: rgba(0,0,0,0.1); border-radius: 5px; }
.dark ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); }
::-webkit-scrollbar-thumb:hover { background: rgba(0,0,0,0.2); }
.dark ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.2); }

.fade-enter-active, .fade-leave-active { transition: opacity 0.2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
