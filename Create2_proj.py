#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Version History
# v1.0: Python2.7 -- 2015//05/27
# v2.0: Update to Python3 -- 2020/04/01
# v2.1: Stiffler (bare) modifications -- 2022/02/02
# v3.0: Stiffler Quality of Life changes
# v3.1: Stiffler Bug Fixes and QoL - 2025/02/18

###########################################################################
# Copyright (c) 2015-2020 iRobot Corporation#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#   Redistributions of source code must retain the above copyright
#   notice, this list of conditions and the following disclaimer.
#
#   Redistributions in binary form must reproduce the above copyright
#   notice, this list of conditions and the following disclaimer in
#   the documentation and/or other materials provided with the
#   distribution.
#
#   Neither the name of iRobot Corporation nor the names
#   of its contributors may be used to endorse or promote products
#   derived from this software without specific prior written
#   permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
###########################################################################

import logging
import struct
import sys
import glob
import time
import tkinter as tk
from tkinter import messagebox, simpledialog
from functools import wraps

# Create Library
import createlib as cl

try:
    import serial
except ImportError:
    messagebox.showerror('Import error', 'Please install pyserial using: pip install pyserial')
    raise

# Constants
TEXTWIDTH = 100
TEXTHEIGHT = 24
VELOCITYCHANGE = 200
ROTATIONCHANGE = 300
DOCK_TIMEOUT = 30  # Timeout for docking in seconds

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# ---------- Helper for Dropdown Connection ----------
class PortSelectDialog(simpledialog.Dialog):
    def __init__(self, parent, title, ports):
        self.ports = ports
        self.selected_port = None
        super().__init__(parent, title)

    def body(self, master):
        tk.Label(master, text="Select a COM port:").pack(padx=10, pady=5)

        self.var = tk.StringVar(master)
        self.var.set(self.ports[0])  # default to first port

        self.dropdown = tk.OptionMenu(master, self.var, *self.ports)
        self.dropdown.pack(padx=10, pady=5)
        return self.dropdown  # initial focus

    def apply(self):
        self.selected_port = self.var.get()

def require_robot(func):
    """Decorator to ensure robot is connected before executing a function."""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if self.robot is None:
            messagebox.showinfo('Error', "Robot Not Connected!")
            return
        return func(self, *args, **kwargs)
    return wrapper

