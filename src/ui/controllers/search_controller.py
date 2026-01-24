from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtWidgets import QMainWindow
from typing import Optional

class SearchController(QObject):
    """
    负责处理搜索、筛选和排序逻辑
    """
    def __init__(self, main_window: QMainWindow):
        super().__init__()
        self.main = main_window
        self.current_search_id = "" # 用于防止缩略图加载错乱
        # 搜索防抖
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.perform_search)

    def on_search_changed(self, text: str) -> None:
        """搜索框文字变化回调"""
        self.search_timer.start(300) # 300ms 防抖

    def on_filter_requested(self, filter_type: str, value: str) -> None:
        """模型浏览器筛选请求"""
        if filter_type == "Model": # 注意：signal 发出的是 "Model" (Title Case)
            self.main.current_model = value
            # 当模型改变时，刷新 LoRA 列表以仅显示兼容的 LoRA
            # 这实现了“级联筛选”逻辑，避免用户选择不存在的组合
            if self.main.current_folder:
                loras = self.main.db_manager.get_unique_loras(self.main.current_folder, model_filter=value)
                # ModelExplorer 需要一个新的方法来只更新 LoRA，或者我们即使调用 update_models
                # 但 update_models 需要 models 和 loras。
                # 为了简单和一致性，我们可以只更新 LoRA 部分，或者获取 models 再全更。
                # 获取 Models 代价不大，保持全更最安全
                models = self.main.db_manager.get_unique_models(self.main.current_folder)
                self.main.model_explorer.update_models(models, loras)
                
                # ModelExplorer.update_models 会清除 LoRA 选区(重置为 ALL)，这符合预期
                # 但我们需要确保 current_lora 也重置
                self.main.current_lora = "ALL"
            
        elif filter_type == "Lora": # Signal is "Lora"
            self.main.current_lora = value
            
        self.perform_search()

    def reset_filters(self) -> None:
        """重置所有筛选条件"""
        self.main.search_bar.clear()
        self.main.current_model = "ALL"
        self.main.current_lora = "ALL"
        self.main.model_explorer._clear_selection()
        # 重置时也要恢复完整的 LoRA 列表
        if self.main.current_folder:
            models = self.main.db_manager.get_unique_models(self.main.current_folder)
            loras = self.main.db_manager.get_unique_loras(self.main.current_folder) # 无 filter
            self.main.model_explorer.update_models(models, loras)
            
        self.perform_search()

    def perform_search(self) -> None:
        """执行搜索"""
        # 生成新的搜索 ID
        import uuid
        self.current_search_id = str(uuid.uuid4())
        
        keyword = self.main.search_bar.text().strip()
        model = self.main.current_model
        lora = self.main.current_lora
        
        # UI 反馈
        self.main.statusBar().showMessage(f"正在搜索: {keyword} [Model: {model}, LoRA: {lora}]...")
        
        # 数据库查询
        # 注意：这里耦合了 main_window 的 db_manager，实际应当注入 service
        results = self.main.db_manager.search_images(
            keyword=keyword,
            folder_path=self.main.current_folder,
            model=model,
            lora=lora,
            order_by=self.main.current_sort_by
        )
        
        self.main.statusBar().showMessage(f"搜索完成: 找到 {len(results)} 张图片")
        
        # 更新缩略图列表 (传入当前 search_id)
        self.load_thumbnails_for_list(results, self.current_search_id)

    def _load_search_results(self, paths: list[str], search_id: str) -> None:
        """加载搜索结果"""
        from src.core.loader import SearchThumbnailLoader
        
        # 停止旧的 loader (虽然有了 id 校验，停止也是好的)
        if hasattr(self, 'search_loader') and self.search_loader.isRunning():
            self.search_loader.stop()
            self.search_loader.wait()
            
        self.missing_files_detected = False # 重置标记
        
        # 使用 Controller 自己的 loader 引用
        self.search_loader = SearchThumbnailLoader(paths, self.main.thumb_cache, search_id=search_id)
        self.search_loader.thumbnail_ready.connect(self._on_search_thumb_ready)
        self.search_loader.file_missing.connect(self._on_file_missing)
        self.search_loader.finished.connect(self._on_loader_finished)
        self.search_loader.start()

    def _on_file_missing(self, path: str) -> None:
        """处理文件丢失：从数据库移除僵尸记录"""
        print(f"[Search] Cleaning up missing file: {path}")
        self.missing_files_detected = True # 标记有文件被清理
        try:
            # 这里的 db_manager 是 MainWindow 的实例，我们可以增加一个 delete 方法
            # 或者直接操作 sqlite3 (不推荐，但为了快速修复)
            import sqlite3
            conn = sqlite3.connect(self.main.db_manager.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM images WHERE file_path = ?", (path,))
            # 级联删除 image_loras 会由 FK 自动处理 (如果开启了 PRAGMA foreign_keys = ON)
            # 稳妥起见，我们可能需要手动删，或者信任 DB 结构
            # 我们的 create table 写了 ON DELETE CASCADE，但 sqlite 默认不开启 FK 支持
            # 显式开启
            cursor.execute("PRAGMA foreign_keys = ON")
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[Search] Cleanup error: {e}")
            
    def _on_loader_finished(self):
        """加载完成后，如果有清理过文件，则自动刷新"""
        if self.missing_files_detected:
            print("[Search] Missing files detected during load, auto-refreshing...")
            # 为了避免无限循环（虽然通常不会），可以重置标记
            self.missing_files_detected = False
            # 稍微延迟一下，让 UI 喘口气？或者直接调
            # 直接调用 perform_search 会再次走一遍，这次 DB 里已经没有那些文件了
            self.perform_search()

    def _on_search_thumb_ready(self, index: int, path: str, thumb, search_id: str) -> None:
        """搜索结果缩略图准备就绪"""
        # 关键校验：如果 ID 不匹配，说明这是过期的搜索结果，直接丢弃
        if search_id != self.current_search_id:
            return
            
        # 注意：如果在此期间因为 _on_file_missing 触发了 auto-refresh，
        # 新的 perform_search 会生成新的 search_id，
        # 所以旧的 loader 即使还在发信号也会被这里的 id check 拦截。
        # 完美。
            
        # 再次确认路径是否匹配（双重保险，防止 List 和 Loader 错位）
        # 实际上我们依赖 SearchThumbnailLoader 是按顺序发送的，且 perform_search 先填充了 list
        # 如果 id 匹配，说明 list 就是我们要的那个 list
        self.main.thumbnail_list.update_image_icon(index, thumb) 

    def load_thumbnails_for_list(self, paths: list[str], search_id: str) -> None:
        # 实际上 perform_search 应该先添加 items
        self.main.thumbnail_list.clear_list()
        for path in paths:
             # 先添加占位
             self.main.thumbnail_list.add_image(path)
             
        # 然后启动 loader
        self._load_search_results(paths, search_id)
