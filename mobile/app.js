const { createApp, ref, onMounted, reactive, watch, computed } = Vue;

createApp({
    setup() {
        const activeTab = ref('gallery'); // 'gallery' or 'create'
        const images = ref([]);
        const loading = ref(false);
        const searchKeyword = ref("");
        const page = ref(1);
        const hasMore = ref(true);

        // Modal & Detail
        const selectedImage = ref(null);
        const meta = ref(null);

        // Filters
        const showFilters = ref(false);
        const filterData = reactive({ folders: [], models: [], loras: [], samplers: [], schedulers: [], resolutions: [] });
        const selectedFilters = reactive({ folder: null, model: null, lora: null });

        // AI Optimize
        const showAIModal = ref(false);
        const aiInput = ref("");
        const aiLoading = ref(false);

        // AI System Prompts synced with Python side
        const SYSTEM_PROMPTS = {
            GENERATE: "你是一位专业的AI绘画提示词高级专家。\n\n你的任务是将用户的需求口语化转换为一段细节丰富、画面清晰、且完全使用中文自然语言书写的提示词。\n\n要求:\n1. 必须使用中文自然语言书写，不要出现英文单词\n2. 必须严格遵循用户指令，用户提到的服饰、发型、场景、动作等必须明确写入\n3. 如果用户指定“换成/改成/必须是”等强指令，必须把该元素放在句首强调，并删除任何与之冲突的描述\n4. 输出为纯文本，不要使用Markdown格式，不要添加解释或前缀，不要使用星号或其他标记符号\n5. 描述要具体可视化，包含材质、颜色、款式与穿着部位",
            OPTIMIZE: "你是一位专业的AI绘画提示词优化专家。\n\n你的任务是根据用户的修改指令，直接重写并优化现有提示词，输出为中文自然语言。\n\n要求:\n1. 严格执行用户的修改指令，涉及服装、姿态、场景的要求必须明确写入\n2. 对强指令必须替换掉原冲突内容，不允许保留矛盾服饰或场景\n3. 用户指令中的关键元素必须放在句首强调\n4. 输出为纯文本，不要使用Markdown格式，不要添加解释，不要使用星号或其他标记符号\n5. 保留原提示词的主体风格，但以用户指令为最高优先级",
            NEG_GENERATE: "你是一位专业的AI绘画负向提示词（Negative Prompt）处理专家。\n\n你的任务是根据用户的反馈，输出“中文关键词列表”形式的反向提示词。\n\n要求:\n1. 必须使用中文关键词或短语，使用中文逗号分隔\n2. 只输出关键词列表，不要使用长句，不要使用解释\n3. 覆盖常见问题：模糊、重影、马赛克、噪点、崩坏肢体、比例失调、五官扭曲、皮肤塑料感、水印、文字、Logo、背景杂乱等\n4. 如果用户特别强调某些不要项，必须优先放在列表前部\n5. 输出为纯文本，不要使用Markdown格式\n6. 最多输出30个关键词，优先保留最关键的问题",
            NEG_OPTIMIZE: "你是一位专业的AI绘画负向提示词优化专家。\n\n你的任务是根据用户的最新指令，对现有的反向提示词进行扩充，输出为“中文关键词列表”。\n\n要求:\n1. 保留原有核心避雷内容\n2. 根据用户的额外要求，精准添加新的关键词\n3. 必须使用中文关键词或短语，使用中文逗号分隔\n4. 只输出关键词列表，不要使用长句或解释\n5. 输出为纯文本，不要使用Markdown格式\n6. 最多输出30个关键词，优先保留最关键的问题"
        };
        const loadGenParams = () => {
            try {
                const saved = localStorage.getItem('genParams');
                if (saved) {
                    return JSON.parse(saved);
                }
            } catch (e) { }
            return null;
        };

        const savedParams = loadGenParams();
        const isGenerating = ref(false);
        const comfyStatus = reactive({ connected: false, queue_remaining: 0 });
        const queueData = reactive({ pending: [], history: [], progress: 0 });
        const genParams = reactive({
            model: savedParams?.model || "",
            prompt: savedParams?.prompt || "",
            negative_prompt: savedParams?.negative_prompt || "模糊, 重影, 崩坏肢体, 文字, 水印",
            resolution: savedParams?.resolution || "512x768",
            sampler: savedParams?.sampler || "",
            scheduler: savedParams?.scheduler || "",
            steps: savedParams?.steps || 20,
            cfg: savedParams?.cfg || 7.0,
            lora: savedParams?.lora || "",
            lora_weight: savedParams?.lora_weight || 1.0
        });

        // 保存 genParams 到 localStorage
        const saveGenParams = () => {
            try {
                localStorage.setItem('genParams', JSON.stringify({
                    model: genParams.model,
                    prompt: genParams.prompt,
                    negative_prompt: genParams.negative_prompt,
                    resolution: genParams.resolution,
                    sampler: genParams.sampler,
                    scheduler: genParams.scheduler,
                    steps: genParams.steps,
                    cfg: genParams.cfg,
                    lora: genParams.lora,
                    lora_weight: genParams.lora_weight
                }));
            } catch (e) { }
        };

        // 监听 genParams 变化并保存
        watch(genParams, () => {
            saveGenParams();
        }, { deep: true });

        // Sidebar Width functionality (Focus on Settings Panel)
        const isResizing = ref(false);
        const settingsWidth = ref(parseInt(localStorage.getItem('settingsWidth')) || 400);
        const startX = ref(0);
        const startSettingsWidth = ref(0);

        const startResize = (e) => {
            isResizing.value = true;
            startX.value = e.clientX || e.touches[0].clientX;
            startSettingsWidth.value = settingsWidth.value;
            document.body.classList.add('user-select-none');
            document.addEventListener('mousemove', doResize);
            document.addEventListener('mouseup', stopResize);
            document.addEventListener('touchmove', doResize);
            document.addEventListener('touchend', stopResize);
        };

        const doResize = (e) => {
            if (!isResizing.value) return;
            const clientX = e.clientX || e.touches[0].clientX;
            const delta = clientX - startX.value;
            // 往左拉 delta 为负，设置区变宽；往右拉 delta 为正，设置区变窄
            const newWidth = startSettingsWidth.value - delta;
            // 约束宽度范围 (最小 300, 最大 80%)
            settingsWidth.value = Math.max(300, Math.min(window.innerWidth * 0.8, newWidth));
            localStorage.setItem('settingsWidth', settingsWidth.value);
        };

        const stopResize = () => {
            isResizing.value = false;
            document.body.classList.remove('user-select-none');
            document.removeEventListener('mousemove', doResize);
            document.removeEventListener('mouseup', stopResize);
            document.removeEventListener('touchmove', doResize);
            document.removeEventListener('touchend', stopResize);
        };

        const fetchImages = async (isRefresh = false) => {
            if (loading.value) return;
            if (isRefresh) {
                page.value = 1;
                images.value = [];
                hasMore.value = true;
            }
            if (!hasMore.value) return;

            loading.value = true;
            try {
                const query = new URLSearchParams({
                    keyword: searchKeyword.value,
                    page: page.value,
                    folder: selectedFilters.folder || "",
                    model: selectedFilters.model || "",
                    lora: selectedFilters.lora || ""
                });
                const response = await fetch(`/api/images?${query.toString()}`);
                const data = await response.json();

                if (data.images.length === 0) {
                    hasMore.value = false;
                } else {
                    // Pre-calculate aspect ratio styles for stable layout
                    const newImages = data.images.map(img => {
                        const w = img.width || 512;
                        const h = img.height || 768;
                        return {
                            ...img,
                            aspectRatio: w / h,
                            // 占位符颜色：根据文件名hash生成一个固定的柔和色，避免单调灰
                            placeholderColor: stringToColor(img.file_path),
                            loaded: false
                        };
                    });

                    images.value = [...images.value, ...newImages];
                    page.value++;
                    hasMore.value = data.has_more;

                    // 加载完成后，检查是否填满屏幕
                    setTimeout(checkFillScreen, 100);
                }
            } catch (err) {
                console.error("Fetch error:", err);
            } finally {
                loading.value = false;
                // 加载完成后，检查是否填满屏幕
                scheduleCheckFill();
            }
        };

        let checkFillTimeout = null;
        const scheduleCheckFill = () => {
            if (checkFillTimeout) clearTimeout(checkFillTimeout);
            checkFillTimeout = setTimeout(checkFillScreen, 300); // 增加延迟，防止爆发
        };

        const fetchFilters = async () => {
            try {
                const resp = await fetch('/api/filters');
                const data = await resp.json();
                filterData.folders = data.folders;
                filterData.models = data.models;
                filterData.loras = data.loras;
                filterData.samplers = data.samplers || [];
                filterData.schedulers = data.schedulers || [];
                filterData.resolutions = data.resolutions || [];

                // Default settings from desktop consistency
                if (!genParams.model && data.models.length > 0) genParams.model = data.models[0];
                if (!genParams.sampler && data.samplers.length > 0) genParams.sampler = data.samplers[0];
                if (!genParams.scheduler && data.schedulers.length > 0) genParams.scheduler = data.schedulers[0];
                if (!genParams.resolution && data.resolutions.length > 0) genParams.resolution = data.resolutions[0];
            } catch (e) { console.error("Filter fetch failed", e); }
        };

        let isPolling = false;
        const pollComfyStatus = async () => {
            if (isPolling) return;
            isPolling = true;
            try {
                const resp = await fetch('/api/comfy/status');
                const data = await resp.json();
                comfyStatus.connected = data.connected !== false;
                const prevQueueRemaining = comfyStatus.queue_remaining;
                comfyStatus.queue_remaining = data.status?.exec_info?.queue_remaining || 0;

                // 检测队列完成，自动刷新图片
                if (prevQueueRemaining > 0 && comfyStatus.queue_remaining === 0 && queueData.pending.length === 0) {
                    fetch('/api/scan', { method: 'POST' }).catch(() => { });
                    setTimeout(() => {
                        refreshImages();
                        showNotification("图片生成完成", "success");
                    }, 1000);
                }

                if (comfyStatus.connected) {
                    const qResp = await fetch('/api/comfy/queue');
                    const qData = await qResp.json();
                    queueData.pending = qData.pending;
                    queueData.history = qData.history;
                    if (qData.queue_remaining !== undefined) {
                        comfyStatus.queue_remaining = qData.queue_remaining;
                    }

                    const hasRunning = queueData.pending.some(t => t.status === 'running');
                    if (hasRunning) {
                        queueData.progress = (queueData.progress >= 95) ? 95 : (queueData.progress + 2);
                    } else {
                        queueData.progress = 0;
                    }
                }
            } catch (e) {
                comfyStatus.connected = false;
            } finally {
                isPolling = false;
            }

            // 降低轮训频率：无任务 2s，有任务 1s
            const interval = (queueData.pending.length > 0 || activeTab.value === 'create') ? 1000 : 2000;
            setTimeout(pollComfyStatus, interval);
        };

        const submitGeneration = async () => {
            if (!comfyStatus.connected) {
                showNotification("ComfyUI 未连接", "error");
                return;
            }
            isGenerating.value = true;
            try {
                const resp = await fetch('/api/comfy/generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(genParams)
                });
                if (!resp.ok) throw new Error(await resp.text());

                showNotification("任务已提交，生成中...", "success");
            } catch (e) {
                showNotification("生成提交失败: " + e.message, "error");
            } finally {
                isGenerating.value = false;
            }
        };

        const showNotification = (msg, type = "info") => {
            const container = document.createElement("div");
            container.className = `fixed top-4 right-4 z-[100] px-4 py-3 rounded-xl shadow-lg text-sm font-medium flex items-center gap-2 animate-slide-in ${type === "success" ? "bg-green-500/20 text-green-400 border border-green-500/30" :
                type === "error" ? "bg-red-500/20 text-red-400 border border-red-500/30" :
                    "bg-blue-500/20 text-blue-400 border border-blue-500/30"
                }`;
            container.innerHTML = msg;
            document.body.appendChild(container);
            setTimeout(() => {
                container.style.opacity = "0";
                container.style.transform = "translateX(100px)";
                container.style.transition = "all 0.3s";
                setTimeout(() => container.remove(), 300);
            }, 3000);
        };

        // AI Optimization State
        const aiResult = ref("");
        const aiTarget = ref("positive"); // positive or negative

        const openAIModal = (target = "positive") => {
            aiTarget.value = target;
            aiInput.value = "";
            aiResult.value = "";
            showAIModal.value = true;
        };

        const runAIOptimize = async () => {
            if (!aiInput.value.trim()) return;

            const targetIsNegative = aiTarget.value === "negative";
            const isOptimizing = targetIsNegative ? !!genParams.negative_prompt : !!genParams.prompt;

            // Choose the correct system prompt
            let systemPrompt = "";
            if (targetIsNegative) {
                systemPrompt = isOptimizing ? SYSTEM_PROMPTS.NEG_OPTIMIZE : SYSTEM_PROMPTS.NEG_GENERATE;
            } else {
                systemPrompt = isOptimizing ? SYSTEM_PROMPTS.OPTIMIZE : SYSTEM_PROMPTS.GENERATE;
            }

            // Capture existing prompt for API payload BEFORE clearing UI
            const currentPrompt = targetIsNegative ? genParams.negative_prompt : genParams.prompt;

            // Close modal immediately
            showAIModal.value = false;
            aiLoading.value = true;

            // Clear the target input to show streaming result clearly
            // If optimizing, we want to replace the old prompt, not append to it
            if (targetIsNegative) {
                genParams.negative_prompt = "";
            } else {
                genParams.prompt = "";
            }

            try {
                const payload = {
                    mode: targetIsNegative ? 'negative' : (isOptimizing ? 'optimize' : 'generate'),
                    user_input: aiInput.value,
                    existing_prompt: currentPrompt, // Send the captured old prompt
                    system_prompt: systemPrompt
                };

                const response = await fetch('/api/ai/optimize', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                // ... rest of stream logic remains same ...

                if (!response.ok) {
                    throw new Error(await response.text());
                }

                const reader = response.body.getReader();
                const decoder = new TextDecoder('utf-8');
                let buffer = '';

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop() || '';

                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            try {
                                const data = JSON.parse(line.slice(6));

                                if (data.chunk) {
                                    // 流式填充到目标输入框
                                    if (targetIsNegative) {
                                        genParams.negative_prompt += data.chunk;
                                    } else {
                                        genParams.prompt += data.chunk;
                                    }
                                } else if (data.done) {
                                    showNotification("AI 处理完成", "success");
                                } else if (data.error) {
                                    throw new Error(data.error);
                                }
                            } catch (e) {
                                // 忽略解析错误
                            }
                        }
                    }
                }

            } catch (e) {
                showNotification("AI 处理失败: " + e.message, "error");
            } finally {
                aiLoading.value = false;
            }
        };

        const copyAIResult = () => {
            if (aiResult.value) {
                navigator.clipboard.writeText(aiResult.value);
                showNotification("已复制到剪贴板", "success");
            }
        };

        const triggerAIIMageImport = () => {
            const input = document.querySelector('input[type="file"]');
            if (input) input.click();
        };

        // Add paste listener for handling clipboard in prompt inputs
        const handlePromptPaste = async (e, targetField) => {
            const items = e.clipboardData?.items;
            if (!items) return;

            for (const item of items) {
                if (item.type.indexOf('image') !== -1) {
                    e.preventDefault();
                    const blob = item.getAsFile();
                    const reader = new FileReader();
                    reader.onload = async (event) => {
                        const b64 = event.target.result.split(",", 1)[1] || event.target.result;
                        try {
                            const resp = await fetch('/api/ai/optimize', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    mode: 'image',
                                    user_input: '',
                                    existing_prompt: '',
                                    image_b64: b64
                                })
                            });
                            const data = await resp.json();
                            if (targetField === 'prompt') {
                                genParams.prompt = data.result;
                            } else {
                                genParams.negative_prompt = data.result;
                            }
                        } catch (err) {
                            showNotification("图片识别失败", "error");
                        }
                    };
                    reader.readAsDataURL(blob);
                    break;
                }
            }
        };

        // Attach paste handlers to prompt inputs
        onMounted(() => {
            const promptInput = document.querySelector('textarea[placeholder="描述你想生成的画面..."]');
            const negInput = document.querySelector('textarea[placeholder="不想出现的内容..."]');
            if (promptInput) {
                promptInput.addEventListener('paste', (e) => handlePromptPaste(e, 'prompt'));
            }
            if (negInput) {
                negInput.addEventListener('paste', (e) => handlePromptPaste(e, 'negative'));
            }
        });

        // File import for prompt
        const fileInput = ref(null);
        const handleFileImport = () => {
            if (fileInput.value) fileInput.value.click();
        };
        const onFileChanged = (e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = async (ev) => {
                const b64 = ev.target.result.split(",", 1)[1] || ev.target.result;
                try {
                    const resp = await fetch('/api/ai/optimize', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ mode: 'image', user_input: '', existing_prompt: '', image_b64: b64 })
                    });
                    const data = await resp.json();
                    genParams.prompt = data.result;
                    showNotification("已从图片生成提示词", "success");
                } catch (err) {
                    showNotification("图片识别失败", "error");
                }
            };
            reader.readAsDataURL(file);
        };

        // Filter methods
        const toggleFilter = (key, val) => {
            const currentKey = key.slice(0, -1); // folders -> folder
            if (selectedFilters[currentKey] === val) {
                selectedFilters[currentKey] = null;
            } else {
                selectedFilters[currentKey] = val;
            }
        };
        const isFilterSelected = (key, val) => selectedFilters[key.slice(0, -1)] === val;
        const resetFilters = () => {
            selectedFilters.folder = null;
            selectedFilters.model = null;
            selectedFilters.lora = null;
        };
        const applyFilters = () => {
            showFilters.value = false;
            fetchImages(true);
        };

        // Helper function to safely get params with fallbacks
        const getParam = (key, fallback = null) => {
            if (!meta.value || !meta.value.params) return fallback;
            const p = meta.value.params;
            // Check multiple possible key formats
            const keys = [key, key.toLowerCase(), key.charAt(0).toUpperCase() + key.slice(1).toLowerCase()];
            for (const k of keys) {
                if (p[k] !== undefined && p[k] !== null && p[k] !== '') {
                    return p[k];
                }
            }
            return fallback;
        };

        const stringToColor = (str) => {
            let hash = 0;
            for (let i = 0; i < str.length; i++) {
                hash = str.charCodeAt(i) + ((hash << 5) - hash);
            }
            const c = (hash & 0x00FFFFFF).toString(16).toUpperCase();
            return '#' + '00000'.substring(0, 6 - c.length) + c;
        };

        // Helper to get image dimensions
        const getImageDimensions = () => {
            if (selectedImage.value && selectedImage.value.width && selectedImage.value.height) {
                return `${selectedImage.value.width}×${selectedImage.value.height}`;
            }
            return '';
        };

        const applyToWorkspace = () => {
            if (!meta.value) return;
            const m = meta.value;
            const p = m.params || {};

            genParams.prompt = m.prompt || "";
            genParams.negative_prompt = m.negative_prompt || "";
            genParams.model = p.Model || p.model || "";
            genParams.steps = parseInt(p.Steps || p.steps) || 20;
            genParams.cfg = parseFloat(p['CFG scale'] || p.cfg || p.CFG) || 7.0;
            genParams.sampler = p.Sampler || p.sampler_name || "";
            genParams.scheduler = p.Scheduler || p.scheduler || "";

            // LoRA handling (包含权重提取)
            if (m.loras && m.loras.length > 0) {
                const loraStr = m.loras[0];
                const loraName = loraStr.split('(')[0].trim();
                genParams.lora = loraName;

                // 提取权重，格式如 "lora_name(0.8)"
                const weightMatch = loraStr.match(/\(([\d.]+)\)/);
                genParams.lora_weight = weightMatch ? parseFloat(weightMatch[1]) : 1.0;
            } else {
                genParams.lora = "";
                genParams.lora_weight = 1.0;
            }

            // Resolution handling - 多种可能来源
            let targetRes = "";

            // 1. 直接从 width/height 获取
            if (p.width && p.height) {
                targetRes = `${p.width}x${p.height}`;
            }
            // 2. 从 size 字段获取
            else if (p.size) {
                targetRes = p.size;
            }
            // 3. 从 meta.size 获取
            else if (m.size) {
                targetRes = m.size;
            }

            // 如果找到分辨率，添加到选项并选中
            if (targetRes) {
                if (!filterData.resolutions.includes(targetRes)) {
                    filterData.resolutions.unshift(targetRes);
                }
                genParams.resolution = targetRes;
            } else {
                genParams.resolution = "512x768";
            }

            // 关闭详情页并切换到生图标签
            closeDetail();
            activeTab.value = 'create';
            showNotification("已调用到生图区", "success");
        };

        // --- History & Navigation (Native Back Button Support) ---
        const pushModalState = (name) => {
            history.pushState({ modal: name }, "");
        };

        window.addEventListener('popstate', (event) => {
            // Priority: Detail > AI Modal > Filters
            if (selectedImage.value) {
                closeDetail(false);
            } else if (showAIModal.value) {
                showAIModal.value = false;
            } else if (showFilters.value) {
                showFilters.value = false;
            }
        });

        // Swipe & Animation Logic
        let touchStartX = 0;
        let touchStartY = 0;
        const imageAnimationClass = ref("");

        const handleTouchStart = (e) => {
            touchStartX = e.touches[0].clientX;
            touchStartY = e.touches[0].clientY;
        };

        const navigateImage = (dir) => {
            if (!selectedImage.value) return;
            const idx = images.value.findIndex(i => i.file_path === selectedImage.value.file_path);
            if (idx === -1) return;
            const nextIdx = idx + dir;
            if (nextIdx >= 0 && nextIdx < images.value.length) {
                // 触发切换动画
                imageAnimationClass.value = dir > 0 ? "slide-left" : "slide-right";
                setTimeout(() => {
                    viewDetail(images.value[nextIdx], false); // false 表示不重置滚动条
                    imageAnimationClass.value = "";
                }, 150);
            }
        };

        const lastWheelTime = ref(0);
        const handleWheel = (e) => {
            if (!selectedImage.value) return;
            // 节流处理，防止翻页过快
            const now = Date.now();
            if (now - lastWheelTime.value < 500) return;

            if (Math.abs(e.deltaY) > 10) { // 忽略微小滚动
                const dir = e.deltaY > 0 ? 1 : -1;
                navigateImage(dir);
                lastWheelTime.value = now;
            }
        };

        const handleTouchEnd = (e) => {
            const deltaX = e.changedTouches[0].clientX - touchStartX;
            const deltaY = e.changedTouches[0].clientY - touchStartY;

            // 只有当水平位移远大于垂直位移，且位移量足够时才触发翻页
            if (Math.abs(deltaX) > 50 && Math.abs(deltaX) > Math.abs(deltaY) * 1.5) {
                const dir = deltaX > 0 ? -1 : 1;
                navigateImage(dir);
            }
        };

        // Predicitive Prefetching Logic
        const prefetchCache = new Set();
        const prefetchAdjacentImages = (currentIndex) => {
            if (currentIndex === -1) return;

            const indicesToPrefetch = [
                currentIndex + 1, // Next
                currentIndex - 1  // Prev
            ];

            indicesToPrefetch.forEach(idx => {
                if (idx >= 0 && idx < images.value.length) {
                    const img = images.value[idx];
                    const src = `/api/image/raw?path=${encodeURIComponent(img.file_path)}`;

                    if (!prefetchCache.has(src)) {
                        // Use standard Image object to force browser download
                        const i = new Image();
                        i.src = src;
                        prefetchCache.add(src);

                        // Simple LRU-ish: Clear cache if too big to save memory
                        if (prefetchCache.size > 20) {
                            const it = prefetchCache.values();
                            prefetchCache.delete(it.next().value);
                        }
                    }
                }
            });
        };

        // Watch for selection changes to trigger prefetch
        Vue.watch(selectedImage, (newVal) => {
            if (newVal) {
                const idx = images.value.findIndex(i => i.file_path === newVal.file_path);
                if (idx !== -1) prefetchAdjacentImages(idx);
            }
        });

        // Updated Modal Methods
        const viewDetail = async (img, resetScroll = true) => {
            selectedImage.value = img;
            meta.value = null; // Clear old metadata immediately to avoid stale or blank display

            document.body.classList.add('modal-open');
            if (resetScroll) {
                pushModalState('detail');
                setTimeout(() => {
                    const el = document.querySelector('#detail-info');
                    if (el) el.scrollTop = 0;
                    const wrapper = document.querySelector('.glass-modal-wrapper');
                    if (wrapper) wrapper.scrollTop = 0;
                }, 0);
            }

            try {
                const response = await fetch(`/api/metadata?path=${encodeURIComponent(img.file_path)}&t=${Date.now()}`);
                if (!response.ok) throw new Error("Fetch failed");
                const data = await response.json();
                meta.value = data;
            } catch (err) {
                console.error("Meta Fetch Failed:", err);
                meta.value = { prompt: "无法解析该图片的元数据", params: {} };
            }
        };

        const closeDetail = (doBack = true) => {
            if (!selectedImage.value) return;
            selectedImage.value = null;
            meta.value = null; // Reset meta when closing detail
            document.body.classList.remove('modal-open');
            if (doBack && window.history.state?.modal === 'detail') {
                history.back();
            }
        };

        const confirmDelete = () => {
            if (!selectedImage.value) return;
            if (confirm(`确定要将此图片移至回收站吗？\n${selectedImage.value.file_name}`)) {
                deleteImage();
            }
        };

        const deleteImage = async () => {
            const path = selectedImage.value.file_path;
            try {
                const res = await fetch(`/api/image?path=${encodeURIComponent(path)}`, {
                    method: 'DELETE'
                });

                if (res.status === 405) {
                    alert("删除失败 (405): 服务器拒绝了 DELETE 请求。\n这通常是因为后端代码已更新但服务器未重启。\n请在终端中按下 Ctrl+C 停止后再重新运行 python server/app.py 即可解决。");
                    return;
                }

                const data = await res.json();
                if (data.success) {
                    // 从本地数组中移除，实现即时刷新的视觉效果
                    const index = images.value.findIndex(img => img.file_path === path);
                    if (index !== -1) {
                        images.value.splice(index, 1);
                    }

                    // 自动回到主页（关闭详情弹窗）
                    closeDetail();

                    showNotification("图片已成功移至回收站", "success");
                } else {
                    throw new Error(data.detail || "删除失败");
                }
            } catch (err) {
                console.error("Delete error:", err);
                showNotification("请求删除失败", "error");
            }
        };

        // Watch for modal states
        watch(showAIModal, (val) => {
            if (val) pushModalState('ai');
        });

        const handleClipboardImport = async () => {
            try {
                const items = await navigator.clipboard.read();
                for (const item of items) {
                    if (item.types.includes('image/png') || item.types.includes('image/jpeg')) {
                        const blob = await item.getType(item.types.find(t => t.startsWith('image/')));
                        const reader = new FileReader();
                        reader.onload = async (e) => {
                            const base64 = e.target.result;
                            aiLoading.value = true;
                            try {
                                const resp = await fetch('/api/ai/optimize', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ mode: 'image', user_input: '', existing_prompt: '', image_b64: base64 })
                                });
                                const data = await resp.json();
                                genParams.prompt = data.result;
                                showNotification("已从剪贴板读取图片并转换为提示词", "success");
                            } catch (e) { showNotification("识别剪贴板图片失败: " + e.message, "error"); }
                            finally { aiLoading.value = false; }
                        };
                        reader.readAsDataURL(blob);
                        return;
                    }
                }
                const text = await navigator.clipboard.readText();
                if (text) {
                    genParams.prompt = text;
                    showNotification("已从剪贴板导入文本提示词", "success");
                }
            } catch (err) {
                showNotification("无法访问剪贴板，请确保已授予权限", "error");
            }
        };

        // --- Standard helpers ---
        const refreshImages = () => fetchImages(true);
        const fileName = (path) => path?.split(/[/\\]/).pop() || "";

        const onGalleryScroll = (e) => {
            if (activeTab.value !== 'gallery') return;
            const el = e.target;
            if (el.scrollTop + el.clientHeight >= el.scrollHeight - 600) {
                fetchImages();
            }
        };

        const checkFillScreen = () => {
            if (activeTab.value !== 'gallery' || !hasMore.value || loading.value) return;

            const el = document.querySelector('.gallery-scroll-area');
            if (el && el.scrollHeight <= el.clientHeight + 150) {
                // 容器未填满，继续加载下一页
                fetchImages();
            }
        };

        // Watchers
        watch(showFilters, (val) => {
            if (val) pushModalState('filters');
        });

        // Responsive Layout Logic
        const windowWidth = ref(window.innerWidth);
        const isDesktop = computed(() => windowWidth.value >= 1024);
        const galleryScale = ref(180); // Grid column width in px

        const columnCount = computed(() => {
            const containerWidth = windowWidth.value - 100;
            if (isDesktop.value && activeTab.value === 'gallery') {
                return Math.max(2, Math.floor(containerWidth / galleryScale.value));
            }
            if (windowWidth.value >= 768) return 4;
            if (windowWidth.value >= 480) return 3;
            return 2;
        });

        // Grid Images (Left to Right Layout)
        const gridImages = computed(() => {
            return images.value;
        });

        const handleResize = () => {
            windowWidth.value = window.innerWidth;
            // 窗口变大后，检查是否需要补全图片（节流处理）
            scheduleCheckFill();
        };

        // Keyboard Navigation
        const handleKeydown = (e) => {
            if (!selectedImage.value) return;

            const idx = images.value.findIndex(i => i.file_path === selectedImage.value.file_path);
            if (idx === -1) return;

            if (e.key === 'ArrowLeft') {
                if (idx > 0) viewDetail(images.value[idx - 1], false);
            } else if (e.key === 'ArrowRight') {
                if (idx < images.value.length - 1) viewDetail(images.value[idx + 1], false);
            } else if (e.key === 'Escape') {
                closeDetail();
            }
        };

        // Theme Logic
        const isDark = ref(localStorage.getItem('theme') !== 'light');
        const toggleTheme = () => {
            isDark.value = !isDark.value;
            localStorage.setItem('theme', isDark.value ? 'dark' : 'light');
            updateThemeClass();
        };
        const updateThemeClass = () => {
            if (isDark.value) document.documentElement.classList.add('dark');
            else document.documentElement.classList.remove('dark');
        };

        // Automatic System Theme Detection
        const watchSystemTheme = () => {
            const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
            const handleChange = (e) => {
                if (!localStorage.getItem('theme')) {
                    isDark.value = e.matches;
                    updateThemeClass();
                }
            };
            mediaQuery.addEventListener('change', handleChange);

            // Initial check if no manual setting exists
            if (!localStorage.getItem('theme')) {
                isDark.value = mediaQuery.matches;
                updateThemeClass();
            }
        };

        onMounted(() => {
            updateThemeClass();
            watchSystemTheme(); // Support auto system theme
            window.addEventListener('resize', handleResize);
            window.addEventListener('keydown', handleKeydown);
            fetchImages();
            fetchFilters();
            pollComfyStatus();
        });

        return {
            activeTab, images, loading, searchKeyword, showFilters, filterData, selectedFilters,
            showAIModal, aiInput, aiResult, aiTarget,
            aiLoading, isGenerating, comfyStatus, queueData, genParams,
            selectedImage, meta, imageAnimationClass, gridImages, isDesktop, galleryScale,
            isDark, toggleTheme, settingsWidth,
            refreshImages, toggleFilter, isFilterSelected, resetFilters, applyFilters,
            openAIModal, runAIOptimize, copyAIResult,
            submitGeneration, viewDetail, closeDetail, confirmDelete, fileName,
            applyToWorkspace, handleFileImport, handleClipboardImport, fileInput, onFileChanged,
            handleTouchStart, handleTouchEnd, onGalleryScroll,
            startResize, getParam, getImageDimensions, handleWheel, navigateImage
        };
    }
}).mount('#app');
