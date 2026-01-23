from PyQt6.QtCore import QAbstractListModel, Qt, QSize, pyqtSignal, QModelIndex
from PyQt6.QtGui import QImage, QPixmap, QIcon
import os

class ImageModel(QAbstractListModel):
    """
    高性能图片列表模型，仅在需要时加载数据。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.image_data = [] # 存储字典: {'path': str, 'name': str, 'thumb': QImage}

    def rowCount(self, parent=None):
        return len(self.image_data)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.image_data):
            return None

        item = self.image_data[index.row()]

        if role == Qt.ItemDataRole.DisplayRole:
            return item['name']
        
        if role == Qt.ItemDataRole.DecorationRole:
            thumb = item.get('thumb')
            if thumb:
                return QIcon(QPixmap.fromImage(thumb))
            return None # 也可以返回一个占位图标

        if role == Qt.ItemDataRole.UserRole:
            return item['path']

        return None

    def add_image(self, path, thumb=None, index=None):
        """添加图片到模型"""
        name = os.path.basename(path)
        new_item = {'path': path, 'name': name, 'thumb': thumb}
        
        if index is None:
            index = len(self.image_data)
            self.beginInsertRows(QModelIndex(), index, index)
            self.image_data.append(new_item)
            self.endInsertRows()
        else:
            self.beginInsertRows(QModelIndex(), index, index)
            self.image_data.insert(index, new_item)
            self.endInsertRows()

    def update_thumbnail(self, path, thumb):
        """更新已存在项的缩略图"""
        for i, item in enumerate(self.image_data):
            if item['path'] == path:
                item['thumb'] = thumb
                idx = self.index(i)
                self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])
                break

    def clear(self):
        self.beginResetModel()
        self.image_data = []
        self.endResetModel()
        
    def get_path(self, index):
        if 0 <= index < len(self.image_data):
            return self.image_data[index]['path']
        return None
