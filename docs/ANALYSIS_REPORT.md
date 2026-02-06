# 项目分析报告 (Project Analysis Report)

**生成日期**: 2026-01-29
**评估对象**: AIMG Pro (Desktop + Web Hybrid)

## 📊 总体评分: 70/100

| 维度 | 评分 | 简评 |
|---|---|---|
| **架构设计** | 7.5/10 | 混合架构 (PyQt + FastAPI subprocess) 设计巧妙，适合本地工具。 |
| **代码质量** | 7.0/10 | 后端逻辑清晰，但前端 (Web) 严重耦合。 |
| **安全性** | **4.0/10** | 存在高危的任意文件读取漏洞 (LFI)，且服务暴露在局域网。 |
| **可维护性** | 6.5/10 | Desktop 端结构良好 (`src/ui`)，Web 端结构糟糕 (`App.vue` Monolith)。 |

---

## 🔴 严重缺陷 (Critical Issues)

### 1. 任意文件读取漏洞 (Arbitrary File Read / Path Traversal)
- **位置**: `server/app.py` 的 `/api/image/raw` 和 `/api/image/thumb` 接口。
- **问题描述**: 接口直接接受 `path` 参数并读取文件，仅做了 `os.path.normpath` 处理，未检查该路径是否在用户配置的“允许文件夹”内。
- **风险**: 攻击者可以通过 `curl "http://[IP]:8000/api/image/raw?path=C:/Windows/System32/drivers/etc/hosts"` 读取用户电脑上的**任意文件**。
- **加剧因素**: `main.py` 默认将 Server 绑定在 `0.0.0.0`，这意味着局域网内的任何设备都可以利用此漏洞攻破运行该软件的电脑。

### 2. Web 前端架构单体化 (Monolithic Frontend)
- **位置**: `web/src/App.vue`.
- **问题描述**: 整个 Web 应用的所有逻辑（API 请求、状态管理、UI 渲染、样式、ComfyUI 交互）全部写在**一个 500+ 行的文件**中。
- **影响**: 极难维护，难以复用组件，违反“关注点分离”原则。`web/src/components` 目录缺失。

---

## 🟡 中等风险与建议 (Medium Risks)

### 1. 数据库事务风险
- **位置**: `server/app.py` 的 `scan_folders` 函数。
- **问题**: 批量插入使用了简单的 `for` 循环，虽然 SQLite 在单线程下安全，但目前的 try-except 块可能会在发生部分错误时导致数据不一致，且没有显式的事务回滚机制。

### 2. 静态资源缓存策略
- **位置**: `server/app.py`.
- **问题**: 试图通过中间件 `add_no_cache_headers` 解决缓存问题，但逻辑较为粗暴（Year Long vs No Cache）。建议引入基于文件 Hash 的 ETag 机制，既能缓存又能及时更新。

---

## 🟢 架构亮点 (Good Points)

1.  **混合应用模式**: 利用 `main.py` 启动子进程运行 FastAPI，既保留了 PyQt 的原生桌面体验，又低成本扩展了移动端访问能力。
2.  **SQL 注入防护**: `src/core/database.py` 中使用了参数化查询 (`?`), 有效防止了基础的 SQL 注入。
3.  **ComfyUI 集成**: 后端直接代理 ComfyUI 请求，解决了跨域问题，且逻辑封装清晰。

---

## 🛣️ 改进路线图 (Improvement Roadmap)

### 阶段 1: 紧急修复 (Security Hotfix)
- [ ] **修复 LFI**: 在 `get_raw_image` 中引入 `db.get_unique_folders()` 校验，确保请求的 `path` 是已索引文件夹的子路径。
- [ ] **绑定与鉴权**: 默认绑定到 `127.0.0.1`，或者在局域网模式下增加简单的访问 Token/密码。

### 阶段 2: 前端重构 (Frontend Refactor)
- [ ] 拆分组件：
  - `components/ImageList.vue`
  - `components/ImageViewer.vue`
  - `components/SettingsPanel.vue`
  - `components/PromptBar.vue`
- [ ] 引入 `pinia` 或 `composables` (如 `useImages.js`) 抽离状态逻辑。

### 阶段 3: 性能优化
- [ ] 优化 `scan_folders`: 现在的扫描是阻塞式的，虽然有 `concurrent.futures` 解析元数据，但 IO 遍历仍可能卡顿。建议改为完全异步的生成器模式。

---

## 结论
该项目作为一个原型或个人工具非常出色，功能完备。但如果计划公开发布或在不可信网络环境中使用，**必须**先修复安全性问题。
