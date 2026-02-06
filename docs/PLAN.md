# 项目分析与改进计划 (Project Analysis & Improvement Plan)

## 📌 当前状态
- **Security**: 已修复 LFI 漏洞，恢复 `0.0.0.0` 绑定以支持移动端。
- **Frontend**: 已完成组件化重构 (`ImageList`, `ImageViewer`, `FilterModal`, `InfoPanel`)。
- **Performance**: 已禁用 HMR。

## 📱 移动端适配计划 (Mobile Adaptation Strategy)

### 目标
实现 "Write Once, Run Everywhere"。确保 Web 端在手机浏览器 (iOS Safari, Android Chrome) 上有一流的原生应用体验。

### 涉及代理 (Agents)
| 代理 (Agent) | 职责 |
|---|---|
| **Mobile UX Designer** | 设计移动端交互流程（手势、抽屉式导航）。 |
| **Frontend Specialist** | 实现响应式布局 (Responsive Layout)。 |
| **Test Engineer** | 验证不同视口下的表现。 |

### 核心变更 (Proposed Changes)

#### 1. 响应式布局 (Layout)
- **桌面端**: 三栏布局 (左侧列表 | 中间视图 | 右侧参数)。
- **移动端**: 单栏布局 + 底部导航栏/抽屉。
  - **默认视图**: 图片网格 (ImageList)。
  - **详情视图**: 点击图片后全屏覆盖 (ImageViewer)，支持手势关闭。
  - **参数面板**: 通过底部 Sheet 或侧边抽屉唤起。

#### 2. 交互优化 (Interactions)
- [ ] **Touch Actions**: 禁用不必要的双击缩放 (`touch-action: manipulation`)。
- [ ] **Gestures**: 在查看大图时支持双指缩放 (Pinch-to-zoom) 和单指拖拽。
- [ ] **Buttons**: 增大点击热区 (min 44px)。

#### 3. 组件改造
- `App.vue`: 引入 `useWindowSize` 或 CSS Media Queries 控制布局模式。
- `ImageList.vue`: 手机端默认为 2 列或 1 列。
- `InfoPanel.vue`: 手机端改为浮层 (Overlay/Sheet) 样式。
- `ImageViewer.vue`: 增加关闭按钮 (Mobile only)，优化触摸事件。

## ✅ 验证计划
- 使用 Chrome DevTools 模拟 iPhone 12/14 Pro。
- 检查横竖屏切换表现。

---

## 📅 执行顺序
1.  **Meta Tag**: 确认 `viewport` 设置。
2.  **App Framework**: 修改 CSS Grid/Flex 布局为响应式。
3.  **Component Adapt**: 逐个调整组件样式。