# ---------- Main App ----------
class TetheredDriveApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("iRobot Create 2 Tethered Drive")

        # required variables
        self.robot = None
        self.velocity = 0
        self.rotation = 0
        # TODO: custom variables
        
        # Automatic polling
        self.sensor_poll_timer = None
        self.sensor_polling_active = False

        # GUI Elements
        self._setup_ui()
        self.bind("<KeyPress>", self.handle_keypress)
        self.bind("<KeyRelease>", self.handle_keyrelease)

    def _setup_ui(self):
        """Sets up UI elements like the menu and text output."""
        self.option_add('*tearOff', False)

        menubar = tk.Menu(self)
        self.configure(menu=menubar)

        create_menu = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label="Create", menu=create_menu)
        create_menu.add_command(label="Connect", command=self.on_connect)
        create_menu.add_command(label="Help", command=self.on_help)
        create_menu.add_command(label="Quit", command=self.on_quit)

        # Use a horizontal frame to hold two text widgets
        frame = tk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True)

        # Left panel - Instructions
        self.instruction_text = tk.Text(frame, height=TEXTHEIGHT, width=int(TEXTWIDTH/2), wrap=tk.WORD)
        instruction_scroll = tk.Scrollbar(frame, command=self.instruction_text.yview)
        self.instruction_text.configure(yscrollcommand=instruction_scroll.set)

        # Right panel - Sensor live data
        self.sensor_text = tk.Text(frame, height=TEXTHEIGHT, width=int(TEXTWIDTH/2), wrap=tk.WORD)
        sensor_scroll = tk.Scrollbar(frame, command=self.sensor_text.yview)
        self.sensor_text.configure(yscrollcommand=sensor_scroll.set)

        # Layout
        self.instruction_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        instruction_scroll.pack(side=tk.LEFT, fill=tk.Y)
        self.sensor_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sensor_scroll.pack(side=tk.LEFT, fill=tk.Y)

        # Set up instruction text initially
        self.instruction_text.insert(tk.END, self._help_text())
        self.instruction_text.config(state=tk.DISABLED)  # make read-only


    def _help_text(self):
        """Returns help text for key mappings."""
        supported_keys = {
            "P": "Passive Mode",
            "S": "Safe Mode",
            "F": "Full Mode",
            "C": "Clean",
            "D": "Dock",
            "R": "Reset",
            "B": "Sensor Dump",
            "Space": "Beep",
            "O": "Toggle Sensor Polling",
            "Arrows": "Motion",
            "Escape": "Quick Shutdown",
        }
        return "\n".join([f"{key}: {desc}" for key, desc in supported_keys.items()]) + \
               "\n\nIf nothing happens after you connect, try pressing 'P' and then 'S' to enter safe mode."

    def handle_keypress(self, event):
        """Handles keypress events."""
        key = event.keysym.upper()
        key_mapping = {
            "P": lambda: self.robot.start(),
            "S": lambda: self.robot.safe(),
            "F": lambda: self.robot.full(),
            "C": lambda: self.robot.clean(),
            "R": lambda: self.robot.reset(),
            "SPACE": lambda: self._beep_song(),
            "B": lambda: logging.info(self._format_sensor_data(self.robot.get_sensors())),
            "O": self.toggle_sensor_polling,
            "UP": lambda: self._set_motion(velocity=VELOCITYCHANGE),
            "DOWN": lambda: self._set_motion(velocity=-VELOCITYCHANGE),
            "LEFT": lambda: self._set_motion(rotation=ROTATIONCHANGE),
            "RIGHT": lambda: self._set_motion(rotation=-ROTATIONCHANGE),
            "ESCAPE": self.on_quit
        }
        if key in key_mapping:
            key_mapping[key]()

    def handle_keyrelease(self, event):
        """Handles key release events to stop movement."""
        key = event.keysym.upper()
        if key in {"UP", "DOWN"}:
            self._set_motion(velocity=0)
        elif key in {"LEFT", "RIGHT"}:
            self._set_motion(rotation=0)

    @require_robot
    def _set_motion(self, velocity=None, rotation=None):
        """
        Updates motion values and sends drive command.
        """
        if velocity is not None:
            self.velocity = velocity
        if rotation is not None:
            self.rotation = rotation

        vr = int(self.velocity + (self.rotation / 2))
        vl = int(self.velocity - (self.rotation / 2))
        self.robot.drive_direct(vl, vr)

    def _format_sensor_data(self, sensors):
        """
        Formats sensor data for logging.
        """
        return "\n".join([f"{key}: {value}" for key, value in sensors._asdict().items()])


    def on_connect(self):
        """
        Handles connection to the robot.
        """
        if self.robot:
            messagebox.showinfo('Oops', "You're already connected to the robot!")
            return

        try:
            ports = self._get_serial_ports()

            if not ports:
                messagebox.showerror('No Devices', 'No serial devices found. Please check your connection.')
                return

            if len(ports) == 1:
                port = ports[0]
                logging.info(f"Only one port found: {port}. Connecting automatically.")
            else:
                # Use dropdown
                dialog = PortSelectDialog(self, "Select Port", ports)
                if dialog.selected_port:
                    port = dialog.selected_port
                else:
                    logging.warning('Connection cancelled by user.')
                    return

            self.robot = cl.Create2(port=port, baud=115200)
            messagebox.showinfo('Connected', f"Connected successfully to {port}!")
            logging.info(f"Connected to robot on {port}")

        except Exception as e:
            logging.error(f"Failed to connect: {e}")
            messagebox.showerror('Connection Failed', f"Couldn't connect to {port}")

    def on_help(self):
        """
        Displays help text.
        """
        messagebox.showinfo('Help', self._help_text())

    def on_quit(self):
        """
        Handles quitting the application.
        """
        if messagebox.askyesno('Really?', 'Are you sure you want to quit?'):
            if self.robot:
                del self.robot
            self.destroy()

    def _get_serial_ports(self):
        """
        Lists serial ports
        From http://stackoverflow.com/questions/12090503/listing-available-com-ports-with-python

        :raises EnvironmentError:
            On unsupported or unknown platforms
        :returns:
            A list of available serial ports
        """
        if sys.platform.startswith('win'):
            ports = ['COM' + str(i + 1) for i in range(256)]

        elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
            # this is to exclude your current terminal "/dev/tty"
            ports = glob.glob('/dev/tty[A-Za-z]*')

        elif sys.platform.startswith('darwin'):
            ports = glob.glob('/dev/tty.*')

        else:
            raise EnvironmentError('Unsupported platform')

        result = []
        for port in ports:
            try:
                s = serial.Serial(port)
                s.close()
                result.append(port)
            except (OSError, serial.SerialException):
                pass
        return result


    # ----------------------- Custom functions ------------------------------
    @require_robot
    def _beep_song(self):
        beep_song = [64, 16]
        self.robot.createSong(3, beep_song)
        self.robot.playSong(3)

    @require_robot
    def toggle_sensor_polling(self):
        """
        Toggles automatic sensor polling on/off.
        """
        if self.sensor_polling_active:
            if self.sensor_poll_timer:
                self.sensor_poll_timer.stop()
                self.sensor_poll_timer = None
            self.sensor_polling_active = False
            logging.info("Sensor polling stopped.")
        else:
            from createlib.custom_timer import CustomTimer
            self.sensor_poll_timer = CustomTimer(0.5, self.poll_sensors, False, repeat=True)
            self.sensor_polling_active = True
            logging.info("Sensor polling started.")

    @require_robot
    def poll_sensors(self, show_log=False):
        """
        Called automatically to poll and display sensor data.
        """
        sensors = self.robot.get_sensors()
        sensor_text = self._format_sensor_data(sensors)

        if show_log:
            logging.info(sensor_text)

        current_text = self.sensor_text.get("1.0", tk.END).strip()

        if current_text != sensor_text:
            self.sensor_text.config(state=tk.NORMAL)
            self.sensor_text.delete("1.0", tk.END)
            self.sensor_text.insert(tk.END, sensor_text)
            self.sensor_text.config(state=tk.DISABLED)


# ----------------------- Main Driver ------------------------------
if __name__ == "__main__":
    banner = """
==================================================
   iRobot Create 2 Tethered Drive Interface
==================================================
Press "Connect" from the menu to begin.
Use the keyboard to drive the robot once connected!
Press "O" to toggle live sensor monitoring.
==================================================
    """
    print(banner)
    
    app = TetheredDriveApp()
    app.mainloop()
