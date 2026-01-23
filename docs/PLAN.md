# 核心优化执行计划 (PLAN.md)

本项目将进入性能重构阶段，重点解决图像量级提升带来的延迟问题。

## 指派任务组
- **数据库架构师 (`database-architect`)**: 负责 FTS5 虚拟表迁移和 LoRA 关系表重构。
- **前端专家 (`frontend-specialist`)**: 负责将 `QListWidget` 迁移至 `QListView` (虚拟列表) 并实现同步缩放。
- **性能优化师 (`performance-optimizer`)**: 负责实现 WebP 持久化缩略图缓存机制。
- **测试工程师 (`test-engineer`)**: 负责验证元数据解析的一致性及检索性能。

## 执行步骤

### 阶段 1: 基础设施 (Foundation)
1. **[DB]** 迁移 SQLite 结构，增加 FTS5 支持。
2. **[Cache]** 实现 `ThumbnailCache` 类，支持磁盘读写。

### 阶段 2: 核心组件 (Core)
1. **[UI]** 编写 `ImageModel` (QAbstractListModel) 代替现有列表。
2. **[UI]** 重构 `ThumbnailList` 使用 `QListView`。
3. **[Core]** 优化 `loader.py` 使其支持批量事务。

### 阶段 3: 功能增强 (Polish)
1. **[UI]** 实现 `ComparisonView` 的同步视角。
2. **[UI]** 实现参数面板的“一键回填”逻辑。

## 验证计划
- 扫描 1000+ 带元数据的图片目录，内存占用需低于 150MB。
- 模糊搜索提示词响应时间 < 50ms。
