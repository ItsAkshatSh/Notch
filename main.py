import sys
import asyncio
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, 
                           QPushButton, QLabel, QSystemTrayIcon, QMenu, QAction)
from PyQt5.QtCore import Qt, QTimer, QPoint, QPropertyAnimation, QRect, QEasingCurve
from PyQt5.QtGui import QIcon, QPixmap, QFont
from datetime import datetime
import winsdk.windows.media.control as media_control
import threading
import queue
import win32gui
import win32con
import os

class AsyncioThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.loop = None
        self.queue = queue.Queue()
        self._is_ready = threading.Event()
        
    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._is_ready.set()
        self.loop.run_forever()

    def stop(self):
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)
            
    def wait_until_ready(self):
        self._is_ready.wait()

    async def run_coro(self, coro):
        return await coro

    def run_coroutine(self, coro):
        self.wait_until_ready()
        if not self.loop or not self.loop.is_running():
            raise RuntimeError("AsyncIO loop is not running")
        future = asyncio.run_coroutine_threadsafe(self.run_coro(coro), self.loop)
        return future.result()

class MediaController:
    def __init__(self, asyncio_thread):
        self.asyncio_thread = asyncio_thread
        self.session_manager = self.asyncio_thread.run_coroutine(
            media_control.GlobalSystemMediaTransportControlsSessionManager.request_async()
        )

    def get_media_info(self):
        try:
            current_session = self.session_manager.get_current_session()
            if current_session:
                info = self.asyncio_thread.run_coroutine(
                    current_session.try_get_media_properties_async()
                )
                return {
                    "title": info.title,
                    "artist": info.artist,
                    "playback_status": current_session.get_playback_info().playback_status,
                    "source": self.get_media_source(current_session)
                }
        except Exception as e:
            print(f"Error getting media info: {e}")
            return None

    def get_media_source(self, session):
        try:
            app_id = session.source_app_user_model_id
            if "spotify" in app_id.lower():
                return "Spotify"
            elif "chrome" in app_id.lower():
                return "Chrome"
            elif "firefox" in app_id.lower():
                return "Firefox"
            else:
                return app_id.split('.')[-1]
        except:
            return "Media"

    def play_pause(self):
        try:
            current_session = self.session_manager.get_current_session()
            if current_session:
                self.asyncio_thread.run_coroutine(
                    current_session.try_toggle_play_pause_async()
                )
        except Exception as e:
            print(f"Error toggling playback: {e}")

    def next_track(self):
        try:
            current_session = self.session_manager.get_current_session()
            if current_session:
                self.asyncio_thread.run_coroutine(
                    current_session.try_skip_next_async()
                )
        except Exception as e:
            print(f"Error skipping track: {e}")

    def previous_track(self):
        try:
            current_session = self.session_manager.get_current_session()
            if current_session:
                self.asyncio_thread.run_coroutine(
                    current_session.try_skip_previous_async()
                )
        except Exception as e:
            print(f"Error going to previous track: {e}")

