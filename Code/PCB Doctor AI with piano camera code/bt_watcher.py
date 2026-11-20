import time
import sys
import subprocess
import webbrowser
import tkinter as tk
from tkinter import messagebox
import serial.tools.list_ports

def get_bt_ports():
    ports = set()
    for p in serial.tools.list_ports.comports():
        desc = (p.description or "").lower()
        hwid = (p.hwid or "").lower()
        if "bluetooth" in desc or "bthenum" in hwid or "pcb_doctor" in desc:
            ports.add(p.device)
    return ports

def ask_start(port_name):
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    ans = messagebox.askyesno(
        "PCB Doctor AI",
        f"Bluetooth Camera detected on {port_name}.\n\nWould you like to start the diagnostic process?"
    )
    root.destroy()
    return ans

def launch_app(port_name):
    subprocess.Popen([sys.executable, "pcb_doctor_app.py", port_name])
    time.sleep(2.5)
    webbrowser.open("http://127.0.0.1:8000")

def main():
    known_ports = get_bt_ports()
    if known_ports:
        first_port = sorted(known_ports)[0]
        if ask_start(first_port):
            launch_app(first_port)
            return

    while True:
        current_ports = get_bt_ports()
        new_ports = current_ports - known_ports
        if new_ports:
            target = sorted(new_ports)[0]
            if ask_start(target):
                launch_app(target)
                break
        known_ports = current_ports
        time.sleep(2)

if __name__ == "__main__":
    main()
