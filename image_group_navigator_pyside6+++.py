#!/usr/bin/env python3
import os
import re
import sys
import json
import queue
import subprocess
from pathlib import Path
from datetime import datetime

from PySide6 import QtWidgets, QtCore, QtGui, QtMultimedia, QtMultimediaWidgets
from PIL import Image
import io
from collections import OrderedDict


class ImageCache:
    """画像キャッシュクラス（LRU方式）"""

    def __init__(self, max_size=10):
        self.max_size = max_size
        self.cache = OrderedDict()

    def get(self, filepath):
        """キャッシュから画像を取得"""
        if filepath in self.cache:
            # アクセスされたので最新に移動
            self.cache.move_to_end(filepath)
            return self.cache[filepath]
        return None

    def put(self, filepath, pixmap):
        """キャッシュに画像を追加"""
        if filepath in self.cache:
            self.cache.move_to_end(filepath)
        else:
            self.cache[filepath] = pixmap
            # 最大サイズを超えたら古いものを削除
            if len(self.cache) > self.max_size:
                self.cache.popitem(last=False)

    def clear(self):
        """キャッシュをクリア"""
        self.cache.clear()


class ImagePreloader(QtCore.QThread):
    """バックグラウンドで画像を読み込むスレッド"""

    imageLoaded = QtCore.Signal(str, object)  # filepath, pixmap/frames

    def __init__(self, parent=None):
        super().__init__(parent)
        self.queue = queue.Queue()
        self.running = False
        self.stop_requested = False

    def load_image(self, filepath):
        """画像読み込みをリクエスト"""
        self.queue.put(filepath)
        if not self.isRunning():
            self.running = True
            self.stop_requested = False
            self.start()

    def stop(self):
        """スレッド停止をリクエスト"""
        self.stop_requested = True
        # ダミーアイテムを追加してブロックを解除
        self.queue.put(None)

    def run(self):
        """バックグラウンド処理"""
        while not self.stop_requested:
            try:
                # タイムアウト付きで次のファイルを取得
                filepath = self.queue.get(timeout=1.0)

                # 停止リクエストのチェック
                if filepath is None or self.stop_requested:
                    break

                if not os.path.exists(filepath):
                    continue

                ext = os.path.splitext(filepath)[1].lower()

                # APNG判定
                if ext == ".png" and self._is_apng(filepath):
                    frames = self._load_apng_frames(filepath)
                    if frames:
                        self.imageLoaded.emit(filepath, frames)
                else:
                    # 静止画
                    pixmap = QtGui.QPixmap(filepath)
                    if not pixmap.isNull():
                        self.imageLoaded.emit(filepath, pixmap)

            except queue.Empty:
                # キューが空の場合は継続
                continue
            except Exception as e:
                print(f"画像読み込みエラー: {e}")

        self.running = False

    def _is_apng(self, filepath):
        """PNGファイルがAPNGかチェック"""
        try:
            with Image.open(filepath) as img:
                return getattr(img, "is_animated", False)
        except:
            return False

    def _load_apng_frames(self, filepath):
        """APNGの全フレームを読み込み"""
        try:
            img = Image.open(filepath)
            frames = []

            for frame_index in range(getattr(img, "n_frames", 1)):
                img.seek(frame_index)
                frame = img.convert("RGBA")

                data = frame.tobytes("raw", "RGBA")
                qimage = QtGui.QImage(
                    data, frame.width, frame.height, QtGui.QImage.Format_RGBA8888
                )
                pixmap = QtGui.QPixmap.fromImage(qimage)
                duration = img.info.get("duration", 100)

                frames.append({"pixmap": pixmap, "duration": duration})

            return frames if frames else None
        except:
            return None


class ShortcutManager:
    """ショートカットキー管理クラス"""

    # デフォルトのショートカット設定
    DEFAULT_SHORTCUTS = {
        "fullscreen_exit": "F",
        "reveal_in_finder": "C",
        "next_middle_group": "Shift+Space",
        "prev_middle_group": "Space",
        "next_left_group": "Down",
        "prev_left_group": "Up",
    }

    # アクション名の日本語表示
    ACTION_NAMES = {
        "fullscreen_exit": "フルスクリーン解除",
        "reveal_in_finder": "Finderでファイルを表示",
        "next_middle_group": "次の中間グループに移動",
        "prev_middle_group": "前の中間グループに移動",
        "next_left_group": "次の左グループに移動",
        "prev_left_group": "前の左グループに移動",
    }

    def __init__(self):
        self.shortcuts = self.DEFAULT_SHORTCUTS.copy()

    def load_from_config(self, config):
        """設定から読み込み"""
        if "shortcuts" in config:
            self.shortcuts.update(config["shortcuts"])

    def save_to_config(self, config):
        """設定に保存"""
        config["shortcuts"] = self.shortcuts

    def get_key_sequence(self, action):
        """アクションに対応するキーシーケンスを取得"""
        return self.shortcuts.get(action, "")

    def set_key_sequence(self, action, key_sequence):
        """アクションにキーシーケンスを設定"""
        self.shortcuts[action] = key_sequence

    def matches_key_event(self, action, event):
        """キーイベントが指定アクションと一致するかチェック"""
        key_seq = self.get_key_sequence(action)
        if not key_seq:
            return False

        # キーシーケンスをパース
        parts = key_seq.split("+")
        required_modifiers = QtCore.Qt.NoModifier
        required_key = None

        for part in parts:
            part = part.strip()
            if part == "Shift":
                required_modifiers |= QtCore.Qt.ShiftModifier
            elif part == "Ctrl" or part == "Control":
                required_modifiers |= QtCore.Qt.ControlModifier
            elif part == "Alt" or part == "Option":
                required_modifiers |= QtCore.Qt.AltModifier
            elif part == "Meta" or part == "Cmd" or part == "Command":
                required_modifiers |= QtCore.Qt.MetaModifier
            elif part == "Space":
                required_key = QtCore.Qt.Key_Space
            elif part == "Up":
                required_key = QtCore.Qt.Key_Up
            elif part == "Down":
                required_key = QtCore.Qt.Key_Down
            elif part == "Left":
                required_key = QtCore.Qt.Key_Left
            elif part == "Right":
                required_key = QtCore.Qt.Key_Right
            elif len(part) == 1:
                # 単一文字キー
                required_key = ord(part.upper())

        if required_key is None:
            return False

        # イベントのキーとモディファイアをチェック
        event_key = event.key()
        event_modifiers = event.modifiers()

        # Shiftキーの特別処理（大文字判定）
        if required_key in range(ord("A"), ord("Z") + 1):
            # 大文字が要求されている場合
            if event_key == required_key and (
                event_modifiers & QtCore.Qt.ShiftModifier
            ):
                return True

        # 通常のキーマッチング
        return event_key == required_key and event_modifiers == required_modifiers


