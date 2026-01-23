# Windows 11 风格重构计划 (PLAN_UI.md)

## 目标
将应用的视觉语言从传统的“深色表单”升级为 Windows 11 **Fluent Design** 风格，提升精致感、通透感和易用性。

## 核心变更点

### 1. 材质与通透感 (Materials)
- **模拟 Mica 效果**: 使用层次化的深色/浅色背景，主窗体背景采用更柔和的深灰 (`#202020`) 或浅灰 (`#F3F3F3`)。
- **层级感**: 使用微妙的描边 (`1px solid rgba(255,255,255,0.06)`) 区分不同的面板卡片。

### 2. 圆角与形状 (Geometry)
- **全局圆角**: 所有的按钮、输入框、面板边缘统一使用 `radius: 8px`。
- **卡片化布局**: 侧边栏和主编辑区采用分立的卡片设计，而非生硬的长条分割。

### 3. 字体与排版 (Typography)
- **Segoe UI Variable**: 优先使用 Win11 推荐字体，调整字重 (Font Weight) 以强化层级。
- **间距优化**: 增加组件间的 Padding 和 Margin，营造“呼吸感”。

### 4. 组件微调 (Components)
- **Toolbar**: 简化图标，移除冗余文字，增加悬浮态反馈。
- **ScrollBars**: 细长简约风格，悬浮时稍微变宽。
- **Inputs & Combos**: 底部高亮边框 (`Border Bottom`) 效果，模拟 Win11 焦点状态。

---

## 代理分工
- **frontend-specialist**: 负责 QSS 全局样式的重写及组件布局调整。
- **performance-optimizer**: 负责验证 QSS 复杂渲染下的滚动性能。
- **test-engineer**: 负责多分辨率下的适配验证。

## 风险点
- PyQt6 在 Windows 下的无边框和 Mica 调用较为复杂，初期将先通过纯 QSS 模拟。