class NotchBar(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | 
            Qt.WindowStaysOnTopHint | 
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.expanded = False
        
        self.asyncio_thread = AsyncioThread()
        self.asyncio_thread.start()
        self.asyncio_thread.wait_until_ready()
        
        self.media_controller = MediaController(self.asyncio_thread)
        
        self.setup_system_tray()
        
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QHBoxLayout(self.central_widget)
        self.layout.setContentsMargins(5, 2, 5, 2)
        self.layout.setSpacing(4)
        
        self.font = QFont("-apple-system", 10)
        self.setFont(self.font)
        
        self.setStyleSheet("""
            QWidget {
                background-color: rgba(0, 0, 0, 180);
                color: white;
                border-radius: 12px;
            }
            QPushButton {
                border: none;
                padding: 3px;
                border-radius: 3px;
                background-color: transparent;
                min-width: 20px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 30);
            }
            QLabel {
                background-color: transparent;
                padding: 0px 2px;
            }
        """)
        
        self.clock_label = QLabel()
        self.clock_label.setAlignment(Qt.AlignCenter)
        self.update_clock()
        
        self.play_btn = QPushButton("▶")
        self.app_label = QLabel()
        self.app_label.setAlignment(Qt.AlignCenter)
        
        self.layout.addWidget(self.clock_label)
        self.layout.addWidget(self.play_btn)
        self.layout.addWidget(self.app_label)
        
        self.prev_btn = QPushButton("⏮")
        self.next_btn = QPushButton("⏭")
        self.title_label = QLabel()
        
        self.prev_btn.hide()
        self.next_btn.hide()
        self.title_label.hide()
        
        self.layout.addWidget(self.prev_btn)
        self.layout.addWidget(self.next_btn)
        self.layout.addWidget(self.title_label)
        
        self.play_btn.clicked.connect(self.media_controller.play_pause)
        self.prev_btn.clicked.connect(self.media_controller.previous_track)
        self.next_btn.clicked.connect(self.media_controller.next_track)
        
        self.compact_width = 100
        self.expanded_width = 250
        self.height = 25
        
        screen = QApplication.primaryScreen().geometry()
        center_x = (screen.width() - self.compact_width) // 2
        self.setGeometry(
            center_x,
            0,
            self.compact_width,
            self.height
        )
        
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_clock)
        self.clock_timer.start(1000)
        
        self.media_timer = QTimer(self)
        self.media_timer.timeout.connect(self.update_media_info)
        self.media_timer.start(1000)
        
        self.setMouseTracking(True)
        self.central_widget.setMouseTracking(True)
        self.installEventFilter(self)

    def setup_system_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon("icon.png"))
        
        tray_menu = QMenu()
        show_action = QAction("Show/Hide", self)
        quit_action = QAction("Exit", self)
        autostart_action = QAction("Start with Windows", self)
        autostart_action.setCheckable(True)
        autostart_action.setChecked(self.is_autostart_enabled())
        
        show_action.triggered.connect(self.toggle_visibility)
        quit_action.triggered.connect(self.quit_application)
        autostart_action.triggered.connect(self.toggle_autostart)
        
        tray_menu.addAction(show_action)
        tray_menu.addAction(autostart_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def toggle_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()

    def quit_application(self):
        self.asyncio_thread.stop()
        self.asyncio_thread.join()
        QApplication.quit()

    def is_autostart_enabled(self):
        import winreg
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ
            )
            winreg.QueryValueEx(key, "NotchBar")
            winreg.CloseKey(key)
            return True
        except WindowsError:
            return False

    def toggle_autostart(self):
        import winreg
        app_path = os.path.abspath(sys.argv[0])
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                key_path,
                0,
                winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
            )
            
            try:
                winreg.QueryValueEx(key, "NotchBar")
                winreg.DeleteValue(key, "NotchBar")
            except WindowsError:
                winreg.SetValueEx(key, "NotchBar", 0, winreg.REG_SZ, f'"{app_path}"')
                
            winreg.CloseKey(key)
        except WindowsError as e:
            print(f"Error modifying registry: {e}")

    def update_clock(self):
        current_time = datetime.now().strftime("%H:%M")
        self.clock_label.setText(current_time)

    def eventFilter(self, obj, event):
        if obj is self:
            if event.type() == event.Enter:
                self.expand()
            elif event.type() == event.Leave:
                self.collapse()
        return super().eventFilter(obj, event)

    def expand(self):
        if not self.expanded:
            self.expanded = True
            self.prev_btn.show()
            self.next_btn.show()
            self.title_label.show()
            
            animation = QPropertyAnimation(self, b"geometry")
            animation.setDuration(200)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            current_geo = self.geometry()
            new_x = current_geo.x() - (self.expanded_width - self.compact_width) // 2
            animation.setStartValue(current_geo)
            animation.setEndValue(QRect(
                new_x,
                current_geo.y(),
                self.expanded_width,
                self.height
            ))
            animation.start()

    def collapse(self):
        if self.expanded:
            self.expanded = False
            animation = QPropertyAnimation(self, b"geometry")
            animation.setDuration(200)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            current_geo = self.geometry()
            new_x = current_geo.x() + (self.expanded_width - self.compact_width) // 2
            animation.setStartValue(current_geo)
            animation.setEndValue(QRect(
                new_x,
                current_geo.y(),
                self.compact_width,
                self.height
            ))
            animation.finished.connect(lambda: self.hide_expanded_widgets())
            animation.start()

    def hide_expanded_widgets(self):
        self.prev_btn.hide()
        self.next_btn.hide()
        self.title_label.hide()

    def update_media_info(self):
        media_info = self.media_controller.get_media_info()
        if media_info:
            is_playing = (media_info['playback_status'] == 
                        media_control.GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING)
            self.play_btn.setText("⏸" if is_playing else "▶")
            
            source = media_info['source']
            self.app_label.setText(source[:1])
            
            title = media_info['title']
            if len(title) > 30:
                title = title[:27] + "..."
            self.title_label.setText(title)
        else:
            self.play_btn.setText("▶")
            self.app_label.setText("-")
            self.title_label.setText("No media")

    def closeEvent(self, event):
        event.ignore()
        self.hide()

def main():
    app = QApplication(sys.argv)
    
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(('localhost', 47200))
    except socket.error:
        print("Application is already running")
        sys.exit()
    
    notch = NotchBar()
    notch.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()