class ShortcutSettingsDialog(QtWidgets.QDialog):
    """ショートカットキー設定ダイアログ"""

    def __init__(self, shortcut_manager, parent=None):
        super().__init__(parent)
        self.shortcut_manager = shortcut_manager
        self.setWindowTitle("ショートカットキー設定")
        self.resize(600, 400)

        layout = QtWidgets.QVBoxLayout(self)

        # 説明ラベル
        info_label = QtWidgets.QLabel(
            "各機能のショートカットキーを設定できます。\n"
            "例: F, Shift+Space, Ctrl+A, Cmd+S など"
        )
        layout.addWidget(info_label)

        # テーブル
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["機能", "ショートカットキー"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)

        # ショートカット一覧を表示
        actions = list(ShortcutManager.DEFAULT_SHORTCUTS.keys())
        self.table.setRowCount(len(actions))

        for row, action in enumerate(actions):
            # 機能名
            name_item = QtWidgets.QTableWidgetItem(
                ShortcutManager.ACTION_NAMES.get(action, action)
            )
            name_item.setFlags(name_item.flags() & ~QtCore.Qt.ItemIsEditable)
            name_item.setData(QtCore.Qt.UserRole, action)  # アクション名を保存
            self.table.setItem(row, 0, name_item)

            # ショートカットキー
            key_item = QtWidgets.QTableWidgetItem(
                self.shortcut_manager.get_key_sequence(action)
            )
            self.table.setItem(row, 1, key_item)

        layout.addWidget(self.table)

        # ボタン
        button_layout = QtWidgets.QHBoxLayout()

        reset_btn = QtWidgets.QPushButton("デフォルトに戻す")
        reset_btn.clicked.connect(self.reset_to_default)
        button_layout.addWidget(reset_btn)

        button_layout.addStretch()

        ok_btn = QtWidgets.QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        button_layout.addWidget(ok_btn)

        cancel_btn = QtWidgets.QPushButton("キャンセル")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    def reset_to_default(self):
        """デフォルト設定に戻す"""
        for row in range(self.table.rowCount()):
            action = self.table.item(row, 0).data(QtCore.Qt.UserRole)
            default_key = ShortcutManager.DEFAULT_SHORTCUTS.get(action, "")
            self.table.item(row, 1).setText(default_key)

    def get_shortcuts(self):
        """現在の設定を取得"""
        shortcuts = {}
        for row in range(self.table.rowCount()):
            action = self.table.item(row, 0).data(QtCore.Qt.UserRole)
            key_seq = self.table.item(row, 1).text().strip()
            shortcuts[action] = key_seq
        return shortcuts


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
        self.info_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        self.info_label.setStyleSheet(
            "color: white; background-color: rgba(0, 0, 0, 180); padding: 12px; font-size: 15px;"
        )
        # 固定の最小サイズを設定（2行分の高さを確保）
        self.info_label.setMinimumHeight(70)
        self.info_label.setMinimumWidth(400)

        # 影効果を追加
        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(8)
        shadow.setColor(QtGui.QColor(0, 0, 0, 200))
        shadow.setOffset(2, 2)
        self.info_label.setGraphicsEffect(shadow)

        self.info_label.raise_()  # 最前面に

        self._current_pixmap = None

        # APNG再生用
        self._apng_frames = []
        self._apng_frame_index = 0
        self._apng_timer = QtCore.QTimer(self)
        self._apng_timer.timeout.connect(self._next_apng_frame)

        # 画像キャッシュと先読み
        self.cache = ImageCache(max_size=10)
        self.preloader = ImagePreloader(self)
        self.preloader.imageLoaded.connect(self._on_image_preloaded)
        self.preload_backward = parent.preload_backward  # 親ウィンドウの設定を使用
        self.preload_forward = parent.preload_forward  # 親ウィンドウの設定を使用
        self._apng_check_cache = {}  # APNG判定結果のキャッシュ
        self._current_files = []  # 現在のファイルリスト
        self._current_filepath = None  # 現在表示中のファイルパス

        # フルスクリーン表示
        self.showFullScreen()

        # 初期画像を表示
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

        # 現在のファイルリストとパスを保存
        self._current_files = files
        self._current_filepath = filepath

        # キャッシュをチェック
        cached = self.cache.get(filepath)
        if cached:
            if isinstance(cached, list):
                # APNGフレーム
                self._show_cached_apng(cached, filepath, files)
            else:
                # 静止画
                self._apng_timer.stop()
                self._apng_frames = []
                self._current_pixmap = cached
                self.update_scaled_pixmap()

                filename = os.path.basename(filepath)
                cache_info = self._get_cache_info(files)
                info_text = f"{self.current_index + 1} / {len(files)}  -  {filename}\n{cache_info}"
                self.info_label.setText(info_text)

            # 先読みを開始
            self._start_preloading(files)
            return

        try:
            ext = os.path.splitext(filepath)[1].lower()

            # APNG判定
            if ext == ".png" and self._is_apng(filepath):
                self._show_apng(filepath, files)
            else:
                # 静止画
                pixmap = QtGui.QPixmap(filepath)
                if not pixmap.isNull():
                    self._apng_timer.stop()
                    self._apng_frames = []
                    self._current_pixmap = pixmap
                    self.update_scaled_pixmap()

                    # キャッシュに追加
                    self.cache.put(filepath, pixmap)

                    # 情報表示を更新
                    filename = os.path.basename(filepath)
                    cache_info = self._get_cache_info(files)
                    info_text = f"{self.current_index + 1} / {len(files)}  -  {filename}\n{cache_info}"
                    self.info_label.setText(info_text)
                else:
                    self.info_label.setText("画像を読み込めませんでした")
        except Exception as e:
            self.info_label.setText(f"エラー: {e}")

        # 先読みを開始
        self._start_preloading(files)

    def update_scaled_pixmap(self):
        """画像をスクリーンサイズに合わせて表示"""
        if self._current_pixmap:
            scaled = self._current_pixmap.scaled(
                self.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
            )
            self.image_label.setPixmap(scaled)

    def _is_apng(self, filepath):
        """PNGファイルがAPNGかチェック"""
        # キャッシュをチェック
        if filepath in self._apng_check_cache:
            return self._apng_check_cache[filepath]

        try:
            with Image.open(filepath) as img:
                result = getattr(img, "is_animated", False)
                self._apng_check_cache[filepath] = result
                return result
        except:
            self._apng_check_cache[filepath] = False
            return False

    def _show_apng(self, filepath, files):
        """APNGを読み込んで再生"""
        self._apng_timer.stop()
        self._apng_frames = []
        self._apng_frame_index = 0

        try:
            img = Image.open(filepath)

            # 全フレームを読み込み
            for frame_index in range(getattr(img, "n_frames", 1)):
                img.seek(frame_index)
                frame = img.convert("RGBA")

                # PIL ImageをQPixmapに変換
                data = frame.tobytes("raw", "RGBA")
                qimage = QtGui.QImage(
                    data, frame.width, frame.height, QtGui.QImage.Format_RGBA8888
                )
                pixmap = QtGui.QPixmap.fromImage(qimage)

                # フレーム時間を取得（ミリ秒）
                duration = img.info.get("duration", 100)

                self._apng_frames.append({"pixmap": pixmap, "duration": duration})

            if self._apng_frames:
                self._show_apng_frame(0)

                # キャッシュに追加
                self.cache.put(filepath, self._apng_frames)

                # 情報表示を更新
                filename = os.path.basename(filepath)
                cache_info = self._get_cache_info(files)
                info_text = f"{self.current_index + 1} / {len(files)}  -  {filename} (APNG)\n{cache_info}"
                self.info_label.setText(info_text)

                if len(self._apng_frames) > 1:
                    self._apng_timer.start(self._apng_frames[0]["duration"])
            else:
                self.info_label.setText("APNGを読み込めませんでした")

        except Exception as e:
            self.info_label.setText(f"APNGエラー: {e}")
            self._apng_frames = []

    def _show_apng_frame(self, index):
        """APNGの指定フレームを表示"""
        if 0 <= index < len(self._apng_frames):
            frame_data = self._apng_frames[index]
            self._current_pixmap = frame_data["pixmap"]
            self.update_scaled_pixmap()
            self._apng_frame_index = index

    def _next_apng_frame(self):
        """次のAPNGフレームを表示"""
        if not self._apng_frames:
            self._apng_timer.stop()
            return

        self._apng_frame_index = (self._apng_frame_index + 1) % len(self._apng_frames)
        self._show_apng_frame(self._apng_frame_index)

        # 次のフレームの時間でタイマーを再設定
        if self._apng_frames:
            duration = self._apng_frames[self._apng_frame_index]["duration"]
            self._apng_timer.setInterval(duration)

    def resizeEvent(self, event):
        """ウィンドウサイズ変更時"""
        super().resizeEvent(event)
        # 画像ラベルを画面全体に
        self.image_label.setGeometry(0, 0, self.width(), self.height())
        # 情報ラベルを左下に配置
        info_height = 35
        info_width = min(600, self.width() - 20)
        self.info_label.setGeometry(
            10, self.height() - info_height - 10, info_width, info_height
        )
        # 画像を再スケール
        self.update_scaled_pixmap()

    def keyPressEvent(self, event):
        """キーボード操作"""
        # ショートカットキーのチェック
        if self.parent_window.shortcut_manager.matches_key_event(
            "fullscreen_exit", event
        ):
            self.close()
            event.accept()
            return
        elif self.parent_window.shortcut_manager.matches_key_event(
            "reveal_in_finder", event
        ):
            self.parent_window.reveal_in_finder()
            event.accept()
            return

        # グループ先頭移動（↑↓）
        if event.key() == QtCore.Qt.Key_Down:
            self.move_to_next_left_group()
            event.accept()
            return
        elif event.key() == QtCore.Qt.Key_Up:
            self.move_to_prev_left_group()
            event.accept()
            return

        # グループ中間移動
        if self.parent_window.shortcut_manager.matches_key_event(
            "next_middle_group", event
        ):
            self.move_to_next_middle_group()
            event.accept()
            return
        elif self.parent_window.shortcut_manager.matches_key_event(
            "prev_middle_group", event
        ):
            self.move_to_prev_middle_group()
            event.accept()
            return

        # Escapeで閉じる
        if event.key() == QtCore.Qt.Key_Escape:
            self.close()
        # 左右キーでファイル間移動（端に到達したら次の中間グループへ）
        elif event.key() == QtCore.Qt.Key_Right:
            # 次の画像
            self.current_index += 1
            files = self.get_all_files_in_current_group()

            if self.current_index >= len(files):
                # 最後の画像を超えたら次の中間グループへ
                if self.move_to_next_middle_group():
                    # 移動成功（move_to_next_middle_groupで既にcurrent_index=0に設定済み）
                    pass
                else:
                    # 次のグループがない場合は最初に戻る
                    self.current_index = 0
                    self.show_current_image()
                    self.parent_window.right_list.setCurrentRow(self.current_index)
            else:
                self.show_current_image()
                self.parent_window.right_list.setCurrentRow(self.current_index)

        elif event.key() == QtCore.Qt.Key_Left:
            # 前の画像
            self.current_index -= 1

            if self.current_index < 0:
                # 最初の画像より前に行ったら前の中間グループへ
                if self.move_to_prev_middle_group():
                    # 移動成功（move_to_prev_middle_groupで既にcurrent_index=0に設定済み）
                    pass
                else:
                    # 前のグループがない場合は最後に戻る
                    files = self.get_all_files_in_current_group()
                    self.current_index = len(files) - 1
                    self.show_current_image()
                    self.parent_window.right_list.setCurrentRow(self.current_index)
            else:
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
            # フルスクリーン時は最初のファイルを表示
            self.current_index = 0
            self.show_current_image()
            self.parent_window.right_list.setCurrentRow(self.current_index)
            return True
        else:
            # 最後の中間グループ → 次の左グループに移動
            return self.move_to_next_left_group()

    def move_to_prev_middle_group(self):
        """前の中間グループに移動"""
        middle_list = self.parent_window.middle_list
        current_row = middle_list.currentRow()

        if current_row > 0:
            # 前のグループがある
            middle_list.setCurrentRow(current_row - 1)
            # フルスクリーン時は最初のファイルを表示
            self.current_index = 0
            self.show_current_image()
            self.parent_window.right_list.setCurrentRow(self.current_index)
            return True
        else:
            # 最初の中間グループ → 前の左グループに移動
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
            # フルスクリーン時は最初のファイルを表示
            self.current_index = 0
            self.show_current_image()
            self.parent_window.right_list.setCurrentRow(self.current_index)
            return True
        return False

    def move_to_prev_left_group(self):
        """前の左グループに移動"""
        left_list = self.parent_window.left_list
        current_row = left_list.currentRow()

        if current_row > 0:
            # 前のグループがある
            left_list.setCurrentRow(current_row - 1)
            # 中リストの最後を選択（前に戻るので最後から）
            middle_count = self.parent_window.middle_list.count()
            if middle_count > 0:
                self.parent_window.middle_list.setCurrentRow(middle_count - 1)
            # フルスクリーン時は最初のファイルを表示
            self.current_index = 0
            self.show_current_image()
            self.parent_window.right_list.setCurrentRow(self.current_index)
            return True
        return False

    def _start_preloading(self, files):
        """前後の画像を先読み"""
        # 先読み数が0の場合は何もしない
        if self.preload_backward <= 0 and self.preload_forward <= 0:
            return

        # 前方のファイルを先読み（-1, -2, -3, ...）
        for offset in range(-1, -self.preload_backward - 1, -1):
            idx = self.current_index + offset
            if 0 <= idx < len(files):
                filepath = files[idx]
                if not self.cache.get(filepath):
                    # キャッシュにない場合のみ読み込み
                    self.preloader.load_image(filepath)

        # 次方のファイルを先読み（+1, +2, +3, ...）
        for offset in range(1, self.preload_forward + 1):
            idx = self.current_index + offset
            if 0 <= idx < len(files):
                filepath = files[idx]
                if not self.cache.get(filepath):
                    # キャッシュにない場合のみ読み込み
                    self.preloader.load_image(filepath)

    def _on_image_preloaded(self, filepath, data):
        """画像が読み込まれたときのコールバック"""
        if isinstance(data, list):
            # APNGフレーム
            self.cache.put(filepath, data)
        else:
            # 静止画
            self.cache.put(filepath, data)

        # 現在表示中の画像の情報を更新（リアルタイムでキャッシュ状況を表示）
        if self._current_filepath and self._current_files:
            filename = os.path.basename(self._current_filepath)
            cache_info = self._get_cache_info(self._current_files)
            # 現在表示中の画像がAPNGかチェック
            is_apng = isinstance(self.cache.get(self._current_filepath), list)
            apng_suffix = " (APNG)" if is_apng else ""
            info_text = f"{self.current_index + 1} / {len(self._current_files)}  -  {filename}{apng_suffix}\n{cache_info}"
            self.info_label.setText(info_text)

    def _show_cached_apng(self, frames, filepath, files):
        """キャッシュされたAPNGフレームを表示"""
        self._apng_timer.stop()
        self._apng_frames = frames
        self._apng_frame_index = 0

        if self._apng_frames:
            self._show_apng_frame(0)

            filename = os.path.basename(filepath)
            cache_info = self._get_cache_info(files)
            info_text = f"{self.current_index + 1} / {len(files)}  -  {filename} (APNG)\n{cache_info}"
            self.info_label.setText(info_text)

            if len(self._apng_frames) > 1:
                self._apng_timer.start(self._apng_frames[0]["duration"])

    def _get_cache_info(self, files):
        """キャッシュ情報を取得"""
        # 前後でキャッシュされている数を数える
        cached_backward = 0
        cached_forward = 0

        # 前方をチェック
        for offset in range(-1, -self.preload_backward - 1, -1):
            idx = self.current_index + offset
            if 0 <= idx < len(files):
                if self.cache.get(files[idx]):
                    cached_backward += 1

        # 次方をチェック
        for offset in range(1, self.preload_forward + 1):
            idx = self.current_index + offset
            if 0 <= idx < len(files):
                if self.cache.get(files[idx]):
                    cached_forward += 1

        return f"キャッシュ: 前{cached_backward}/{self.preload_backward} 次{cached_forward}/{self.preload_forward}"

    def resizeEvent(self, event):
        """ウィンドウサイズ変更時"""
        super().resizeEvent(event)
        # 画像ラベルをウィンドウ全体に
        self.image_label.setGeometry(self.rect())
        # 情報ラベルを左下に配置
        # 幅は画面の半分か600pxのいずれか小さい方
        label_width = min(600, int(self.width() * 0.5))
        self.info_label.setFixedSize(label_width, 70)
        self.info_label.move(10, self.height() - 80)
        # 画像を再スケール
        if self._current_pixmap:
            self.update_scaled_pixmap()

    def mousePressEvent(self, event):
        """マウスクリックで閉じる"""
        if event.button() == QtCore.Qt.RightButton:
            self.close()

    def closeEvent(self, event):
        """ウィンドウを閉じる時の処理"""
        # プリローダースレッドを停止
        if hasattr(self, 'preloader'):
            self.preloader.stop()
            self.preloader.wait(1000)  # 最大1秒待つ
        # APNGタイマーを停止
        if hasattr(self, '_apng_timer'):
            self._apng_timer.stop()
        event.accept()


