# AI Image Viewer Pro

本项目是一个基于 PyQt6 的本地 AI 图像浏览与生成工作台，集成 ComfyUI 工作流管理、提示词优化、LoRA 管理与元数据解析。适合需要批量查看与快速复用生成配置的创作者与开发者使用。

## 功能特性

- 本地图片浏览与对比模式
- 生成工作区：提示词、采样器、分辨率、LoRA 等参数管理
- 提示词 AI 优化与历史记录
- ComfyUI 工作流注入与远程生成
- 元数据解析与筛选
- 生成参数自动记忆

## 环境要求

- Python 3.10+
- Windows 10/11（已适配）

依赖包见 requirements.txt。

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 运行

```bash
python main.py
```

### 开发热重载（可选）

```bash
python dev_runner.py
```

## 打包

```bash
python build_app.py
```

打包成功后，输出在 dist/ 目录。

## 目录结构

```
src/
  assets/            默认工作流与资源
  core/              核心逻辑（Comfy 客户端、元数据、数据库等）
  ui/                界面与控制器
```

## 许可

如需开源协议，请自行补充 LICENSE 文件。
