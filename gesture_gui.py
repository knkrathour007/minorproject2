# gesture_gui.py
# Frameless draggable mini GUI + MediaPipe gesture controller (corrected)
# Requirements:
#   pip install opencv-python mediapipe pillow pyautogui pywin32
#
# Run:
#   python gesture_gui.py

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import cv2
import mediapipe as mp
import threading
import time
import math
import pyautogui
import ctypes
import win32gui
import win32con
import collections
import sys

# ----------------- Helpers & OS control -----------------
user32 = ctypes.windll.user32
VK_PLAY = 0xB3
VK_NEXT = 0xB0
VK_PREV = 0xB1

def media(key):
    user32.keybd_event(key, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(key, 0, 2, 0)

def dist(a, b):
    return math.hypot(a[0]-b[0], a[1]-b[1])

# ----------------- MediaPipe setup (use keywords) -----------------
mp_hands = mp.solutions.hands
mp_draw = mp.solutions.drawing_utils
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    min_detection_confidence=0.6,
    min_tracking_confidence=0.6
)

# ----------------- Gesture parameters -----------------
screen_w, screen_h = pyautogui.size()
SMOOTH = 0.22
CLICK_COOLDOWN = 0.6
SCROLL_COOLDOWN = 0.25
SWIPE_COOLDOWN = 1.0

