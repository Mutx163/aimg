<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { Image as ImageIcon } from 'lucide-vue-next'

const props = defineProps({
  selectedImage: Object,
  error: Boolean,
  wheelAction: { type: String, default: 'zoom' }
})

const emit = defineEmits(['error', 'switch'])

// View State
const viewScale = ref(1)
const minScale = ref(0.1) // Minimum scale allowed (dynamic based on image fit)
const viewX = ref(0)
const viewY = ref(0)
const isDragging = ref(false)
const isSwitching = ref(false)
const isLoading = ref(false)
const dragStartX = ref(0)
const dragStartY = ref(0)

const imageRef = ref(null)
const containerRef = ref(null)
let transitionTimer = null

// Auto-reset view on window resize
const onWindowResize = () => {
    resetView()
}

onMounted(() => window.addEventListener('resize', onWindowResize))
onUnmounted(() => window.removeEventListener('resize', onWindowResize))

// Reset view when image changes
watch(() => props.selectedImage, () => {
    isSwitching.value = true
    isLoading.value = true
    
    // Clear any pending transition restore
    if (transitionTimer) clearTimeout(transitionTimer)
    
    // Reset immediately (without transition because isSwitching is true)
    viewScale.value = 1
    viewX.value = 0
    viewY.value = 0
    
    // Crucial: Reset switch accumulator so previous scroll inertia doesn't affect new image
    switchAccumulator.value = 0
})

const onImageLoad = () => {
    // Recalculate layout for new image
    resetView()
    
    // Mark loading done, but keep isSwitching true for a moment to ensure 
    // the layout update (viewScale change in resetView) applies without transition
    isLoading.value = false
    
    // Small delay before enabling transition to prevent "zoom to fit" animation
    if (transitionTimer) clearTimeout(transitionTimer)
    transitionTimer = setTimeout(() => {
        isSwitching.value = false
    }, 100) 
}

const resetView = () => {
    if (!imageRef.value || !containerRef.value) return
    // Auto Fit logic
    const img = imageRef.value
    const cont = containerRef.value
    if (img.naturalWidth === 0) return

    const wRatio = cont.clientWidth / img.naturalWidth
    const hRatio = cont.clientHeight / img.naturalHeight
    const scale = Math.min(wRatio, hRatio) // 100% fit
    
    viewScale.value = scale || 1
    minScale.value = scale || 0.1 // Store as minimum
    viewX.value = 0
    viewY.value = 0
}

// Switch Accumulator
const switchAccumulator = ref(0)
const SWITCH_THRESHOLD = 40 // Lower threshold for snappier response (was 60)

const onWheel = (e) => {
    e.preventDefault()
    
    // Handle Switch Mode
    if (props.wheelAction === 'switch') {
        switchAccumulator.value += e.deltaY
        
        if (Math.abs(switchAccumulator.value) >= SWITCH_THRESHOLD) {
            // CLAMP steps to 1 to prevent skipping images during fast scroll
            // We want 1 notch = 1 image, not jumping 5 images
            const steps = 1 
            const direction = switchAccumulator.value > 0 ? 1 : -1
            
            emit('switch', direction * steps)
            
            // Soft reset: Keep just enough residue or Reset completely?
            // Reset completely to 0 prevents "double firing" if user keeps scrolling fast,
            // enforcing a "lift off" or "continuous notch" feel.
            // But if we want continuous rapid scroll, we should subtract threshold.
            // Problem with subtracting: if user spins FAST, deltaY is huge (e.g. 500).
            // 500 / 40 = 12 steps. We clamped to 1.
            // If we keep 460 residue, next frame fires again.
            // If we reset to 0, user has to scroll MORE to get next.
            // BEST UX for "View Mode": Reset to 0. Enforce distinct steps.
            switchAccumulator.value = 0
        }
        
        clearTimeout(window._switchResetTimer)
        window._switchResetTimer = setTimeout(() => {
            switchAccumulator.value = 0
        }, 200)

        return 
    }

    // Default Zoom Mode
    const zoomFactor = 1.1
    const direction = e.deltaY > 0 ? -1 : 1
    let newScale = direction > 0 ? viewScale.value * zoomFactor : viewScale.value / zoomFactor
    
    // Clamp between minScale and 20
    newScale = Math.max(minScale.value, Math.min(newScale, 20))

    viewScale.value = newScale
}

const startDrag = (e) => {
    // Fix: Disable drag (panning) when image is fitted to screen (not zoomed in)
    if (viewScale.value <= minScale.value * 1.001) return

    isDragging.value = true
    dragStartX.value = e.clientX - viewX.value
    dragStartY.value = e.clientY - viewY.value
}

const onDrag = (e) => {
    if (!isDragging.value) return
    e.preventDefault()
    viewX.value = e.clientX - dragStartX.value
    viewY.value = e.clientY - dragStartY.value
}

const stopDrag = () => {
    isDragging.value = false
}

// --- Touch Handling ---
const lastTouchDistance = ref(0)