class ImagePreviewWidget(QtWidgets.QLabel):
    """画像/動画プレビュー表示ウィジェット"""

    # ダブルクリックシグナル
    doubleClicked = QtCore.Signal()

    def __init__(self, parent_window=None, cache_size=5):
        super().__init__()
        self.parent_window = parent_window
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setMinimumSize(300, 300)
        self.setStyleSheet(
            "QLabel { background-color: #2b2b2b; color: #888; border: 1px solid #444; }"
        )
        self.setText("画像を選択してください\n\nダブルクリックでフルスクリーン表示")
        self.setScaledContents(False)
        self._current_pixmap = None
        self._current_movie = None
        self._current_filepath = None

        # APNG再生用
        self._apng_frames = []
        self._apng_frame_index = 0
        self._apng_timer = QtCore.QTimer(self)
        self._apng_timer.timeout.connect(self._next_apng_frame)

        # 画像キャッシュと先読み
        self.cache = ImageCache(max_size=cache_size)
        self.preloader = ImagePreloader(self)
        self.preloader.imageLoaded.connect(self._on_image_preloaded)
        self.preload_backward = 3  # 前方先読み数
        self.preload_forward = 7  # 次方先読み数
        self._apng_check_cache = {}  # APNG判定結果のキャッシュ

    def set_image(self, filepath):
        """画像/動画/APNG を読み込んで表示"""
        if not filepath or not os.path.exists(filepath):
            self.clear_image()
            return

        self._current_filepath = filepath
        ext = os.path.splitext(filepath)[1].lower()

        # キャッシュをチェック
        cached = self.cache.get(filepath)
        if cached:
            if isinstance(cached, list):
                # APNGフレーム
                self._show_cached_apng(cached)
            else:
                # 静止画
                self._current_pixmap = cached
                self._update_scaled_pixmap()
            # 先読みを開始
            self._start_preloading()
            return

        # GIFアニメーション
        if ext == ".gif":
            self._show_animated_gif(filepath)
        # PNG（APNGの可能性）
        elif ext == ".png":
            if self._is_apng(filepath):
                self._show_apng(filepath)
            else:
                self._show_static_image(filepath)
        else:
            # 静止画
            self._show_static_image(filepath)

        # 先読みを開始
        self._start_preloading()

    def _show_static_image(self, filepath):
        """静止画を表示"""
        self._clear_movie()
        try:
            pixmap = QtGui.QPixmap(filepath)
            if pixmap.isNull():
                self.setText("画像を読み込めませんでした")
                self._current_pixmap = None
            else:
                self._current_pixmap = pixmap
                self._update_scaled_pixmap()
                # キャッシュに追加
                self.cache.put(filepath, pixmap)
        except Exception as e:
            self.setText(f"エラー: {e}")
            self._current_pixmap = None

    def _show_animated_gif(self, filepath):
        """GIFアニメーションを表示"""
        self._clear_movie()
        self._current_pixmap = None
        try:
            self._current_movie = QtGui.QMovie(filepath)
            if self._current_movie.isValid():
                self._current_movie.setScaledSize(self.size())
                self.setMovie(self._current_movie)
                self._current_movie.start()
            else:
                self.setText("GIFを読み込めませんでした")
                self._current_movie = None
        except Exception as e:
            self.setText(f"エラー: {e}")
            self._current_movie = None

    def _clear_movie(self):
        """ムービーをクリア"""
        if self._current_movie:
            self._current_movie.stop()
            self._current_movie = None
            self.setMovie(None)

    def _is_apng(self, filepath):
        """PNGファイルがAPNGかチェック"""
        # キャッシュをチェック
        if filepath in self._apng_check_cache:
            return self._apng_check_cache[filepath]

        try:
            with Image.open(filepath) as img:
                result = getattr(img, "is_animated", False)
                self._apng_check_cache[filepath] = result
                return result
        except:
            self._apng_check_cache[filepath] = False
            return False

    def _show_apng(self, filepath):
        """APNGを読み込んで再生"""
        self._clear_movie()
        self._current_pixmap = None
        self._apng_timer.stop()
        self._apng_frames = []
        self._apng_frame_index = 0

        try:
            img = Image.open(filepath)

            # 全フレームを読み込み
            for frame_index in range(getattr(img, "n_frames", 1)):
                img.seek(frame_index)
                frame = img.convert("RGBA")

                # PIL ImageをQPixmapに変換
                data = frame.tobytes("raw", "RGBA")
                qimage = QtGui.QImage(
                    data, frame.width, frame.height, QtGui.QImage.Format_RGBA8888
                )
                pixmap = QtGui.QPixmap.fromImage(qimage)

                # フレーム時間を取得（ミリ秒）
                duration = img.info.get("duration", 100)

                self._apng_frames.append({"pixmap": pixmap, "duration": duration})

            if self._apng_frames:
                self._show_apng_frame(0)
                if len(self._apng_frames) > 1:
                    self._apng_timer.start(self._apng_frames[0]["duration"])
                # キャッシュに追加
                self.cache.put(filepath, self._apng_frames)
            else:
                self.setText("APNGを読み込めませんでした")

        except Exception as e:
            self.setText(f"APNGエラー: {e}")
            self._apng_frames = []

    def _show_apng_frame(self, index):
        """APNGの指定フレームを表示"""
        if 0 <= index < len(self._apng_frames):
            frame_data = self._apng_frames[index]
            self._current_pixmap = frame_data["pixmap"]
            self._update_scaled_pixmap()
            self._apng_frame_index = index

    def _next_apng_frame(self):
        """次のAPNGフレームを表示"""
        if not self._apng_frames:
            self._apng_timer.stop()
            return

        self._apng_frame_index = (self._apng_frame_index + 1) % len(self._apng_frames)
        self._show_apng_frame(self._apng_frame_index)

        # 次のフレームの時間でタイマーを再設定
        if self._apng_frames:
            duration = self._apng_frames[self._apng_frame_index]["duration"]
            self._apng_timer.setInterval(duration)

    def clear_image(self):
        """画像をクリア"""
        self.setText("画像を選択してください\n\nダブルクリックでフルスクリーン表示")
        self._clear_movie()
        self._apng_timer.stop()
        self._apng_frames = []
        self._current_pixmap = None
        self._current_filepath = None

    def _update_scaled_pixmap(self):
        """ウィンドウサイズに合わせて画像を拡大縮小"""
        if self._current_pixmap:
            scaled = self._current_pixmap.scaled(
                self.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
            )
            self.setPixmap(scaled)

    def resizeEvent(self, event):
        """ウィンドウサイズ変更時に画像を再スケール"""
        super().resizeEvent(event)
        if self._current_movie and self._current_movie.isValid():
            self._current_movie.setScaledSize(self.size())
        else:
            self._update_scaled_pixmap()

    def _start_preloading(self):
        """前後の画像を先読み"""
        if not self.parent_window:
            return

        # 先読み数が0の場合は何もしない
        if self.preload_backward <= 0 and self.preload_forward <= 0:
            return

        adjacent_files = self._get_adjacent_files()
        for filepath in adjacent_files:
            if filepath and not self.cache.get(filepath):
                # キャッシュにない場合のみ読み込み
                self.preloader.load_image(filepath)

    def _get_adjacent_files(self):
        """前後のファイルパスを取得"""
        if not self.parent_window:
            return []

        left_item = self.parent_window.left_list.currentItem()
        middle_item = self.parent_window.middle_list.currentItem()
        current_row = self.parent_window.right_list.currentRow()

        if not (left_item and middle_item) or current_row < 0:
            return []

        left_key = left_item.text()
        middle_key = middle_item.data(QtCore.Qt.UserRole)
        filelist = self.parent_window.group_dict.get(left_key, [])
        middle_groups = self.parent_window.get_middle_groups(filelist)
        files = middle_groups.get(middle_key, [])

        adjacent_files = []
        # 前方のファイルを取得（-1, -2, -3, ...）
        for offset in range(-1, -self.preload_backward - 1, -1):
            idx = current_row + offset
            if 0 <= idx < len(files):
                filepath = os.path.join(self.parent_window.image_folder, files[idx])
                adjacent_files.append(filepath)

        # 次方のファイルを取得（+1, +2, +3, ...）
        for offset in range(1, self.preload_forward + 1):
            idx = current_row + offset
            if 0 <= idx < len(files):
                filepath = os.path.join(self.parent_window.image_folder, files[idx])
                adjacent_files.append(filepath)

        return adjacent_files

    def _on_image_preloaded(self, filepath, data):
        """画像が読み込まれたときのコールバック"""
        if isinstance(data, list):
            # APNGフレーム
            self.cache.put(filepath, data)
        else:
            # 静止画
            self.cache.put(filepath, data)

    def _show_cached_apng(self, frames):
        """キャッシュされたAPNGフレームを表示"""
        self._clear_movie()
        self._current_pixmap = None
        self._apng_timer.stop()
        self._apng_frames = frames
        self._apng_frame_index = 0

        if self._apng_frames:
            self._show_apng_frame(0)
            if len(self._apng_frames) > 1:
                self._apng_timer.start(self._apng_frames[0]["duration"])

    def mouseDoubleClickEvent(self, event):
        """ダブルクリックイベント"""
        if event.button() == QtCore.Qt.LeftButton:
            self.doubleClicked.emit()

    def cleanup(self):
        """クリーンアップ処理"""
        # プリローダースレッドを停止
        if hasattr(self, 'preloader'):
            self.preloader.stop()
            self.preloader.wait(1000)  # 最大1秒待つ
        # APNGタイマーを停止
        if hasattr(self, '_apng_timer'):
            self._apng_timer.stop()
        # ムービーをクリア
        self._clear_movie()

    def __del__(self):
        """デストラクタ"""
        self.cleanup()