# ----------------- App class -----------------
class GestureApp:
    def __init__(self, root):
        self.root = root
        root.title("GestureMini")
        # Remove window decorations (frameless)
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.geometry("360x260+10+10")  # width x height + x + y

        # Make window draggable
        self.offset_x = 0
        self.offset_y = 0
        root.bind("<Button-1>", self.start_move)
        root.bind("<B1-Motion>", self.do_move)

        # Frame for UI (use tk.Frame so bg option works)
        self.frame = tk.Frame(root, bg="#111")
        self.frame.pack(fill="both", expand=True)

        # Canvas/Label for video
        self.video_label = tk.Label(self.frame, bg="#000")
        self.video_label.place(x=8, y=8, width=320, height=180)

        # gesture label
        self.gesture_var = tk.StringVar(value="Idle")
        self.gesture_label = tk.Label(self.frame, textvariable=self.gesture_var,
                                      bg="#111", fg="#0ff", font=("Segoe UI", 10, "bold"))
        self.gesture_label.place(x=8, y=192, width=320, height=26)

        # Buttons (ttk is fine for buttons)
        self.btn_start = ttk.Button(self.frame, text="Start", command=self.start)
        self.btn_start.place(x=8, y=222, width=80, height=28)

        self.btn_stop = ttk.Button(self.frame, text="Stop", command=self.stop, state="disabled")
        self.btn_stop.place(x=98, y=222, width=80, height=28)

        self.btn_pin = ttk.Button(self.frame, text="Pin", command=self.toggle_topmost)
        self.btn_pin.place(x=188, y=222, width=60, height=28)

        self.btn_quit = ttk.Button(self.frame, text="Quit", command=self.quit_app)
        self.btn_quit.place(x=254, y=222, width=74, height=28)

        # internal state
        self._running = False
        self._capture_thread = None
        self.cap = None
        self.smooth_x = None
        self.smooth_y = None
        self.last_click = 0
        self.last_scroll = 0
        self.last_play = 0
        self.last_swipe = 0
        self.history = collections.deque(maxlen=6)

        # keep a reference for ImageTk to avoid GC
        self._last_imgtk = None

    # dragging handlers
    def start_move(self, event):
        self.offset_x = event.x
        self.offset_y = event.y

    def do_move(self, event):
        x = self.root.winfo_x() + event.x - self.offset_x
        y = self.root.winfo_y() + event.y - self.offset_y
        self.root.geometry(f"+{x}+{y}")

    def toggle_topmost(self):
        cur = self.root.attributes("-topmost")
        self.root.attributes("-topmost", not cur)

    def start(self):
        if self._running:
            return
        # open camera
        # try a couple of camera backends for reliability
        self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            self.gesture_var.set("Camera not found")
            return

        self._running = True
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

    def stop(self):
        self._running = False
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        # capture loop will clean up the camera

    def quit_app(self):
        self._running = False
        time.sleep(0.05)
        try:
            if self.cap and self.cap.isOpened():
                self.cap.release()
        except Exception:
            pass
        try:
            hands.close()
        except Exception:
            pass
        self.root.destroy()
        sys.exit(0)

    def _capture_loop(self):
        # run until stopped
        while self._running and self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.02)
                continue
            try:
                frame = cv2.flip(frame, 1)
                h, w, _ = frame.shape
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                res = hands.process(rgb)
                now = time.time()
                gesture_name = "Idle"

                if res.multi_hand_landmarks:
                    lm = res.multi_hand_landmarks[0]
                    mp_draw.draw_landmarks(frame, lm, mp_hands.HAND_CONNECTIONS)
                    pts = [(p.x, p.y) for p in lm.landmark]

                    wrist = pts[0]
                    thumb = pts[4]
                    index = pts[8]
                    middle = pts[12]
                    ring = pts[16]
                    pinky = pts[20]
                    tips = [thumb, index, middle, ring, pinky]

                    # swipe history
                    self.history.append(index[0])

                    # Swipe detection
                    if len(self.history) >= 5:
                        movement = self.history[-1] - self.history[0]
                        if movement > 0.18 and now - self.last_swipe > SWIPE_COOLDOWN:
                            media(VK_NEXT)
                            gesture_name = "Next track"
                            self.last_swipe = now
                            self.history.clear()
                        elif movement < -0.18 and now - self.last_swipe > SWIPE_COOLDOWN:
                            media(VK_PREV)
                            gesture_name = "Previous track"
                            self.last_swipe = now
                            self.history.clear()

                    # PINCH -> CLICK
                    if dist(thumb, index) < 0.05:
                        if now - self.last_click > CLICK_COOLDOWN:
                            pyautogui.click()
                            gesture_name = "Click"
                            self.last_click = now

                    # POINT -> CURSOR
                    elif dist(index, wrist) > 0.15 and dist(middle, wrist) < 0.12:
                        cx = int(index[0] * screen_w)
                        cy = int(index[1] * screen_h)
                        if self.smooth_x is None:
                            self.smooth_x, self.smooth_y = cx, cy
                        else:
                            self.smooth_x = int(self.smooth_x * (1-SMOOTH) + cx * SMOOTH)
                            self.smooth_y = int(self.smooth_y * (1-SMOOTH) + cy * SMOOTH)
                        try:
                            pyautogui.moveTo(self.smooth_x, self.smooth_y, duration=0.01)
                        except Exception:
                            pass
                        gesture_name = "Cursor"

                    # INDEX up -> scroll up
                    elif index[1] < middle[1] - 0.05:
                        if now - self.last_scroll > SCROLL_COOLDOWN:
                            pyautogui.scroll(300)
                            gesture_name = "Scroll Up"
                            self.last_scroll = now

                    # INDEX down -> scroll down
                    elif index[1] > middle[1] + 0.05:
                        if now - self.last_scroll > SCROLL_COOLDOWN:
                            pyautogui.scroll(-300)
                            gesture_name = "Scroll Down"
                            self.last_scroll = now

                    # V sign -> play
                    elif dist(index, middle) > 0.12:
                        if now - self.last_play > 1:
                            media(VK_PLAY)
                            gesture_name = "Play"
                            self.last_play = now

                    # Open palm -> pause (all fingers extended)
                    elif all(dist(f, wrist) > 0.15 for f in tips):
                        if now - self.last_play > 1:
                            media(VK_PLAY)
                            gesture_name = "Pause"
                            self.last_play = now

                # update gesture label
                self.gesture_var.set(gesture_name)

                # convert frame to ImageTk and show
                img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(img)
                img = img.resize((320, 180))
                imgtk = ImageTk.PhotoImage(image=img)
                # saving reference to avoid GC
                self._last_imgtk = imgtk
                self.video_label.configure(image=imgtk)

            except Exception as ex:
                # don't crash capture loop on unexpected exceptions
                print("Capture loop error:", ex)
                time.sleep(0.02)
                continue

            # small sleep to reduce CPU usage
            time.sleep(0.008)

        # cleanup when loop ends
        try:
            if self.cap and self.cap.isOpened():
                self.cap.release()
        except Exception:
            pass

# ----------------- Main -----------------
def main():
    root = tk.Tk()
    app = GestureApp(root)
    # ensure window shows on top of all on start
    root.lift()
    root.focus_force()
    root.mainloop()

if __name__ == "__main__":
    main()
000