const onTouchStart = (e) => {
    if (e.touches.length === 1) {
        // For touch, we want to allow dragging even if zoomed out (for swipe detection)
        // So we manually set isDragging instead of calling startDrag which has a check
        isDragging.value = true
        dragStartX.value = e.touches[0].clientX - viewX.value
        dragStartY.value = e.touches[0].clientY - viewY.value
        swipeDeltaX.value = 0 // Reset swipe tracker
    } else if (e.touches.length === 2) {
        // Pinch start
        lastTouchDistance.value = getTouchDistance(e.touches)
    }
}

const swipeDeltaX = ref(0) // Track swipe distance without moving image

const onTouchMove = (e) => {
    e.preventDefault() 
    if (e.touches.length === 1) {
        // SWIPE LOGIC: If image is roughly fit to screen
        if (viewScale.value <= minScale.value * 2.0) {
             // STATIC SWIPE: Do NOT move the image (viewX/viewY)
             // Just calculate the distance from start to check for intent
             const currentX = e.touches[0].clientX
             // dragStartX was set to clientX - viewX (0) -> so dragStartX is just start clientX
             // But let's recalculate cleanly from touch start
             // actually dragStartX = e.touches[0].clientX - viewX.value. If viewX is 0, it is clientX.
             
             // We can just track delta relative to start
             // We need to know where we started. 
             // dragStartX is (StartClientX - InitialViewX).
             // Current Delta = CurrentClientX - InitialViewX - dragStartX
             //              = CurrentClientX - InitialViewX - (StartClientX - InitialViewX)
             //              = CurrentClientX - StartClientX
             
             // Let's rely on the native calculation but NOT assign to viewX
             const calculatedX = e.touches[0].clientX - dragStartX.value
             swipeDeltaX.value = calculatedX 
             
             // FORCE STATIC: Ensure image does not move visually
             viewX.value = 0
             viewY.value = 0 
        } else {
             // Normal Pan Logic (Zoomed In)
             onDrag({ 
                preventDefault: () => {}, 
                clientX: e.touches[0].clientX, 
                clientY: e.touches[0].clientY 
            })
        }
    } else if (e.touches.length === 2) {
        // Pinch Zoom Logic
        const dist = getTouchDistance(e.touches)
        const scaleChange = dist / lastTouchDistance.value
        let newScale = viewScale.value * scaleChange
        newScale = Math.max(minScale.value, Math.min(newScale, 20))
        viewScale.value = newScale
        lastTouchDistance.value = dist
    }
}

const onTouchEnd = (e) => {
    stopDrag()
    
    // Swipe Detection Logic
    if (viewScale.value <= minScale.value * 2.0) {
        // Use the internally tracked delta
        const threshold = 50 
        
        if (swipeDeltaX.value > threshold) {
            emit('switch', -1)
        } else if (swipeDeltaX.value < -threshold) {
            emit('switch', 1)
        }
        
        // Reset local tracker
        swipeDeltaX.value = 0
        // Ensure View is still 0 (should be already, but just in case)
        viewX.value = 0
        viewY.value = 0
    }
}

const getTouchDistance = (touches) => {
    return Math.hypot(
        touches[0].clientX - touches[1].clientX,
        touches[0].clientY - touches[1].clientY
    )
}
</script>

<template>
  <section class="flex-1 overflow-hidden relative bg-[#1c1c1c] flex flex-col" ref="containerRef">
    <div v-if="selectedImage" 
            class="w-full h-full flex items-center justify-center cursor-move touch-none"
            @wheel="onWheel"
            @mousedown="startDrag"
            @mousemove="onDrag"
            @mouseup="stopDrag"
            @mouseleave="stopDrag"
            @touchstart="onTouchStart"
            @touchmove="onTouchMove"
            @touchend="onTouchEnd">
            
        <div class="transform-gpu ease-linear origin-center"
            :class="isDragging || isSwitching || isLoading ? '' : 'transition-transform duration-75'"
            :style="{ transform: `translate(${viewX}px, ${viewY}px) scale(${viewScale})` }">
        <img ref="imageRef"
                :src="'/api/image/raw?path=' + encodeURIComponent(selectedImage.file_path)"
                v-if="!error"
                @load="onImageLoad"
                @error="$emit('error')"
                draggable="false"
                class="max-w-none block shadow-2xl select-none" />
        
            <div v-else class="text-gray-500 flex flex-col items-center scale-[1/viewScale]">
            <ImageIcon class="w-12 h-12 opacity-50" />
            <span class="mt-2 text-sm">加载失败</span>
            </div>
        </div>
    </div>
    
    <div v-else class="w-full h-full flex items-center justify-center text-gray-500 flex-col select-none">
        <ImageIcon class="w-12 h-12 opacity-30" />
        <span class="mt-2 text-sm">选择一张图片查看</span>
        <span class="mt-1 text-xs text-gray-600">滚轮缩放 · 拖拽移动</span>
    </div>

    <!-- Swipe Indicators -->
    <div v-if="swipeDeltaX > 50" class="absolute left-4 top-1/2 -translate-y-1/2 z-20 bg-black/50 p-4 rounded-full text-white backdrop-blur-md animate-in fade-in zoom-in duration-200">
        <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg>
    </div>
    <div v-if="swipeDeltaX < -50" class="absolute right-4 top-1/2 -translate-y-1/2 z-20 bg-black/50 p-4 rounded-full text-white backdrop-blur-md animate-in fade-in zoom-in duration-200">
        <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>
    </div>
    
  </section>
</template>
