<script setup>
import { computed } from 'vue'
import { X } from 'lucide-vue-next'

const props = defineProps({
  show: Boolean,
  filterData: Object,
  selectedFilters: Object,
  wheelAction: String, // 'zoom' | 'switch'
  gridCols: Number
})

const emit = defineEmits(['update:show', 'update:selectedFilters', 'update:wheelAction', 'update:gridCols', 'apply', 'reset'])

// Helper to update filters
const updateFilter = (key, value) => {
    const newFilters = { ...props.selectedFilters, [key]: value }
    emit('update:selectedFilters', newFilters)
}
</script>

<template>
  <transition name="fade">
    <div v-if="show" class="fixed inset-0 z-[110] flex items-center justify-center p-4">
      <div class="absolute inset-0 bg-black/60" @click="$emit('update:show', false)"></div>
      <div class="relative w-full max-w-sm bg-white dark:bg-[#0b0c10] rounded-2xl shadow-2xl p-5">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-base font-bold">筛选图片</h3>
          <button @click="$emit('update:show', false)" class="p-1 hover:bg-gray-100 dark:hover:bg-white/10 rounded">
            <X class="w-5 h-5" />
          </button>
        </div>
        
        <div class="space-y-3">
          <!-- Folder Filter -->
          <div>
            <label class="text-xs font-bold text-gray-500 uppercase">文件夹</label>
            <div class="flex flex-wrap gap-1 mt-2">
              <button v-for="f in filterData.folders" :key="f" 
                @click="updateFilter('folder', selectedFilters.folder === f ? null : f)"
                class="px-2 py-1 text-xs rounded-lg transition-colors" 
                :class="selectedFilters.folder === f ? 'bg-indigo-600 text-white' : 'bg-gray-100 dark:bg-white/5'">
                {{ f }}
              </button>
            </div>
          </div>
          
          <!-- Model Filter -->
          <div>
            <label class="text-xs font-bold text-gray-500 uppercase">模型</label>
            <select :value="selectedFilters.model || ''" 
                    @change="updateFilter('model', $event.target.value || null)"
                    class="w-full mt-1 h-8 px-3 bg-gray-50 dark:bg-zinc-900 rounded-lg text-sm outline-none border border-transparent focus:border-indigo-500">
              <option value="">全部模型</option>
              <option v-for="m in filterData.models" :key="m" :value="m">{{ m }}</option>
            </select>
          </div>
          
          <!-- LoRA Filter -->
          <div>
            <label class="text-xs font-bold text-gray-500 uppercase">LoRA</label>
            <select :value="selectedFilters.lora || ''" 
                    @change="updateFilter('lora', $event.target.value || null)"
                    class="w-full mt-1 h-8 px-3 bg-gray-50 dark:bg-zinc-900 rounded-lg text-sm outline-none border border-transparent focus:border-indigo-500">
              <option value="">全部 LoRA</option>
              <option v-for="l in filterData.loras" :key="l" :value="l">{{ l }}</option>
            </select>
          </div>
        </div>

        <div class="border-t border-gray-100 dark:border-white/5 my-4"></div>

        <!-- Preferences -->
        <div class="space-y-3">
             <h4 class="text-xs font-bold text-gray-900 dark:text-gray-100">偏好设置</h4>
             
             <!-- Grid Size (Moved here) -->
             <div class="flex items-center justify-between">
                <label class="text-xs text-gray-500">网格列数</label>
                <div class="flex items-center gap-2">
                    <input type="range" min="1" max="6" 
                           :value="gridCols" 
                           @input="$emit('update:gridCols', Number($event.target.value))"
                           class="w-24 h-1 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700 accent-indigo-600">
                    <span class="text-xs text-gray-500 w-3 text-right">{{ gridCols }}</span>
                </div>
             </div>

             <div class="flex items-center justify-between">
                 <label class="text-xs text-gray-500">鼠标滚轮行为</label>
                 <div class="flex bg-gray-100 dark:bg-zinc-800 rounded-lg p-1">
                     <button @click="$emit('update:wheelAction', 'zoom')"
                         class="px-3 py-1 text-xs rounded-md transition-all"
                         :class="wheelAction === 'zoom' ? 'bg-white dark:bg-zinc-700 shadow-sm text-indigo-600 dark:text-indigo-400 font-bold' : 'text-gray-500'">
                         缩放
                     </button>
                     <button @click="$emit('update:wheelAction', 'switch')"
                         class="px-3 py-1 text-xs rounded-md transition-all"
                         :class="wheelAction === 'switch' ? 'bg-white dark:bg-zinc-700 shadow-sm text-indigo-600 dark:text-indigo-400 font-bold' : 'text-gray-500'">
                         切图
                     </button>
                 </div>
             </div>
        </div>
        
        <div class="flex gap-3 mt-5">
          <button @click="$emit('reset')" 
            class="flex-1 h-9 rounded-lg font-bold text-gray-500 bg-gray-100 dark:bg-white/5 hover:bg-gray-200 dark:hover:bg-white/10">重置</button>
          <button @click="$emit('apply')" 
            class="flex-1 h-9 rounded-lg font-bold text-white bg-indigo-600 hover:bg-indigo-700">应用</button>
        </div>
      </div>
    </div>
  </transition>
</template>