class ImageGroupNavigator(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("画像グループナビゲーター")
        self.resize(1200, 700)

        # 設定ファイルのパス（iCloud Drive）
        config_dir = Path(
            "/Users/iru/Library/Mobile Documents/com~apple~CloudDocs/設定用ファイル"
        )
        config_dir.mkdir(parents=True, exist_ok=True)  # フォルダがなければ作成
        self.config_path = config_dir / "image_group_navigator_config.json"

        # 初期化
        self.image_folder = ""
        self.group_dict = {}
        self.group_keys = []
        self.sort_order = "name"  # "name" または "date"
        self.fullscreen_viewer = None
        self.preload_backward = 3  # 前方先読み数（デフォルト）
        self.preload_forward = 7  # 次方先読み数（デフォルト）
        self.cache_size = 5  # キャッシュサイズ（デフォルト）
        self._first_show = True  # 初回表示フラグ

        # ショートカットマネージャー
        self.shortcut_manager = ShortcutManager()

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

        settings_btn = QtWidgets.QPushButton("ショートカット設定...")
        settings_btn.clicked.connect(self.open_shortcut_settings)
        settings_btn.setEnabled(False)
        settings_btn.setToolTip("ショートカットキーは現在ハードコードされています")
        folder_layout.addWidget(settings_btn)

        # 先読み数設定
        folder_layout.addWidget(QtWidgets.QLabel("先読み（前:"))
        self.preload_backward_spinbox = QtWidgets.QSpinBox()
        self.preload_backward_spinbox.setMinimum(0)
        self.preload_backward_spinbox.setMaximum(10)
        self.preload_backward_spinbox.setValue(self.preload_backward)
        self.preload_backward_spinbox.setToolTip("前方向に何枚の画像を先読みするか（0-10枚）")
        self.preload_backward_spinbox.valueChanged.connect(self.on_preload_backward_changed)
        folder_layout.addWidget(self.preload_backward_spinbox)

        folder_layout.addWidget(QtWidgets.QLabel("次:"))
        self.preload_forward_spinbox = QtWidgets.QSpinBox()
        self.preload_forward_spinbox.setMinimum(0)
        self.preload_forward_spinbox.setMaximum(10)
        self.preload_forward_spinbox.setValue(self.preload_forward)
        self.preload_forward_spinbox.setToolTip("次方向に何枚の画像を先読みするか（0-10枚）")
        self.preload_forward_spinbox.valueChanged.connect(self.on_preload_forward_changed)
        folder_layout.addWidget(self.preload_forward_spinbox)
        folder_layout.addWidget(QtWidgets.QLabel("枚）"))

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
        self.left_list = left_widget["list"]
        self.left_up_btn = left_widget["up_btn"]
        self.left_down_btn = left_widget["down_btn"]
        content_layout.addWidget(left_widget["container"], 1)

        # 中リスト（グループ中間）
        middle_widget = self.create_list_widget("グループ中間", with_buttons=True)
        self.middle_list = middle_widget["list"]
        self.middle_up_btn = middle_widget["up_btn"]
        self.middle_down_btn = middle_widget["down_btn"]
        content_layout.addWidget(middle_widget["container"], 1)

        # 右リスト（ファイル名）
        right_widget = self.create_list_widget("ファイル名", with_buttons=True)
        self.right_list = right_widget["list"]
        self.right_up_btn = right_widget["up_btn"]
        self.right_down_btn = right_widget["down_btn"]
        content_layout.addWidget(right_widget["container"], 1)

        # プレビュー
        preview_container = QtWidgets.QWidget()
        preview_layout = QtWidgets.QVBoxLayout(preview_container)
        preview_layout.addWidget(QtWidgets.QLabel("プレビュー"))
        self.preview_widget = ImagePreviewWidget(parent_window=self, cache_size=self.cache_size)
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

        result = {"container": container, "list": list_widget}

        if with_buttons:
            btn_layout = QtWidgets.QHBoxLayout()
            up_btn = QtWidgets.QPushButton("↑")
            down_btn = QtWidgets.QPushButton("↓")
            btn_layout.addWidget(up_btn)
            btn_layout.addWidget(down_btn)
            layout.addLayout(btn_layout)
            result["up_btn"] = up_btn
            result["down_btn"] = down_btn

        return result

    def connect_signals(self):
        """シグナル接続"""
        # リスト選択変更
        self.left_list.itemSelectionChanged.connect(self.on_left_select)
        self.middle_list.itemSelectionChanged.connect(self.on_middle_select)
        self.right_list.itemSelectionChanged.connect(self.on_right_select)

        # ダブルクリック
        self.left_list.itemDoubleClicked.connect(
            lambda: self.open_current_image(self.left_list)
        )
        self.middle_list.itemDoubleClicked.connect(
            lambda: self.open_current_image(self.middle_list)
        )
        self.right_list.itemDoubleClicked.connect(
            lambda: self.open_current_image(self.right_list)
        )

        # Enterキー
        self.left_list.itemActivated.connect(
            lambda: self.open_current_image(self.left_list)
        )
        self.middle_list.itemActivated.connect(
            lambda: self.open_current_image(self.middle_list)
        )
        self.right_list.itemActivated.connect(
            lambda: self.open_current_image(self.right_list)
        )

        # ↑↓ボタン
        self.left_up_btn.clicked.connect(
            lambda: self.move_selection(self.left_list, -1)
        )
        self.left_down_btn.clicked.connect(
            lambda: self.move_selection(self.left_list, 1)
        )
        self.middle_up_btn.clicked.connect(
            lambda: self.move_selection(self.middle_list, -1)
        )
        self.middle_down_btn.clicked.connect(
            lambda: self.move_selection(self.middle_list, 1)
        )
        self.right_up_btn.clicked.connect(
            lambda: self.move_selection(self.right_list, -1)
        )
        self.right_down_btn.clicked.connect(
            lambda: self.move_selection(self.right_list, 1)
        )

    def keyPressEvent(self, event):
        """キーボードショートカット"""
        focused = QtWidgets.QApplication.focusWidget()

        # Enterキー（リストにフォーカスがある場合）
        if isinstance(focused, QtWidgets.QListWidget):
            if (
                event.key() == QtCore.Qt.Key_Return
                or event.key() == QtCore.Qt.Key_Enter
            ):
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
            self, "画像フォルダを選択", self.folder_input.text() or str(Path.home())
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

    def on_preload_backward_changed(self, value):
        """前方先読み数変更時"""
        self.preload_backward = value
        # プレビューウィジェットに反映
        if hasattr(self, 'preview_widget'):
            self.preview_widget.preload_backward = value
        # 設定を保存
        self.save_settings()
        self.statusBar().showMessage(f"前方先読み数を{value}枚に変更しました", 2000)

    def on_preload_forward_changed(self, value):
        """次方先読み数変更時"""
        self.preload_forward = value
        # プレビューウィジェットに反映
        if hasattr(self, 'preview_widget'):
            self.preview_widget.preload_forward = value
        # 設定を保存
        self.save_settings()
        self.statusBar().showMessage(f"次方先読み数を{value}枚に変更しました", 2000)

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
                reverse=True,
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
            QtWidgets.QMessageBox.warning(
                self, "エラー", "フォルダパスを入力してください"
            )
            return

        if not os.path.isdir(folder):
            QtWidgets.QMessageBox.warning(
                self, "エラー", f"フォルダが存在しません:\n{folder}"
            )
            return

        self.image_folder = folder
        self.save_settings()

        try:
            # ファイル一覧取得
            all_files = os.listdir(folder)
            valid_exts = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")
            image_files = [f for f in all_files if f.lower().endswith(valid_exts)]

            if not image_files:
                QtWidgets.QMessageBox.information(
                    self, "情報", "画像ファイルが見つかりませんでした"
                )
                return

            # グループ化
            self.group_dict = {}
            for filename in image_files:
                prefix = filename.split("_")[0]
                self.group_dict.setdefault(prefix, []).append(filename)

            # グループ内は常に番号順にソート
            for key in self.group_dict.keys():
                self.group_dict[key].sort(key=self.natural_key)

            # 中・右リストクリア（refresh_left_listの前に実行）
            self.middle_list.clear()
            self.right_list.clear()
            self.preview_widget.clear_image()

            # 左リスト更新（ソート順に応じて）
            # これにより自動的に最初の項目が選択され、on_left_select()が呼ばれる
            self.refresh_left_list()

            self.statusBar().showMessage(
                f"{len(image_files)}個の画像ファイルを読み込みました"
            )

        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "エラー", f"フォルダのスキャンに失敗しました:\n{e}"
            )

    def showEvent(self, event):
        """ウィンドウ表示時の処理"""
        super().showEvent(event)
        # 初回表示時のみ自動選択を実行
        if self._first_show and self.left_list.count() > 0:
            self._first_show = False
            # イベントループが開始された後に実行
            QtCore.QTimer.singleShot(50, self._auto_select_first_items)

    def _auto_select_first_items(self):
        """最初のグループと画像を自動選択"""
        if self.left_list.count() > 0:
            # setCurrentRowではなくsetCurrentItemを使用
            item = self.left_list.item(0)
            if item:
                self.left_list.setCurrentItem(item)
                self.left_list.scrollToItem(item)
            QtCore.QTimer.singleShot(100, self._auto_select_first_middle)

    def _auto_select_first_middle(self):
        """ミドルリストの最初の項目を自動選択"""
        if self.middle_list.count() > 0:
            item = self.middle_list.item(0)
            if item:
                self.middle_list.setCurrentItem(item)
                self.middle_list.scrollToItem(item)
            QtCore.QTimer.singleShot(100, self._auto_select_first_right)

    def _auto_select_first_right(self):
        """右リストの最初の項目を自動選択"""
        if self.right_list.count() > 0:
            item = self.right_list.item(0)
            if item:
                self.right_list.setCurrentItem(item)
                self.right_list.scrollToItem(item)

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
        # UserRoleから元のキーを取得--++--++
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
            parts = f.split("_", 2)
            display_name = parts[2] if len(parts) > 2 else f
            if "." in display_name:
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
                subprocess.run(["open", filepath], check=True)
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self, "エラー", f"画像を開けませんでした:\n{e}"
                )

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

    def reveal_in_finder(self):
        """現在のファイルをFinderで選択表示"""
        filepath = self.get_current_filepath()
        if not filepath or not os.path.exists(filepath):
            self.statusBar().showMessage("ファイルが選択されていません")
            return

        try:
            # AppleScriptでFinderを開いてファイルを選択
            script = f'tell application "Finder" to reveal POSIX file "{filepath}"'
            subprocess.run(["osascript", "-e", script], check=True)
            # Finderを前面に
            subprocess.run(
                ["osascript", "-e", 'tell application "Finder" to activate'], check=True
            )
            self.statusBar().showMessage(f"Finderで表示: {os.path.basename(filepath)}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "エラー", f"Finderで開けませんでした:\n{e}"
            )

    def move_to_next_middle_group(self):
        """次の中間グループに移動"""
        if self.middle_list.count() == 0:
            return

        current_row = self.middle_list.currentRow()
        if current_row < self.middle_list.count() - 1:
            # 次のグループに移動
            self.middle_list.setCurrentRow(current_row + 1)
        else:
            # 最後のグループ → 左リストの次に移動
            self.move_to_next_left_group()

    def move_to_prev_middle_group(self):
        """前の中間グループに移動"""
        if self.middle_list.count() == 0:
            return

        current_row = self.middle_list.currentRow()
        if current_row > 0:
            # 前のグループに移動
            self.middle_list.setCurrentRow(current_row - 1)
        else:
            # 最初のグループ → 左リストの前に移動
            self.move_to_prev_left_group()

    def move_to_next_left_group(self):
        """次の左グループに移動"""
        if self.left_list.count() == 0:
            return

        current_row = self.left_list.currentRow()
        if current_row < self.left_list.count() - 1:
            # 次のグループに移動
            self.left_list.setCurrentRow(current_row + 1)
            # 中リストの最初を選択
            if self.middle_list.count() > 0:
                self.middle_list.setCurrentRow(0)

    def move_to_prev_left_group(self):
        """前の左グループに移動"""
        if self.left_list.count() == 0:
            return

        current_row = self.left_list.currentRow()
        if current_row > 0:
            # 前のグループに移動
            self.left_list.setCurrentRow(current_row - 1)
            # 中リストの最後を選択
            if self.middle_list.count() > 0:
                self.middle_list.setCurrentRow(self.middle_list.count() - 1)

    @staticmethod
    def natural_key(s):
        """自然順ソート用キー"""

        def try_int(c):
            try:
                return int(c)
            except:
                return c

        return [try_int(c) for c in re.split(r"(\d+)", s)]

    @staticmethod
    def extract_middle_number(name):
        """ファイル名から中間番号を抽出"""
        parts = name.split("_")
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
                with open(self.config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    self.image_folder = config.get("folder", "")
                    if self.image_folder:
                        self.folder_input.setText(self.image_folder)

                    # ソート順を復元
                    self.sort_order = config.get("sort_order", "name")
                    if self.sort_order == "date":
                        self.sort_date_radio.setChecked(True)
                    else:
                        self.sort_name_radio.setChecked(True)

                    # 先読み設定を復元
                    self.preload_backward = config.get("preload_backward", 3)
                    self.preload_forward = config.get("preload_forward", 7)
                    self.cache_size = config.get("cache_size", 5)
                    # UIに反映
                    if hasattr(self, 'preload_backward_spinbox'):
                        self.preload_backward_spinbox.setValue(self.preload_backward)
                    if hasattr(self, 'preload_forward_spinbox'):
                        self.preload_forward_spinbox.setValue(self.preload_forward)
                    # プレビューウィジェットに設定を適用
                    if hasattr(self, 'preview_widget'):
                        self.preview_widget.preload_backward = self.preload_backward
                        self.preview_widget.preload_forward = self.preload_forward

                    # ショートカットキーを復元
                    # self.shortcut_manager.load_from_config(config)
            except Exception as e:
                print(f"設定の読み込みに失敗: {e}")

    def save_settings(self):
        """設定を保存"""
        try:
            config = {
                "folder": self.image_folder,
                "sort_order": self.sort_order,
                "preload_backward": self.preload_backward,
                "preload_forward": self.preload_forward,
                "cache_size": self.cache_size,
            }
            # ショートカットキーを保存
            # self.shortcut_manager.save_to_config(config)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"設定の保存に失敗: {e}")

    def open_shortcut_settings(self):
        """ショートカットキー設定ダイアログを開く"""
        dialog = ShortcutSettingsDialog(self.shortcut_manager, self)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            # 新しいショートカット設定を適用
            new_shortcuts = dialog.get_shortcuts()
            for action, key_seq in new_shortcuts.items():
                self.shortcut_manager.set_key_sequence(action, key_seq)
            # 設定を保存
            self.save_settings()
            self.statusBar().showMessage("ショートカットキーを保存しました")

    def closeEvent(self, event):
        """ウィンドウを閉じる時"""
        # プレビューウィジェットのクリーンアップ
        if hasattr(self, 'preview_widget'):
            self.preview_widget.cleanup()
        self.save_settings()
        event.accept()


def main():
    app = QtWidgets.QApplication(sys.argv)
    window = ImageGroupNavigator()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
