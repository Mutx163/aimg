<script setup>
import { ref, onMounted, watch, nextTick } from 'vue'
import { Loader2 } from 'lucide-vue-next'

const props = defineProps({
  images: Array,
  loading: Boolean,
  selectedImage: Object,
  gridCols: Number
})

const emit = defineEmits(['viewDetail', 'loadMore'])

const loadSentinel = ref(null)
const observer = ref(null)

// Auto-scroll to selected image
watch(() => props.selectedImage, async (newVal) => {
    if (!newVal) return
    await nextTick()
    const el = document.getElementById(`img-item-${newVal.file_path}`)
    if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
})

onMounted(() => {
  observer.value = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting) {
      emit('loadMore')
    }
  }, { rootMargin: '200px' })
  
  if (loadSentinel.value) {
    observer.value.observe(loadSentinel.value)
  }
})

// Encode path for URL
const encodePath = (path) => encodeURIComponent(path)
const thumbSrc = (img) => `/api/image/thumb?size=512&path=${encodePath(img.file_path)}&v=${img.file_mtime || 0}`
</script>

<template>
  <div class="flex-1 overflow-y-auto p-3 bg-white dark:bg-[#111216]">
    <div class="grid gap-3 content-start transition-all" 
         :style="{ gridTemplateColumns: `repeat(${gridCols}, minmax(0, 1fr))` }">
      <div v-for="img in images" :key="img.file_path" 
        :id="`img-item-${img.file_path}`"
        @click="$emit('viewDetail', img)"
        class="aspect-[2/3] bg-gray-100 dark:bg-zinc-800 rounded-lg overflow-hidden cursor-pointer transition-all hover:ring-2 hover:ring-indigo-500/50 relative group"
        :class="selectedImage?.file_path === img.file_path ? 'ring-2 ring-indigo-500' : ''">
        
        <img :src="thumbSrc(img)" 
             loading="lazy" 
             class="w-full h-full object-cover block transition-transform duration-300 group-hover:scale-105" />
             
      </div>
    </div>
    
    <div v-if="loading" class="py-4 flex justify-center">
      <Loader2 class="w-5 h-5 animate-spin text-indigo-500" />
    </div>
    
    <div v-else-if="images.length === 0" class="flex-1 flex flex-col items-center justify-center text-gray-400 p-8 text-center min-h-[300px]">
      <div class="mb-2 text-4xl">📭</div>
      <p class="text-sm">暂无图片</p>
      <p class="text-xs mt-1 text-gray-500">请检查文件夹路径或稍后刷新</p>
    </div>

    <!-- Sentinel for infinite scroll -->
    <div ref="loadSentinel" class="h-4 w-full"></div>
  </div>
</template>
