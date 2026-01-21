import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from PyQt6.QtCore import QObject, pyqtSignal

class ImageEventHandler(FileSystemEventHandler, QObject):
    """
    处理文件系统事件，过滤图片文件并通过信号发送。
    """
    # 定义信号：路径，事件类型
    new_image_signal = pyqtSignal(str)
    
    # 支持的图片扩展名
    IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}

    def __init__(self):
        FileSystemEventHandler.__init__(self)
        QObject.__init__(self)

    def _is_image(self, path):
        _, ext = os.path.splitext(path)
        return ext.lower() in self.IMAGE_EXTENSIONS

    def on_created(self, event):
        if not event.is_directory and self._is_image(event.src_path):
            print(f"检测到新文件: {event.src_path}")
            self.new_image_signal.emit(event.src_path)

    def on_moved(self, event):
        if not event.is_directory and self._is_image(event.dest_path):
            print(f"文件移动/重命名: {event.dest_path}")
            self.new_image_signal.emit(event.dest_path)

class FileWatcher(QObject):
    """
    管理 watchdog Observer 的生命周期。
    """
    def __init__(self):
        super().__init__()
        self.observer = Observer()
        self.event_handler = ImageEventHandler()

    def start_monitoring(self, path):
        if not os.path.exists(path):
            return False
        
        # 防止重复添加 (简单处理，先停止再开始，或者检查是否已监控)
        self.stop_monitoring()
        
        self.observer = Observer() #虽然init里有，但stop后需要重新init? Observer stop后不能restart
        self.observer.schedule(self.event_handler, path, recursive=False)
        self.observer.start()
        print(f"开始监控文件夹: {path}")
        return True

    def stop_monitoring(self):
        if self.observer.is_alive():
            self.observer.stop()
            self.observer.join()
            print("停止监控")

    def get_signal(self):
        return self.event_handler.new_image_signal
