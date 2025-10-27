#!/usr/bin/env python3
import os
import re
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

from PySide6 import QtWidgets, QtCore, QtGui


class DropPathLine(QtWidgets.QLineEdit):
    """ドラッグ&ドロップ対応のパス入力欄"""
    
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setPlaceholderText("フォルダをドラッグ&ドロップ")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if u.isLocalFile():
                path = u.toLocalFile()
                if os.path.isdir(path):
                    self.setText(path)
                    e.acceptProposedAction()
                    return
        e.ignore()


class FullScreenViewer(QtWidgets.QWidget):
    """フルスクリーン画像ビューア"""
    def __init__(self, parent, initial_index=0):
        super().__init__()
        self.parent_window = parent
        self.current_index = initial_index

        # フルスクリーン設定
        self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint)
        self.setStyleSheet("background-color: black;")

        # 画像表示ラベル（親ウィジェットの子として配置）
        self.image_label = QtWidgets.QLabel(self)
        self.image_label.setAlignment(QtCore.Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color: black;")

        # 情報表示ラベル（画像の上に重ねて左下に配置）
        self.info_label = QtWidgets.QLabel(self)
        self.info_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.info_label.setStyleSheet("color: white; background-color: rgba(0, 0, 0, 180); padding: 8px; font-size: 12px;")
        self.info_label.raise_()  # 最前面に

        self._current_pixmap = None

        # フルスクリーン表示
        self.showFullScreen()

        # 初期画像を表示
        self.show_current_image()

        self.show_current_image()

    def get_all_files_in_current_group(self):
        """現在のグループ内の全ファイルリストを取得"""
        left_item = self.parent_window.left_list.currentItem()
        middle_item = self.parent_window.middle_list.currentItem()
        
        if not (left_item and middle_item):
            return []
        
        left_key = left_item.text()
        middle_key = middle_item.data(QtCore.Qt.UserRole)
        
        filelist = self.parent_window.group_dict.get(left_key, [])
        middle_groups = self.parent_window.get_middle_groups(filelist)
        files = middle_groups.get(middle_key, [])
        
        return [os.path.join(self.parent_window.image_folder, f) for f in files]

    def show_current_image(self):
        """現在のインデックスの画像を表示"""
        files = self.get_all_files_in_current_group()
        
        if not files:
            self.close()
            return
        
        # インデックスを範囲内に収める
        self.current_index = max(0, min(self.current_index, len(files) - 1))
        
        filepath = files[self.current_index]
        
        try:
            pixmap = QtGui.QPixmap(filepath)
            if not pixmap.isNull():
                self._current_pixmap = pixmap
                self.update_scaled_pixmap()
                
                # 情報表示を更新
                filename = os.path.basename(filepath)
                info_text = f"{self.current_index + 1} / {len(files)}  -  {filename}"
                self.info_label.setText(info_text)
            else:
                self.info_label.setText("画像を読み込めませんでした")
        except Exception as e:
            self.info_label.setText(f"エラー: {e}")

    def update_scaled_pixmap(self):
        """画像をスクリーンサイズに合わせて表示"""
        if self._current_pixmap:
            scaled = self._current_pixmap.scaled(
                self.size(),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation
            )
            self.image_label.setPixmap(scaled)

    def resizeEvent(self, event):
        """ウィンドウサイズ変更時"""
        super().resizeEvent(event)
        # 画像ラベルを画面全体に
        self.image_label.setGeometry(0, 0, self.width(), self.height())
        # 情報ラベルを左下に配置
        info_height = 35
        info_width = min(600, self.width() - 20)
        self.info_label.setGeometry(10, self.height() - info_height - 10, info_width, info_height)
        # 画像を再スケール
        self.update_scaled_pixmap()

    def keyPressEvent(self, event):
        """キーボード操作"""
        if event.key() == QtCore.Qt.Key_Escape:
            self.close()
        elif event.key() in (QtCore.Qt.Key_Right, QtCore.Qt.Key_Down):
            # 次の画像
            self.current_index += 1
            files = self.get_all_files_in_current_group()
            
            if self.current_index >= len(files):
                # 現在のグループの最後に到達 → 次のグループへ
                if self.move_to_next_middle_group():
                    self.current_index = 0
                    files = self.get_all_files_in_current_group()
                else:
                    # 次のグループがない場合は最初に戻る
                    self.current_index = 0
            
            self.show_current_image()
            self.parent_window.right_list.setCurrentRow(self.current_index)
            
        elif event.key() in (QtCore.Qt.Key_Left, QtCore.Qt.Key_Up):
            # 前の画像
            self.current_index -= 1
            
            if self.current_index < 0:
                # 現在のグループの最初に到達 → 前のグループへ
                if self.move_to_prev_middle_group():
                    files = self.get_all_files_in_current_group()
                    self.current_index = len(files) - 1
                else:
                    # 前のグループがない場合は最後に戻る
                    files = self.get_all_files_in_current_group()
                    self.current_index = len(files) - 1
            
            self.show_current_image()
            self.parent_window.right_list.setCurrentRow(self.current_index)
        else:
            super().keyPressEvent(event)
    
    def move_to_next_middle_group(self):
        """次の中間グループに移動"""
        middle_list = self.parent_window.middle_list
        current_row = middle_list.currentRow()
        
        if current_row < middle_list.count() - 1:
            # 次のグループがある
            middle_list.setCurrentRow(current_row + 1)
            return True
        else:
            # 最後のグループ → 左リストの次に移動
            return self.move_to_next_left_group()
    
    def move_to_prev_middle_group(self):
        """前の中間グループに移動"""
        middle_list = self.parent_window.middle_list
        current_row = middle_list.currentRow()
        
        if current_row > 0:
            # 前のグループがある
            middle_list.setCurrentRow(current_row - 1)
            return True
        else:
            # 最初のグループ → 左リストの前に移動
            return self.move_to_prev_left_group()
    
    def move_to_next_left_group(self):
        """次の左グループに移動"""
        left_list = self.parent_window.left_list
        current_row = left_list.currentRow()
        
        if current_row < left_list.count() - 1:
            # 次のグループがある
            left_list.setCurrentRow(current_row + 1)
            # 中リストの最初を選択
            if self.parent_window.middle_list.count() > 0:
                self.parent_window.middle_list.setCurrentRow(0)
            return True
        return False
    
    def move_to_prev_left_group(self):
        """前の左グループに移動"""
        left_list = self.parent_window.left_list
        current_row = left_list.currentRow()
        
        if current_row > 0:
            # 前のグループがある
            left_list.setCurrentRow(current_row - 1)
            # 中リストの最後を選択
            middle_count = self.parent_window.middle_list.count()
            if middle_count > 0:
                self.parent_window.middle_list.setCurrentRow(middle_count - 1)
            return True
        return False

    def mousePressEvent(self, event):
        """マウスクリックで閉じる"""
        if event.button() == QtCore.Qt.RightButton:
            self.close()


class ImagePreviewWidget(QtWidgets.QLabel):
    """画像プレビュー表示ウィジェット"""
    
    # ダブルクリックシグナル
    doubleClicked = QtCore.Signal()
    
    def __init__(self):
        super().__init__()
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setMinimumSize(300, 300)
        self.setStyleSheet("QLabel { background-color: #2b2b2b; color: #888; border: 1px solid #444; }")
        self.setText("画像を選択してください\n\nダブルクリックでフルスクリーン表示")
        self.setScaledContents(False)
        self._current_pixmap = None

    def set_image(self, filepath):
        """画像を読み込んで表示"""
        if not filepath or not os.path.exists(filepath):
            self.clear_image()
            return
        
        try:
            pixmap = QtGui.QPixmap(filepath)
            if pixmap.isNull():
                self.setText("画像を読み込めませんでした")
                self._current_pixmap = None
            else:
                self._current_pixmap = pixmap
                self._update_scaled_pixmap()
        except Exception as e:
            self.setText(f"エラー: {e}")
            self._current_pixmap = None

    def clear_image(self):
        """画像をクリア"""
        self.setText("画像を選択してください\n\nダブルクリックでフルスクリーン表示")
        self._current_pixmap = None

    def _update_scaled_pixmap(self):
        """ウィンドウサイズに合わせて画像を拡大縮小"""
        if self._current_pixmap:
            scaled = self._current_pixmap.scaled(
                self.size(), 
                QtCore.Qt.KeepAspectRatio, 
                QtCore.Qt.SmoothTransformation
            )
            self.setPixmap(scaled)

    def resizeEvent(self, event):
        """ウィンドウサイズ変更時に画像を再スケール"""
        super().resizeEvent(event)
        self._update_scaled_pixmap()

    def mouseDoubleClickEvent(self, event):
        """ダブルクリックイベント"""
        if event.button() == QtCore.Qt.LeftButton:
            self.doubleClicked.emit()


class ImageGroupNavigator(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("画像グループナビゲーター")
        self.resize(1200, 700)
        
        # 設定ファイルのパス
        self.config_path = Path.home() / ".image_group_navigator_config.json"
        
        # 初期化
        self.image_folder = ""
        self.group_dict = {}
        self.group_keys = []
        self.sort_order = "name"  # "name" または "date"
        self.fullscreen_viewer = None
        
        # UI構築
        self.setup_ui()
        
        # 設定を読み込み
        self.load_settings()
        
        # 初期フォルダがあればスキャン
        if self.image_folder and os.path.isdir(self.image_folder):
            self.scan_folder()

    def setup_ui(self):
        """UI構築"""
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)
        
        # フォルダ選択部分
        folder_layout = QtWidgets.QHBoxLayout()
        folder_layout.addWidget(QtWidgets.QLabel("画像フォルダ:"))
        self.folder_input = DropPathLine()
        self.folder_input.returnPressed.connect(self.on_folder_changed)
        folder_layout.addWidget(self.folder_input, 1)
        
        browse_btn = QtWidgets.QPushButton("参照...")
        browse_btn.clicked.connect(self.browse_folder)
        folder_layout.addWidget(browse_btn)
        
        scan_btn = QtWidgets.QPushButton("スキャン")
        scan_btn.clicked.connect(self.scan_folder)
        folder_layout.addWidget(scan_btn)
        
        main_layout.addLayout(folder_layout)
        
        # ソート順選択部分
        sort_layout = QtWidgets.QHBoxLayout()
        sort_layout.addWidget(QtWidgets.QLabel("ソート順:"))
        
        self.sort_name_radio = QtWidgets.QRadioButton("ファイル名順")
        self.sort_name_radio.setChecked(True)
        self.sort_name_radio.toggled.connect(self.on_sort_changed)
        sort_layout.addWidget(self.sort_name_radio)
        
        self.sort_date_radio = QtWidgets.QRadioButton("作成日順（新しい順）")
        self.sort_date_radio.toggled.connect(self.on_sort_changed)
        sort_layout.addWidget(self.sort_date_radio)
        
        sort_layout.addStretch()
        main_layout.addLayout(sort_layout)
        
        # メインエリア（3列リスト + プレビュー）
        content_layout = QtWidgets.QHBoxLayout()
        
        # 左リスト（グループ先頭）
        left_widget = self.create_list_widget("グループ先頭", with_buttons=True)
        self.left_list = left_widget['list']
        self.left_up_btn = left_widget['up_btn']
        self.left_down_btn = left_widget['down_btn']
        content_layout.addWidget(left_widget['container'], 1)
        
        # 中リスト（グループ中間）
        middle_widget = self.create_list_widget("グループ中間", with_buttons=True)
        self.middle_list = middle_widget['list']
        self.middle_up_btn = middle_widget['up_btn']
        self.middle_down_btn = middle_widget['down_btn']
        content_layout.addWidget(middle_widget['container'], 1)
        
        # 右リスト（ファイル名）
        right_widget = self.create_list_widget("ファイル名", with_buttons=True)
        self.right_list = right_widget['list']
        self.right_up_btn = right_widget['up_btn']
        self.right_down_btn = right_widget['down_btn']
        content_layout.addWidget(right_widget['container'], 1)
        
        # プレビュー
        preview_container = QtWidgets.QWidget()
        preview_layout = QtWidgets.QVBoxLayout(preview_container)
        preview_layout.addWidget(QtWidgets.QLabel("プレビュー"))
        self.preview_widget = ImagePreviewWidget()
        self.preview_widget.doubleClicked.connect(self.show_fullscreen)
        preview_layout.addWidget(self.preview_widget, 1)
        content_layout.addWidget(preview_container, 1)
        
        main_layout.addLayout(content_layout, 1)
        
        # ステータスバー
        self.statusBar().showMessage("フォルダを選択してください")
        
        # シグナル接続
        self.connect_signals()

    def create_list_widget(self, title, with_buttons=False):
        """リストウィジェット（ボタン付き）を作成"""
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        
        layout.addWidget(QtWidgets.QLabel(title))
        
        list_widget = QtWidgets.QListWidget()
        list_widget.setFont(QtGui.QFont("Helvetica", 12))
        layout.addWidget(list_widget, 1)
        
        result = {'container': container, 'list': list_widget}
        
        if with_buttons:
            btn_layout = QtWidgets.QHBoxLayout()
            up_btn = QtWidgets.QPushButton("↑")
            down_btn = QtWidgets.QPushButton("↓")
            btn_layout.addWidget(up_btn)
            btn_layout.addWidget(down_btn)
            layout.addLayout(btn_layout)
            result['up_btn'] = up_btn
            result['down_btn'] = down_btn
        
        return result

    def connect_signals(self):
        """シグナル接続"""
        # リスト選択変更
        self.left_list.itemSelectionChanged.connect(self.on_left_select)
        self.middle_list.itemSelectionChanged.connect(self.on_middle_select)
        self.right_list.itemSelectionChanged.connect(self.on_right_select)
        
        # ダブルクリック
        self.left_list.itemDoubleClicked.connect(lambda: self.open_current_image(self.left_list))
        self.middle_list.itemDoubleClicked.connect(lambda: self.open_current_image(self.middle_list))
        self.right_list.itemDoubleClicked.connect(lambda: self.open_current_image(self.right_list))
        
        # Enterキー
        self.left_list.itemActivated.connect(lambda: self.open_current_image(self.left_list))
        self.middle_list.itemActivated.connect(lambda: self.open_current_image(self.middle_list))
        self.right_list.itemActivated.connect(lambda: self.open_current_image(self.right_list))
        
        # ↑↓ボタン
        self.left_up_btn.clicked.connect(lambda: self.move_selection(self.left_list, -1))
        self.left_down_btn.clicked.connect(lambda: self.move_selection(self.left_list, 1))
        self.middle_up_btn.clicked.connect(lambda: self.move_selection(self.middle_list, -1))
        self.middle_down_btn.clicked.connect(lambda: self.move_selection(self.middle_list, 1))
        self.right_up_btn.clicked.connect(lambda: self.move_selection(self.right_list, -1))
        self.right_down_btn.clicked.connect(lambda: self.move_selection(self.right_list, 1))

    def keyPressEvent(self, event):
        """キーボードショートカット"""
        focused = QtWidgets.QApplication.focusWidget()
        
        # 矢印キー（リストにフォーカスがある場合は標準動作）
        if isinstance(focused, QtWidgets.QListWidget):
            if event.key() == QtCore.Qt.Key_Return or event.key() == QtCore.Qt.Key_Enter:
                self.open_current_image(focused)
                event.accept()
                return
        
        super().keyPressEvent(event)

    def show_fullscreen(self):
        """フルスクリーン表示を開く"""
        current_index = self.right_list.currentRow()
        if current_index >= 0:
            self.fullscreen_viewer = FullScreenViewer(self, current_index)
            self.fullscreen_viewer.show()

    def browse_folder(self):
        """フォルダ選択ダイアログ"""
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, 
            "画像フォルダを選択",
            self.folder_input.text() or str(Path.home())
        )
        if folder:
            self.folder_input.setText(folder)
            self.on_folder_changed()

    def on_folder_changed(self):
        """フォルダパス変更時"""
        self.scan_folder()

    def on_sort_changed(self):
        """ソート順変更時"""
        if self.sort_name_radio.isChecked():
            self.sort_order = "name"
        else:
            self.sort_order = "date"
        
        self.save_settings()
        
        # 再ソート
        if self.group_keys:
            self.refresh_left_list()

    def get_file_creation_time(self, filename):
        """ファイルの作成日時を取得"""
        try:
            filepath = os.path.join(self.image_folder, filename)
            return os.path.getctime(filepath)
        except:
            return 0

    def get_group_creation_time(self, group_key):
        """グループの代表ファイル（最初のファイル）の作成日時を取得"""
        filelist = self.group_dict.get(group_key, [])
        if not filelist:
            return 0
        return self.get_file_creation_time(filelist[0])

    def format_creation_time(self, filename):
        """ファイルの作成日時をフォーマット"""
        try:
            timestamp = self.get_file_creation_time(filename)
            dt = datetime.fromtimestamp(timestamp)
            return dt.strftime("%Y/%m/%d")
        except:
            return ""

    def get_middle_group_first_file(self, left_key, middle_key):
        """中間グループの最初のファイルを取得"""
        filelist = self.group_dict.get(left_key, [])
        middle_groups = self.get_middle_groups(filelist)
        files = middle_groups.get(middle_key, [])
        return files[0] if files else None

    def refresh_left_list(self):
        """左リストを再描画"""
        # 現在の選択を記憶
        current_item = self.left_list.currentItem()
        current_key = current_item.text() if current_item else None
        
        # ソート
        if self.sort_order == "date":
            # 作成日順（新しい順）
            self.group_keys = sorted(
                self.group_dict.keys(), 
                key=lambda k: self.get_group_creation_time(k),
                reverse=True
            )
        else:
            # ファイル名順
            self.group_keys = sorted(self.group_dict.keys(), key=self.natural_key)
        
        # 左リスト更新
        self.left_list.clear()
        for key in self.group_keys:
            self.left_list.addItem(key)
        
        # 前回の選択を復元
        if current_key:
            items = self.left_list.findItems(current_key, QtCore.Qt.MatchExactly)
            if items:
                self.left_list.setCurrentItem(items[0])
        elif self.group_keys:
            self.left_list.setCurrentRow(0)

    def scan_folder(self):
        """フォルダをスキャンして画像を読み込み"""
        folder = self.folder_input.text()
        
        if not folder:
            QtWidgets.QMessageBox.warning(self, "エラー", "フォルダパスを入力してください")
            return
        
        if not os.path.isdir(folder):
            QtWidgets.QMessageBox.warning(self, "エラー", f"フォルダが存在しません:\n{folder}")
            return
        
        self.image_folder = folder
        self.save_settings()
        
        try:
            # ファイル一覧取得
            all_files = os.listdir(folder)
            valid_exts = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')
            image_files = [f for f in all_files if f.lower().endswith(valid_exts)]
            
            if not image_files:
                QtWidgets.QMessageBox.information(self, "情報", "画像ファイルが見つかりませんでした")
                return
            
            # グループ化
            self.group_dict = {}
            for filename in image_files:
                prefix = filename.split('_')[0]
                self.group_dict.setdefault(prefix, []).append(filename)
            
            # グループ内は常に番号順にソート
            for key in self.group_dict.keys():
                self.group_dict[key].sort(key=self.natural_key)
            
            # 左リスト更新（ソート順に応じて）
            self.refresh_left_list()
            
            # 中・右リストクリア
            self.middle_list.clear()
            self.right_list.clear()
            self.preview_widget.clear_image()
            
            self.statusBar().showMessage(f"{len(image_files)}個の画像ファイルを読み込みました")
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "エラー", f"フォルダのスキャンに失敗しました:\n{e}")

    def on_left_select(self):
        """左リスト選択時"""
        item = self.left_list.currentItem()
        if not item:
            self.middle_list.clear()
            self.right_list.clear()
            self.preview_widget.clear_image()
            return
        
        group_key = item.text()
        filelist = self.group_dict.get(group_key, [])
        middle_groups = self.get_middle_groups(filelist)
        sorted_middle_keys = sorted(middle_groups.keys(), key=self.natural_key)
        
        self.middle_list.clear()
        for k in sorted_middle_keys:
            # 中間グループの最初のファイルの作成日時を取得
            first_file = self.get_middle_group_first_file(group_key, k)
            if first_file:
                date_str = self.format_creation_time(first_file)
                display_text = f"{k}    {date_str}"
            else:
                display_text = k
            
            item = QtWidgets.QListWidgetItem(display_text)
            # データとして元のキーを保存
            item.setData(QtCore.Qt.UserRole, k)
            self.middle_list.addItem(item)
        
        self.right_list.clear()
        self.preview_widget.clear_image()
        
        # 中リストの最初を選択
        if sorted_middle_keys:
            self.middle_list.setCurrentRow(0)

    def on_middle_select(self):
        """中リスト選択時"""
        left_item = self.left_list.currentItem()
        middle_item = self.middle_list.currentItem()
        
        if not left_item or not middle_item:
            self.right_list.clear()
            self.preview_widget.clear_image()
            return
        
        left_key = left_item.text()
        # UserRoleから元のキーを取得
        middle_key = middle_item.data(QtCore.Qt.UserRole)
        filelist = self.group_dict.get(left_key, [])
        
        self.update_right_list(middle_key, filelist)

    def on_right_select(self):
        """右リスト選択時（プレビュー更新）"""
        filepath = self.get_current_filepath()
        if filepath:
            self.preview_widget.set_image(filepath)
        else:
            self.preview_widget.clear_image()

    def update_right_list(self, middle_key, filelist):
        """右リスト更新"""
        middle_groups = self.get_middle_groups(filelist)
        files = middle_groups.get(middle_key, [])
        
        self.right_list.clear()
        for f in files:
            parts = f.split('_', 2)
            display_name = parts[2] if len(parts) > 2 else f
            if '.' in display_name:
                display_name = os.path.splitext(display_name)[0]
            self.right_list.addItem(display_name)
        
        # 右リストの最初を選択
        if files:
            self.right_list.setCurrentRow(0)

    def get_current_filepath(self):
        """現在選択中の画像ファイルパスを取得"""
        left_item = self.left_list.currentItem()
        middle_item = self.middle_list.currentItem()
        right_item = self.right_list.currentItem()
        
        if not (left_item and middle_item and right_item):
            return None
        
        left_key = left_item.text()
        # UserRoleから元のキーを取得
        middle_key = middle_item.data(QtCore.Qt.UserRole)
        right_idx = self.right_list.currentRow()
        
        filelist = self.group_dict.get(left_key, [])
        middle_groups = self.get_middle_groups(filelist)
        files = middle_groups.get(middle_key, [])
        
        if 0 <= right_idx < len(files):
            return os.path.join(self.image_folder, files[right_idx])
        
        return None

    def open_current_image(self, list_widget):
        """現在選択中の画像を外部アプリで開く"""
        filepath = self.get_current_filepath()
        if not filepath:
            # 左・中リストの場合は最初のファイルを開く
            if list_widget == self.left_list:
                item = self.left_list.currentItem()
                if item:
                    filelist = self.group_dict.get(item.text(), [])
                    if filelist:
                        filepath = os.path.join(self.image_folder, filelist[0])
            elif list_widget == self.middle_list:
                left_item = self.left_list.currentItem()
                middle_item = self.middle_list.currentItem()
                if left_item and middle_item:
                    filelist = self.group_dict.get(left_item.text(), [])
                    middle_key = middle_item.data(QtCore.Qt.UserRole)
                    middle_groups = self.get_middle_groups(filelist)
                    files = middle_groups.get(middle_key, [])
                    if files:
                        filepath = os.path.join(self.image_folder, files[0])
        
        if filepath and os.path.exists(filepath):
            try:
                subprocess.run(['open', filepath], check=True)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "エラー", f"画像を開けませんでした:\n{e}")

    def move_selection(self, list_widget, direction):
        """リストの選択を移動"""
        if list_widget.count() == 0:
            return
        
        current = list_widget.currentRow()
        if current == -1:
            new_index = 0 if direction > 0 else list_widget.count() - 1
        else:
            new_index = current + direction
            new_index = max(0, min(new_index, list_widget.count() - 1))
        
        list_widget.setCurrentRow(new_index)

    @staticmethod
    def natural_key(s):
        """自然順ソート用キー"""
        def try_int(c):
            try:
                return int(c)
            except:
                return c
        return [try_int(c) for c in re.split(r'(\d+)', s)]

    @staticmethod
    def extract_middle_number(name):
        """ファイル名から中間番号を抽出"""
        parts = name.split('_')
        if len(parts) >= 3:
            return parts[1]
        return ""

    def get_middle_groups(self, filelist):
        """中間グループ化"""
        middle_group_dict = {}
        for f in filelist:
            key = self.extract_middle_number(f)
            middle_group_dict.setdefault(key, []).append(f)
        return middle_group_dict

    def load_settings(self):
        """設定を読み込み"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.image_folder = config.get('folder', '')
                    if self.image_folder:
                        self.folder_input.setText(self.image_folder)
                    
                    # ソート順を復元
                    self.sort_order = config.get('sort_order', 'name')
                    if self.sort_order == "date":
                        self.sort_date_radio.setChecked(True)
                    else:
                        self.sort_name_radio.setChecked(True)
            except Exception as e:
                print(f"設定の読み込みに失敗: {e}")

    def save_settings(self):
        """設定を保存"""
        try:
            config = {
                'folder': self.image_folder,
                'sort_order': self.sort_order
            }
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"設定の保存に失敗: {e}")

    def closeEvent(self, event):
        """ウィンドウを閉じる時"""
        self.save_settings()
        event.accept()


def main():
    app = QtWidgets.QApplication(sys.argv)
    window = ImageGroupNavigator()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
