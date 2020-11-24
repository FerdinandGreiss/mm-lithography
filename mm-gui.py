#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Created on Thu Sep 21 16:48:12 2017

Simple GUI for automated patterning with an inverted microscope
and its controlling by the Micro-Manager (MM) application. An Arduino microcontroller is used
as triggering device for UV illumination together with a physical shutter.

The x and y positions are imported from a text file (see "position-folder" for example) and can be directly
extracted from AutoCAD files using the provided lisp script.

Warning: This script might not run directly, since the MM config file depends on the individual hardware settings.

@author: Ferdinand Greiss
"""

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

import numpy as np
import os
import sys
import time
from threading import Thread

import struct

MM_PATH = os.path.join('C:', os.path.sep, 'Program Files', 'Micro-Manager-1.4')
sys.path.append(MM_PATH)
os.environ['PATH'] = MM_PATH + ';' + os.environ['PATH']

try:
    import MMCorePy
    import serial
except:
    pass

from skimage import img_as_ubyte
from skimage.exposure import rescale_intensity
from skimage.io import imsave
from skimage.feature import peak_local_max

# Config file has to be created within the Micro Manager configuration wizard
MM_CONFIG_FILE = "C:/Program Files/Micro-Manager-1.4/axiovert200m-woReflector.cfg"
ARDUINO_COM_PORT = "COM8"

# Dimensions of the camera (Here, sCMOS with 16-bit resolution)
CAMERA_HEIGHT = 2160
CAMERA_WIDTH = 2560

# Position (in pixel) of the UV illumination spot on the camera
Y_ORIGIN_POSITION = 1149
X_ORIGIN_POSITION = 1106

# Conversions of motor to camera to pixel dimensions
MOTORSTEPS_UM_CONVERSION = 0.8
UM_PIXEL_CONVERSION = 0.1705


class Arduino():
    def __init__(self, port=None):
        if port is None:
            self.serial_port = serial.Serial(ARDUINO_COM_PORT, 57600, timeout=0.1)
        else:
            self.serial_port = serial.Serial(port, 57600, timeout=0.1)

        self.write_cmd(42, 5, 0)

    def write_cmd(self, *args):
        cmd = struct.pack('>B', args[0])
        for arg in args[1:]:
            cmd += struct.pack('>B', arg)
        self.serial_port.write(cmd)
        return self.serial_port.readline()

    def open_shutter(self):
        # Mode digital write = 42, pin number (pin 8 = 0), on
        self.write_cmd(42, 5, 1)

    def close_shutter(self):
        self.write_cmd(42, 5, 0)

    def close(self):
        self.serial_port.close()


class ImageView(QLabel):
    def __init__(self, d=None, status_bar=None, parent=None):
        super(ImageView, self).__init__(parent)

        if d is None:
            self.data = np.random.randint(0, 2 ** 4 - 1, size=(CAMERA_HEIGHT, CAMERA_WIDTH)).astype(np.uint16)
            # self.data[100:200, 100:500] = 2**16-1
            idy, idx = np.indices((CAMERA_HEIGHT, CAMERA_WIDTH))
            id = np.sqrt((idx - Y_ORIGIN_POSITION) ** 2 + (idy - X_ORIGIN_POSITION / 2) ** 2) < 15
            self.data[id] = 2 ** 16 - 1

        self.H, self.W = self.data.shape
        self.numpy_image = self.data.copy()

        self.data = img_as_ubyte(self.data)
        v_min, v_max = np.percentile(self.data, (5, 100))
        self.data = rescale_intensity(self.data, in_range=(self.data.min(), self.data.max()))

        self.scaling_factor = 0.3
        self.window_w = self.W * self.scaling_factor
        self.window_h = self.H * self.scaling_factor

        self.qimage = QPixmap(QImage(self.data, self.W, self.H, QImage.Format_Grayscale8))
        self.setPixmap(self.getScalePixelMap())
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self.painter = QPainter(self.qimage)
        self.pen = QPen(Qt.red)
        self.pen.setWidth(10)
        self.painter.setPen(self.pen)

        self.mouse_position = None
        self.position1 = None
        self.position2 = None
        self.position_list = []

        self.setMouseTracking(1)
        self.mouseMoveEvent = self.hoverFunction
        self.status_bar = None
        self.main_application = None

    def set_image(self, img):
        self.numpy_image = img.copy()
        self.H = img.shape[0]
        self.W = img.shape[1]
        self.window_w = self.W * self.scaling_factor
        self.window_h = self.H * self.scaling_factor

        if self.painter.isActive():
            self.painter.end()

        if self.side_panel_hard.auto_scaling.isChecked():
            v_min, v_max = np.percentile(self.numpy_image, (5, 95))
        else:
            v_min, v_max = self.side_panel_hard.getLimits()

        self.data = rescale_intensity(self.numpy_image, in_range=(v_min, v_max), out_range=np.uint8)
        self.data = img_as_ubyte(self.data)

        self.qimage = QPixmap(QImage(self.data, self.W, self.H, QImage.Format_Grayscale8))
        self.setPixmap(self.getScalePixelMap())
        self.update()

        self.painter.begin(self.qimage)
        self.painter.setPen(self.pen)

    def scaleImage(self, factor):
        self.scaling_factor *= factor
        self.setPixmap(self.getScalePixelMap())
        self.resize(QSize(self.window_w, self.window_h))
        self.update()

    def getWindowSize(self):
        return self.size()

    def getImageSize(self):
        return self.qimage.size()

    def getScaling(self):
        return [x / y for x, y in zip(self.getWindowSize(), self.getImageSize())]

    def getScalePixelMap(self):
        self.window_w = self.W * self.scaling_factor
        self.window_h = self.H * self.scaling_factor
        return self.qimage.scaled(self.window_w, self.window_h, Qt.KeepAspectRatio)

    def hoverFunction(self, event):
        pos = event.pos()
        self.mouse_position = (pos.x() / self.scaling_factor, pos.y() / self.scaling_factor)

        x, y = self.mouse_position
        calib = self.side_panel_hard.getCalibration()
        um_x, um_y = x * calib, y * calib

        if not self.main_application.exposure_active:
            self.status_bar.showMessage(
                'x: {0} ({2:0.2f} um), y: {1} ({3:0.2f} um), value: {4}'.format(int(x), int(y), um_x, um_y,
                                                                                self.numpy_image[int(y), int(x)]),
                2000)


class SidePanel(QDockWidget):
    def __init__(self, name=None, parent=None):
        super(SidePanel, self).__init__(parent)

        if name is None:
            self.setWindowTitle("Daisy-Control")

        self.setMinimumSize(QSize(270, 530))
        self.grid_widget = QWidget(self)
        self.grid_widget.setGeometry(QRect(10, 50, 256, 550))
        self.grid = QGridLayout(self.grid_widget)

        self.create_btn = QPushButton(" Overlay ")
        self.expose_btn = QPushButton(" Expose ")
        self.stop_btn = QPushButton(" Stop ")
        self.load_position_btn = QPushButton(" Load ")

        self.label1 = QLabel("- Push 1 -", self.grid_widget)
        self.label2 = QLabel("- Push 2 -", self.grid_widget)

        self.time_exp_field = QSpinBox(self.grid_widget)
        self.time_exp_field.setRange(0, 1000000)
        self.time_exp_field.setValue(15000)
        time_exp_label = QLabel("Exposure [ms]: ")
        time_exp_label.setBuddy(self.time_exp_field)

        self.scaling_field = QDoubleSpinBox(self.grid_widget)
        self.scaling_field.setRange(0, 2)
        self.scaling_field.setDecimals(4)
        self.scaling_field.setValue(0.9890)
        scaling_field_label = QLabel("Scaling [x]: ")
        scaling_field_label.setBuddy(self.scaling_field)

        # Before x=1114, y=1146
        self.label_oriX = QLabel("Origin-X [pixel]", self.grid_widget)
        self.label_oriY = QLabel("Origin-Y [pixel]", self.grid_widget)
        self.origin_x = QSpinBox(self.grid_widget)
        self.origin_x.setRange(0, CAMERA_WIDTH)
        self.origin_x.setValue(X_ORIGIN_POSITION)
        self.origin_y = QSpinBox(self.grid_widget)
        self.origin_y.setRange(0, CAMERA_HEIGHT)
        self.origin_y.setValue(Y_ORIGIN_POSITION)

        self.grid.addWidget(self.stop_btn, 0, 1, 1, 1)
        self.grid.addWidget(self.expose_btn, 0, 0, 1, 1)
        self.grid.addWidget(time_exp_label, 1, 0)
        self.grid.addWidget(self.time_exp_field, 1, 1)

        pattern_label = QLabel("-- Pattern --", self.grid_widget)
        self.grid.addWidget(pattern_label, 3, 0, 1, 2)
        self.grid.addWidget(self.load_position_btn, 4, 0)
        self.grid.addWidget(self.create_btn, 4, 1)
        self.grid.addWidget(scaling_field_label, 5, 0)
        self.grid.addWidget(self.scaling_field, 5, 1)

        ill_label = QLabel("-- Illumination origin --", self.grid_widget)
        self.grid.addWidget(ill_label, 11, 0, 1, 2)

        self.grid.addWidget(self.label_oriX, 12, 0)
        self.grid.addWidget(self.origin_x, 12, 1)
        self.grid.addWidget(self.label_oriY, 13, 0)
        self.grid.addWidget(self.origin_y, 13, 1)

        self.find_center_btn = QPushButton(" Estimate ")
        self.grid.addWidget(self.find_center_btn, 14, 0)
        self.reset_center_btn = QPushButton(" Reset ")
        self.grid.addWidget(self.reset_center_btn, 14, 1)

        calib_label = QLabel("-- Pattern calibration --", self.grid_widget)
        self.grid.addWidget(calib_label, 15, 0, 1, 2)

        self.grid.addWidget(self.label1, 16, 0)
        self.grid.addWidget(self.label2, 16, 1)

        self.grid.setSizeConstraint(QLayout.SetDefaultConstraint)

        self.setMouseTracking(1)
        self.mouseMoveEvent = self.hoverFunction

    def hoverFunction(self, event):
        self.time_exp_field.clearFocus()
        self.origin_y.clearFocus()
        self.origin_x.clearFocus()


class SidePanelHard(QDockWidget):
    def __init__(self, parent=None):
        super(SidePanelHard, self).__init__(parent)
        self.setupUi(self)
        self.setMouseTracking(1)
        self.mouseMoveEvent = self.hoverFunction

    def setupUi(self, Form):
        Form.setObjectName("Scope-Control")
        Form.resize(278, 278)
        Form.setMinimumSize(QSize(270, 400))
        self.gridLayoutWidget = QWidget(Form)
        self.gridLayoutWidget.setGeometry(QRect(10, 50, 256, 400))
        self.gridLayoutWidget.setObjectName("gridLayoutWidget")
        self.gridLayout = QGridLayout(self.gridLayoutWidget)
        self.gridLayout.setSizeConstraint(QLayout.SetDefaultConstraint)
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.gridLayout.setObjectName("gridLayout")

        self.label = QLabel(self.gridLayoutWidget)
        self.label.setText("-- XY control --")
        self.gridLayout.addWidget(self.label, 3, 1, 1, 1)

        self.step_size_box = QSpinBox(self.gridLayoutWidget)
        self.step_size_box.setRange(0, 100000)
        self.step_size_box.setValue(1000)
        self.gridLayout.addWidget(self.step_size_box, 5, 1, 1, 1)

        self.expose_box = QSpinBox(self.gridLayoutWidget)
        self.expose_box.setRange(0, 10000)
        self.expose_box.setValue(50)
        self.gridLayout.addWidget(self.expose_box, 1, 1)

        self.auto_scaling = QCheckBox(self.gridLayoutWidget)
        self.auto_scaling.setChecked(True)
        self.auto_scaling.setText("auto-scaling")
        self.gridLayout.addWidget(self.auto_scaling, 1, 2)

        self.expose_label = QLabel(self.gridLayoutWidget)
        self.expose_label.setText("Exposure [ms]: ")
        self.gridLayout.addWidget(self.expose_label, 1, 0, 1, 1)

        self.max_limit = QSpinBox(self.gridLayoutWidget)
        self.min_limit = QSpinBox(self.gridLayoutWidget)
        self.max_limit.setValue(0)
        self.min_limit.setValue(0)
        self.max_limit.setRange(0, 2 ** 16 - 1)
        self.min_limit.setRange(0, 2 ** 16 - 1)
        limits_label = QLabel("Limits (min/max): ")
        limits_label.setBuddy(self.min_limit)

        self.gridLayout.addWidget(self.max_limit, 2, 2)
        self.gridLayout.addWidget(self.min_limit, 2, 1)
        self.gridLayout.addWidget(limits_label, 2, 0)

        self.down_btn = QPushButton(self.gridLayoutWidget)
        self.down_btn.setText("DOWN")
        self.gridLayout.addWidget(self.down_btn, 6, 1, 1, 1)

        self.right_btn = QPushButton(self.gridLayoutWidget)
        self.right_btn.setText("RIGHT")
        self.gridLayout.addWidget(self.right_btn, 5, 2, 1, 1)

        self.up_btn = QPushButton(self.gridLayoutWidget)
        self.up_btn.setText("UP")
        self.gridLayout.addWidget(self.up_btn, 4, 1, 1, 1)

        self.left_btn = QPushButton(self.gridLayoutWidget)
        self.left_btn.setText("LEFT")
        self.gridLayout.addWidget(self.left_btn, 5, 0, 1, 1)

        self.label = QLabel(self.gridLayoutWidget)
        self.label.setText("-- Calibration --")
        self.gridLayout.addWidget(self.label, 7, 1, 1, 1)

        self.um_label = QLabel(self.gridLayoutWidget)
        self.um_label.setText("[um/pixel]: ")
        self.gridLayout.addWidget(self.um_label, 8, 0, 1, 1)

        self.steps_label = QLabel(self.gridLayoutWidget)
        self.steps_label.setText("[steps/um]: ")
        self.gridLayout.addWidget(self.steps_label, 9, 0, 1, 1)

        # Olympus 60x/1.2NA:
        # um_pixel = 0.1127; steps_um = 0.800
        self.um_pixel = QDoubleSpinBox(self.gridLayoutWidget)
        self.um_pixel.setRange(0, 10)
        self.um_pixel.setDecimals(4)
        self.um_pixel.setValue(UM_PIXEL_CONVERSION)
        self.gridLayout.addWidget(self.um_pixel, 8, 1, 1, 1)

        self.steps_um = QDoubleSpinBox(self.gridLayoutWidget)
        self.steps_um.setRange(0, 10)
        self.steps_um.setDecimals(4)
        self.steps_um.setValue(MOTORSTEPS_UM_CONVERSION)
        self.gridLayout.addWidget(self.steps_um, 9, 1, 1, 1)

        self.label = QLabel(self.gridLayoutWidget)
        self.label.setText("-- Z control --")
        self.gridLayout.addWidget(self.label, 10, 1, 1, 1)

        self.z_up_btn = QPushButton(self.gridLayoutWidget)
        self.z_up_btn.setText("UP")
        self.gridLayout.addWidget(self.z_up_btn, 11, 0, 1, 1)

        self.z_down_btn = QPushButton(self.gridLayoutWidget)
        self.z_down_btn.setText("DOWN")
        self.gridLayout.addWidget(self.z_down_btn, 11, 2, 1, 1)

        self.z_box = QSpinBox(self.gridLayoutWidget)
        self.z_box.setRange(0, 10000)
        self.z_box.setValue(0)
        self.gridLayout.addWidget(self.z_box, 11, 1, 1, 1)

        self.per_label = QLabel("-- Peripherals --", self.gridLayoutWidget)
        self.gridLayout.addWidget(self.per_label, 12, 1, 1, 1)

        self.shutter_box = QCheckBox(" Shutter", self.gridLayoutWidget)
        self.shutter_box.setChecked(False)
        self.gridLayout.addWidget(self.shutter_box, 13, 1, 1, 2)

        self.acquire_btn = QPushButton(self.gridLayoutWidget)
        self.acquire_btn.setText("Acquire!")
        self.gridLayout.addWidget(self.acquire_btn, 0, 0, 1, 3)
        self.gridLayoutWidget.raise_()
        self.acquire_btn.raise_()

        self.retranslateUi(Form)
        QMetaObject.connectSlotsByName(Form)

    def retranslateUi(self, Form):
        _translate = QCoreApplication.translate
        Form.setWindowTitle(_translate("Form", "FoScope-Control"))

    def getCalibration(self):
        return self.um_pixel.value()

    def getLimits(self):
        limits = (self.min_limit.value(), self.max_limit.value())
        if limits[0] == limits[1]:
            return min(limits), max(limits) + 1
        return min(limits), max(limits)

    def hoverFunction(self, event):
        self.um_pixel.clearFocus()
        self.step_size_box.clearFocus()
        self.expose_box.clearFocus()
        self.step_size_box.clearFocus()
        self.steps_um.clearFocus()
        self.z_box.clearFocus()


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super(MainWindow, self).__init__(parent)

        self.application_running = True
        self.acquire_images = False
        self.camera_thread = Thread(target=self.acquire_fcn)
        self.camera_thread.daemon = True
        self.camera_thread.start()

        self.exposure_active = False
        self.stop_exposure = False
        self.exposure_list = []

        # self.form_widget = QWidget()
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.side_panel = SidePanel()
        self.side_panel.create_btn.clicked.connect(self.create_fcn)
        self.side_panel.expose_btn.clicked.connect(self.expose_fcn)
        self.side_panel.load_position_btn.clicked.connect(self.load_position_fcn)
        self.side_panel.stop_btn.clicked.connect(self.stop_exposure_fcn)
        self.side_panel.find_center_btn.clicked.connect(self.find_center)
        self.side_panel.reset_center_btn.clicked.connect(self.reset_center)

        self.side_panel_hard = SidePanelHard()

        self.image_view_widget = QWidget(parent=self)
        self.image_view = ImageView(parent=self.image_view_widget)
        self.image_view.main_application = self
        self.image_view.status_bar = self.status_bar
        self.image_view.side_panel_hard = self.side_panel_hard
        self.setCentralWidget(self.image_view_widget)

        self.addDockWidget(Qt.RightDockWidgetArea, self.side_panel)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.side_panel_hard)
        self.setMouseTracking(1)

        self.setWindowTitle("DAISY")
        self.resize(1000, 700)
        self.last_file_path = QDir.currentPath()
        self.hardware_detected = False

        try:
            self.mmc = MMCorePy.CMMCore()
            self.mmc.loadSystemConfiguration(MM_CONFIG_FILE)
            print(self.mmc.getLoadedDevices())
            self.mmc.setExposure(50.)
            self.hardware_detected = True
        except Exception as e:
            print(e)
            self.hardware_detected = False
            self.status_bar.showMessage("No hardware detected...", 5000)

        self.side_panel_hard.down_btn.clicked.connect(self.move_down)
        self.side_panel_hard.up_btn.clicked.connect(self.move_up)
        self.side_panel_hard.right_btn.clicked.connect(self.move_right)
        self.side_panel_hard.left_btn.clicked.connect(self.move_left)
        self.side_panel_hard.acquire_btn.clicked.connect(self.acquire)
        self.side_panel_hard.z_up_btn.clicked.connect(self.move_z_up)
        self.side_panel_hard.z_down_btn.clicked.connect(self.move_z_down)
        self.side_panel_hard.shutter_box.clicked.connect(self.shutter)

        # Hardware stuff
        self.abs_x = 0
        self.abs_y = 0

        if self.hardware_detected:
            self.mmc.unloadDevice(ARDUINO_COM_PORT)
            # self.mmc.unloadDevice("Focus")
            # self.mmc.unloadDevice("ZeissScope")
            # self.mmc.unloadDevice("ZeissReflectorTurret")
            # self.mmc.unloadDevice("ZeissBasePortSlider")
            self.mmc.unloadDevice("ZeissObjectives")
            print(self.mmc.getLoadedDevices())
            self.arduino = Arduino()
            self.arduino.close_shutter()
            self.side_panel_hard.shutter_box.setChecked(True)

        self.initial_origin_x = self.side_panel.origin_x.value()
        self.initial_origin_y = self.side_panel.origin_y.value()

        self.createActions()
        self.createMenus()

    def createActions(self):
        self.openAct = QAction("&Open...", self, shortcut="Ctrl+O", triggered=self.open)
        self.exitAct = QAction("E&xit", self, shortcut="Ctrl+Q", triggered=self.close)
        self.saveAct = QAction("Save Image...", self, shortcut="Ctrl+S", triggered=self.saveImage)
        self.zoomInAct = QAction("Zoom &In (25%)", self, shortcut="Ctrl++", enabled=True, triggered=self.zoomIn)
        self.zoomOutAct = QAction("Zoom &Out (25%)", self, shortcut="Ctrl+-", enabled=True, triggered=self.zoomOut)

    def createMenus(self):
        self.fileMenu = QMenu("&File", self)
        self.fileMenu.addAction(self.openAct)
        self.fileMenu.addAction(self.saveAct)
        self.fileMenu.addSeparator()
        self.fileMenu.addAction(self.exitAct)

        self.viewMenu = QMenu("&View", self)
        self.viewMenu.addAction(self.zoomInAct)
        self.viewMenu.addAction(self.zoomOutAct)

        self.menuBar().addMenu(self.fileMenu)
        self.menuBar().addMenu(self.viewMenu)

    def find_center(self):
        image = self.image_view.numpy_image.copy()

        try:
            blob_list = peak_local_max(image, num_peaks=1, threshold_rel=0.5)
            cy, cx = sorted(blob_list, key=lambda u: u[-1])[-1]
        except IndexError:
            self.status_bar.showMessage("No spot detected...", 5000)
            return

        self.side_panel.origin_x.setValue(cx)
        self.side_panel.origin_y.setValue(cy)

        self.image_view.painter.drawEllipse(cx - 20,
                                            cy - 20,
                                            40, 40)

        self.image_view.setPixmap(self.image_view.getScalePixelMap())
        self.image_view.show()

    def reset_center(self):
        self.side_panel.origin_x.setValue(self.initial_origin_x)
        self.side_panel.origin_y.setValue(self.initial_origin_y)

    def saveImage(self):
        image = self.image_view.numpy_image.copy()
        fileName, _ = QFileDialog.getSaveFileName(self, "Save Image",
                                                  self.last_file_path, "Images (*.tif)")
        self.last_file_path = QFileInfo(fileName).path()

        if fileName:
            imsave(fileName, image)

    def open(self):
        fileName, _ = QFileDialog.getOpenFileName(self, "Open File",
                                                  QDir.currentPath(), "Config Files (*.cfg)")
        if fileName:
            try:
                self.mmc.loadSystemConfiguration(fileName)
            except:
                QMessageBox.information(self, "Image Viewer",
                                        "Cannot load %s." % fileName)

    def shutter(self):
        if not self.hardware_detected:
            return

        state = self.side_panel_hard.shutter_box.checkState()
        if state:
            self.arduino.close_shutter()
        else:
            self.arduino.open_shutter()

    def closeEvent(self, event):
        print("Closing application...")
        self.application_running = False

        if self.hardware_detected:
            self.mmc.unloadAllDevices()
            self.arduino.close()

    def zoomIn(self):
        self.image_view.scaleImage(1.25)

    def zoomOut(self):
        self.image_view.scaleImage(0.8)

    def get_position(self):
        if not self.hardware_detected:
            return (0, 0)
        x = self.mmc.getXPosition()
        y = self.mmc.getYPosition()
        return x, y

    def move_z_up(self):
        step = self.side_panel_hard.step_size_box.value()
        if not self.hardware_detected:
            return
        step = self.side_panel_hard.z_box.value()
        self.mmc.setRelativePosition(step)

    def move_z_down(self):
        step = self.side_panel_hard.step_size_box.value()
        if not self.hardware_detected:
            return
        step = self.side_panel_hard.z_box.value()
        self.mmc.setRelativePosition(-step)

    def move_left(self):
        step = self.side_panel_hard.step_size_box.value()
        if not self.hardware_detected:
            return
        step *= self.side_panel_hard.steps_um.value()
        self.mmc.setRelativeXYPosition(step, 0)

    def move_right(self):
        step = self.side_panel_hard.step_size_box.value()
        if not self.hardware_detected:
            return
        step *= self.side_panel_hard.steps_um.value()
        self.mmc.setRelativeXYPosition(-step, 0)

    def move_up(self):
        step = self.side_panel_hard.step_size_box.value()
        if not self.hardware_detected:
            return
        step *= self.side_panel_hard.steps_um.value()
        self.mmc.setRelativeXYPosition(0, -step)

    def move_down(self):
        step = self.side_panel_hard.step_size_box.value()
        if not self.hardware_detected:
            return
        step *= self.side_panel_hard.steps_um.value()
        self.mmc.setRelativeXYPosition(0, +step)

    def acquire(self):
        self.acquire_images = ~self.acquire_images
        if self.acquire_images:
            self.side_panel_hard.acquire_btn.setText("Stop!")
        else:
            self.side_panel_hard.acquire_btn.setText("Acquire!")

    def acquire_fcn(self):
        while True:
            if self.acquire_images:
                if not self.hardware_detected:
                    img = np.random.randint(0, 2 ** 16 - 1, size=(CAMERA_HEIGHT, CAMERA_WIDTH)).astype(np.uint16)
                    self.image_view.set_image(img)
                else:
                    exp_time = self.side_panel_hard.expose_box.value()
                    self.mmc.setExposure(float(exp_time))

                    self.mmc.snapImage()
                    img = self.mmc.getImage()
                    self.image_view.set_image(img)
            else:
                time.sleep(0.1)

            if not self.application_running:
                break

    def load_position_fcn(self):
        name = QFileDialog.getOpenFileName(self, 'Open File')[0]
        # print(name)
        x, y = np.genfromtxt(name)[1:, :-1].T
        self.exposure_list = list(zip(x, y))
        self.status_bar.showMessage("{0} position(s) loaded.".format(len(self.exposure_list)), 2000)

    def create_fcn(self):
        # Uncomment to remove former marker points, but also alignments marks
        # self.image_view.set_image(self.image_view.numpy_image)

        if self.image_view.position1 is None or self.image_view.position2 is None:
            self.status_bar.showMessage("Positions not defined...", 2000)
            return

        if len(self.exposure_list) == 0:
            self.status_bar.showMessage("Exposure list not loaded...", 2000)
            return

        x1, y1 = self.image_view.position1
        x2, y2 = self.image_view.position2

        motorxy = self.get_position()
        steps_um = self.side_panel_hard.steps_um.value()
        alpha = np.arctan(float(y2 - y1) / float(x2 - x1 + 1e-10))
        scaling = self.side_panel.scaling_field.value()

        matrix = np.array(((np.cos(alpha), -np.sin(alpha)),
                           (np.sin(alpha), np.cos(alpha))))

        # units should be steps
        self.image_view.position_list = []
        for x_, y_ in self.exposure_list:
            new_pos = tuple((x1, y1) + matrix.dot((-x_ * scaling * steps_um, -y_ * steps_um * scaling)))

            self.image_view.position_list.append(new_pos)
            px, py = self.set_step_to_pixel_position(new_pos[0], new_pos[1], motor=motorxy)
            self.image_view.painter.drawEllipse(px - 12, py - 12, 24, 24)

        self.image_view.setPixmap(self.image_view.getScalePixelMap())
        self.image_view.show()

    def set_pixel_to_step_position(self, px, py, motor=None):
        pattern_x = self.side_panel.origin_x.value()
        pattern_y = self.side_panel.origin_y.value()

        um_pixel = self.side_panel_hard.getCalibration()
        steps_um = self.side_panel_hard.steps_um.value()

        if motor is None:
            current_x, current_y = self.get_position()
        else:
            current_x, current_y = motor

        sx = current_x - (px - pattern_x) * um_pixel * steps_um
        sy = current_y + (py - pattern_y) * um_pixel * steps_um

        return sx, sy

    def set_step_to_pixel_position(self, sx, sy, motor=None):
        pattern_x = self.side_panel.origin_x.value()
        pattern_y = self.side_panel.origin_y.value()

        um_pixel = self.side_panel_hard.getCalibration()
        steps_um = self.side_panel_hard.steps_um.value()

        if motor is None:
            current_x, current_y = self.get_position()
        else:
            current_x, current_y = motor

        px = - (sx - current_x) / steps_um / um_pixel + pattern_x
        py = + (sy - current_y) / steps_um / um_pixel + pattern_y

        return px, py

    def move_abs(self, position, scale=False):
        if not self.hardware_detected:
            return

        if scale:
            um_pixel = self.side_panel_hard.getCalibration()
            x = position[0] * um_pixel
            y = position[1] * um_pixel
        else:
            x, y = position

        self.mmc.setXYPosition(x, y)
        self.mmc.waitForDevice("XYStage")

    def stop_exposure_fcn(self):
        self.stop_exposure = True

    def expose_fcn(self):
        if self.exposure_active:
            self.status_bar.showMessage('Already exposing!', 2000)
            return
        if len(self.image_view.position_list) == 0:
            self.status_bar.showMessage('Define positions first!', 2000)
            return
        self.exposure_active = True
        self._expose()

    def _expose(self):

        if self.hardware_detected:
            self.arduino.close_shutter()
            num = float(len(self.image_view.position_list))
            for idx, (x_, y_) in enumerate(self.image_view.position_list):

                QCoreApplication.processEvents()

                if self.stop_exposure:
                    break

                self.move_abs((x_, y_))

                exp_time = self.side_panel.time_exp_field.value()
                self.status_bar.showMessage(
                    'Exposing => x: {0:0.0f} y: {1:0.0f} ({2:0.0f}%)'.format(x_, y_, (idx + 1) / num * 100.))

                self.arduino.open_shutter()
                time.sleep(exp_time / 1000.)
                self.arduino.close_shutter()

                time.sleep(0.1)

        else:
            num = float(len(self.image_view.position_list))
            for idx, (x_, y_) in enumerate(self.image_view.position_list):
                exp_time = self.side_panel.time_exp_field.value()

                QCoreApplication.processEvents()

                if self.stop_exposure:
                    break

                self.status_bar.showMessage(
                    'Exposing => x: {0:0.0f} y: {1:0.0f} ({2:0.0f}%)'.format(x_, y_, (idx + 1) / num * 100.)
                )
                time.sleep(exp_time / 1000.)

        self.status_bar.showMessage('Exposure done!', 2000)
        self.exposure_active = False
        self.stop_exposure = False

    def keyPressEvent(self, event):

        if event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_1:
                sx, sy = self.set_pixel_to_step_position(*self.image_view.mouse_position)
                self.image_view.position1 = (sx, sy)
                self.image_view.painter.drawRect(self.image_view.mouse_position[0] - 25,
                                                 self.image_view.mouse_position[1] - 25,
                                                 50,
                                                 50)
                self.image_view.setPixmap(self.image_view.getScalePixelMap())
                self.image_view.update()

                self.side_panel.label1.setText('Position-1\nx: %d, y: %d' % self.image_view.position1)

            elif event.key() == Qt.Key_2:
                sx, sy = self.set_pixel_to_step_position(*self.image_view.mouse_position)
                self.image_view.position2 = (sx, sy)
                self.image_view.painter.drawRect(self.image_view.mouse_position[0] - 25,
                                                 self.image_view.mouse_position[1] - 25,
                                                 50,
                                                 50)
                self.image_view.setPixmap(self.image_view.getScalePixelMap())
                self.image_view.update()

                self.side_panel.label2.setText('Position-2\nx: %d, y: %d' % self.image_view.position2)


if __name__ == '__main__':
    app = QApplication([])
    foo = MainWindow()
    foo.show()
    sys.exit(app.exec_())