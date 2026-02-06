<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { X, Loader2, Play, Square, Trash2 } from 'lucide-vue-next'

const props = defineProps({
  show: Boolean
})

const emit = defineEmits(['close'])

const queueData = ref({ pending: [], history: [], queue_remaining: 0 })
const loading = ref(false)
const pollTimer = ref(null)

const fetchQueue = async () => {
  loading.value = true
  try {
    const res = await fetch('/api/comfy/queue')
    if (res.ok) {
      queueData.value = await res.json()
    }
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

const cancelTask = async (id) => {
  if (!confirm('确定取消该任务吗？')) return
  try {
    await fetch('/api/comfy/cancel_task', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt_id: id })
    })
    fetchQueue()
  } catch (e) {
    alert('取消失败: ' + e.message)
  }
}

const interruptCurrent = async () => {
  if (!confirm('确定中断当前正在执行的任务吗？')) return
  try {
    await fetch('/api/comfy/interrupt', { method: 'POST' })
    fetchQueue()
  } catch (e) {
    alert('中断失败: ' + e.message)
  }
}

onMounted(() => {
  fetchQueue()
  pollTimer.value = setInterval(fetchQueue, 2000)
})

onUnmounted(() => {
  if (pollTimer.value) clearInterval(pollTimer.value)
})
</script>

<template>
  <div v-if="show" class="fixed inset-0 z-[100] flex items-center justify-center p-4">
    <div class="absolute inset-0 bg-black/60" @click="$emit('close')"></div>
    <div class="relative w-full max-w-lg bg-white dark:bg-[#111216] rounded-2xl shadow-2xl flex flex-col max-h-[80vh] overflow-hidden">
      
      <!-- Header -->
      <div class="flex items-center justify-between p-4 border-b border-gray-100 dark:border-white/5 bg-gray-50/50 dark:bg-black/20">
        <h3 class="text-sm font-bold flex items-center gap-2">
          任务队列
          <span v-if="queueData.queue_remaining > 0" class="bg-indigo-600 text-white text-[10px] px-2 py-0.5 rounded-full">
            剩余 {{ queueData.queue_remaining }}
          </span>
        </h3>
        <button @click="$emit('close')" class="p-1 hover:bg-gray-200 dark:hover:bg-white/10 rounded">
          <X class="w-5 h-5 text-gray-500" />
        </button>
      </div>

      <!-- Content -->
      <div class="flex-1 overflow-y-auto p-4 space-y-6">
        
        <!-- Running -->
        <div v-if="queueData.pending.some(t => t.status === 'running')">
          <div class="text-xs font-bold text-indigo-500 uppercase mb-2 flex justify-between items-center">
            <span>正在执行</span>
            <button @click="interruptCurrent" class="text-red-500 hover:bg-red-50 px-2 py-1 rounded text-[10px] flex items-center gap-1 border border-red-200">
              <Square class="w-3 h-3 fill-current" /> 中断
            </button>
          </div>
          <div v-for="task in queueData.pending.filter(t => t.status === 'running')" :key="task.id"
               class="bg-indigo-50 dark:bg-indigo-900/20 border border-indigo-100 dark:border-indigo-500/30 rounded-lg p-3 relative overflow-hidden">
             <div class="absolute top-0 left-0 bottom-0 bg-indigo-500/5 w-full animate-pulse"></div>
             <div class="relative flex justify-between items-start">
               <div class="flex-1 mr-2">
                 <div class="flex justify-between items-center mb-1">
                   <div class="text-xs font-bold text-indigo-700 dark:text-indigo-300">Processing...</div>
                   <div class="text-[10px] font-mono text-indigo-600 dark:text-indigo-400 font-bold">
                     {{ Math.round(task.progress || 0) }}%
                   </div>
                 </div>
                 
                 <!-- Progress Bar -->
                 <div class="h-1.5 w-full bg-indigo-200 dark:bg-indigo-900/50 rounded-full overflow-hidden mb-1.5">
                   <div class="h-full bg-indigo-500 rounded-full transition-all duration-300 ease-out"
                        :style="{ width: (task.progress || 0) + '%' }"></div>
                 </div>

                 <div class="text-[11px] text-gray-600 dark:text-gray-400 line-clamp-2">{{ task.prompt }}</div>
                 <div v-if="task.lora_info" class="mt-1 text-[10px] text-gray-400 bg-white/50 dark:bg-black/20 inline-block px-1 rounded">
                   {{ task.lora_info }}
                 </div>
               </div>
               <Loader2 class="w-4 h-4 text-indigo-500 animate-spin" />
             </div>
          </div>
        </div>

        <!-- Pending -->
        <div>
          <div class="text-xs font-bold text-gray-400 uppercase mb-2">等待中 ({{ queueData.pending.filter(t => t.status === 'pending').length }})</div>
          <div v-if="queueData.pending.filter(t => t.status === 'pending').length === 0" class="text-center text-xs text-gray-400 py-4 border-2 border-dashed border-gray-100 dark:border-white/5 rounded-lg">
            队列空闲
          </div>
          <div v-else class="space-y-2">
            <div v-for="(task, idx) in queueData.pending.filter(t => t.status === 'pending')" :key="task.id"
                 class="bg-white dark:bg-zinc-900 border border-gray-100 dark:border-white/5 rounded-lg p-3 flex justify-between items-center group hover:border-gray-300 dark:hover:border-white/20 transition-colors">
               <div class="flex-1 min-w-0 mr-3">
                 <div class="flex items-center gap-2 mb-1">
                   <span class="text-[10px] font-mono text-gray-400">#{{ idx + 1 }}</span>
                   <span class="text-[10px] bg-gray-100 dark:bg-white/10 px-1.5 rounded text-gray-500">{{ task.id.substring(0,8) }}</span>
                 </div>
                 <div class="text-[11px] text-gray-600 dark:text-gray-300 truncate">{{ task.prompt || '未知任务' }}</div>
               </div>
               <button @click="cancelTask(task.id)" class="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 p-1 transition-opacity" title="取消任务">
                 <Trash2 class="w-4 h-4" />
               </button>
            </div>
          </div>
        </div>

      </div>
    </div>
  </div>
</template>
