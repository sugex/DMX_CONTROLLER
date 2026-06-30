import sys
import time
import json
import os
import serial
import serial.tools.list_ports
from PyQt5.QtCore import Qt, QTimer, QMutex, QPoint
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QComboBox, QMessageBox, QScrollArea
)

DARK_STYLE = """
    QWidget { background-color: #121212; color: #e0e0e0; font-family: 'Segoe UI'; }
    QSlider::groove:vertical { background: #333; width: 8px; border-radius: 4px; }
    QSlider::handle:vertical { background: #007acc; height: 24px; border-radius: 12px; margin: 0 -8px; }
    QPushButton { background-color: #2c2c2c; border: 1px solid #444; padding: 10px; border-radius: 4px; font-weight: bold; }
    QPushButton:hover { background-color: #3d3d3d; }
    QPushButton:pressed { background-color: #007acc; }
    #BtnClose { background-color: #8b0000; color: white; border: none; }
    #BtnClose:hover { background-color: #ff0000; }
    #BtnFull { background-color: #444; color: white; border: none; }
    #BtnFull:hover { background-color: #555; }
    QLabel { font-weight: bold; color: #bbb; }
"""

CONFIG_FILE = "dmx_config.json"

class DMXController(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.resize(1000, 600)
        self.setStyleSheet(DARK_STYLE)
        
        self.dragPos = QPoint()
        self.ser = None
        self.mutex = QMutex()
        self.settings = self.load_settings()
        
        main_layout = QVBoxLayout()
        
        # --- HEADER ---
        header_layout = QHBoxLayout()
        self.lbl_title = QLabel("SGX DMX CONTROLLER")
        self.lbl_title.setStyleSheet("font-size: 24px; font-weight: bold; color: #007acc;")
        
        # Tombol Full Screen
        self.btn_full = QPushButton("□")
        self.btn_full.setObjectName("BtnFull")
        self.btn_full.setFixedSize(40, 40)
        self.btn_full.clicked.connect(self.toggle_fullscreen)
        
        # Tombol Close
        self.btn_close = QPushButton("X")
        self.btn_close.setObjectName("BtnClose")
        self.btn_close.setFixedSize(40, 40)
        self.btn_close.clicked.connect(self.close)
        
        header_layout.addWidget(self.lbl_title)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_full)
        header_layout.addWidget(self.btn_close)
        main_layout.addLayout(header_layout)

        # --- MIXER CHANNELS ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        mixer_layout = QHBoxLayout(scroll_content)
        
        self.sliders = []
        saved_sliders = self.settings.get("sliders", [0]*18)
        
        for i in range(18):
            ch_layout = QVBoxLayout()
            lbl_ch = QLabel(f"CH {i+1}"); lbl_ch.setAlignment(Qt.AlignCenter)
            slider = QSlider(Qt.Vertical)
            slider.setRange(0, 255)
            slider.setValue(saved_sliders[i])
            slider.setMinimumHeight(300)
            val_lbl = QLabel(str(saved_sliders[i])); val_lbl.setAlignment(Qt.AlignCenter)
            slider.valueChanged.connect(lambda v, l=val_lbl: l.setText(str(v)))
            ch_layout.addWidget(lbl_ch); ch_layout.addWidget(slider, alignment=Qt.AlignCenter); ch_layout.addWidget(val_lbl)
            mixer_layout.addLayout(ch_layout); self.sliders.append(slider)
            
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)

        # --- CONTROLS ---
        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("START DMX")
        self.btn_stop = QPushButton("STOP & BLACKOUT")
        self.btn_start.setStyleSheet("background-color: #28a745; color: white;")
        self.btn_stop.setStyleSheet("background-color: #dc3545; color: white;")
        btn_layout.addWidget(self.btn_start); btn_layout.addWidget(self.btn_stop)
        
        bottom_layout = QHBoxLayout()
        self.com = QComboBox()
        self.btn_refresh = QPushButton("REFRESH"); self.btn_connect = QPushButton("CONNECT")
        bottom_layout.addWidget(QLabel("COM PORT:")); bottom_layout.addWidget(self.com)
        bottom_layout.addWidget(self.btn_refresh); bottom_layout.addWidget(self.btn_connect)
        
        main_layout.addLayout(btn_layout)
        main_layout.addLayout(bottom_layout)
        self.setLayout(main_layout)

        # --- LOGIC ---
        self.timer = QTimer()
        self.timer.timeout.connect(self.send_dmx)
        self.btn_refresh.clicked.connect(self.refresh_ports)
        self.btn_connect.clicked.connect(self.connect_port)
        self.btn_start.clicked.connect(self.start_send)
        self.btn_stop.clicked.connect(self.stop_send)
        
        self.refresh_ports()
        self.auto_connect()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragPos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self.dragPos)
            event.accept()

    # --- FUNGSI LAINNYA TETAP SAMA ---
    def load_settings(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f: return json.load(f)
            except: pass
        return {"port": "", "sliders": [0]*18}

    def save_settings(self):
        data = {"port": self.com.currentText(), "sliders": [s.value() for s in self.sliders]}
        with open(CONFIG_FILE, 'w') as f: json.dump(data, f)

    def auto_connect(self):
        saved_port = self.settings.get("port", "")
        index = self.com.findText(saved_port)
        if index != -1:
            self.com.setCurrentIndex(index)
            self.connect_port()

    def refresh_ports(self):
        self.com.clear()
        self.com.addItems([p.device for p in serial.tools.list_ports.comports()])

    def connect_port(self):
        try:
            if self.ser and self.ser.is_open: self.ser.close()
            self.ser = serial.Serial(self.com.currentText(), baudrate=250000, stopbits=2)
            self.save_settings()
        except Exception as e: QMessageBox.critical(self, "Error", str(e))

    def start_send(self):
        self.timer.start(33)

    def stop_send(self):
        self.timer.stop()
        self.save_settings()
        self.send_blackout()

    def send_dmx(self):
        if not self.ser or not self.ser.is_open: return
        self.mutex.lock()
        try:
            data = bytearray(513)
            for i in range(18): data[i+1] = self.sliders[i].value()
            self.ser.break_condition = True
            time.sleep(0.0001)
            self.ser.break_condition = False
            time.sleep(0.00002)
            self.ser.write(data)
        finally: self.mutex.unlock()

    def closeEvent(self, event):
        self.send_blackout()
        self.save_settings()
        self.timer.stop()
        if self.ser and self.ser.is_open: self.ser.close()
        event.accept()
        
    def send_blackout(self):
        if not self.ser or not self.ser.is_open: return
        self.ser.reset_output_buffer()
        blackout_data = bytearray(513)
        for _ in range(3):
            self.ser.break_condition = True
            time.sleep(0.0001)
            self.ser.break_condition = False
            time.sleep(0.00002)
            self.ser.write(blackout_data)
        self.ser.flush()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DMXController()
    window.show()
    sys.exit(app.exec_())