import cv2
import mediapipe as mp
import numpy as np
import pyautogui
import time
import math
import ctypes
import threading
import win32gui
import win32con

# ---------------- HELPERS ----------------
def dist(a,b):
    return math.hypot(a[0]-b[0], a[1]-b[1])

# Media keys
VK_PLAY = 0xB3
VK_NEXT = 0xB0
VK_PREV = 0xB1
user32 = ctypes.windll.user32

def media(vk):
    user32.keybd_event(vk,0,0,0)
    time.sleep(0.03)
    user32.keybd_event(vk,0,2,0)

# Always-on-top mini window
def keep_top(window):
    while True:
        hwnd = win32gui.FindWindow(None, window)
        if hwnd:
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST,
                                  10, 10, 360, 260,
                                  win32con.SWP_SHOWWINDOW)
        time.sleep(0.3)

# ---------------- MEDIAPIPE ---------------
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    min_detection_confidence=0.6,
    min_tracking_confidence=0.6
)

mp_draw = mp.solutions.drawing_utils

# ---------------- PARAMETERS --------------
screen_w, screen_h = pyautogui.size()
smooth_x = None
smooth_y = None
SMOOTH = 0.2
SCROLL_COOLDOWN = 0.25
CLICK_COOLDOWN = 0.6
SWIPE_COOLDOWN = 1.0

last_scroll = 0
last_click = 0
last_play = 0
last_swipe = 0

history = []  # store x positions for swipe detection

# -------------- MAIN ----------------------
def main():
    global smooth_x, smooth_y, last_scroll, last_click, last_play, last_swipe, history

    cap = cv2.VideoCapture(0)
    win = "GestureMiniWindow"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, 360,260)
    cv2.moveWindow(win,10,10)

    threading.Thread(target=keep_top, args=(win,), daemon=True).start()

    print("Gesture controller running. ESC to exit.")

    while True:
        ok, frame = cap.read()
        if not ok: break
        frame = cv2.flip(frame,1)
        h,w,_ = frame.shape

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = hands.process(rgb)
        now = time.time()
        gesture = ""

        if res.multi_hand_landmarks:
            lm = res.multi_hand_landmarks[0]
            mp_draw.draw_landmarks(frame,lm, mp_hands.HAND_CONNECTIONS)
            pts = [(p.x,p.y) for p in lm.landmark]

            wrist = pts[0]
            thumb = pts[4]
            index = pts[8]
            middle = pts[12]
            ring = pts[16]
            pinky = pts[20]

            # --------- SWIPE tracking ---------
            history.append(index[0])
            if len(history) > 5:
                history.pop(0)

            # ----- Detect swipe -----
            if len(history) == 5:
                movement = history[-1] - history[0]

                # SWIPE RIGHT → NEXT SONG
                if movement > 0.18 and now - last_swipe > SWIPE_COOLDOWN:
                    media(VK_NEXT)
                    gesture = "next_song"
                    last_swipe = now
                    history.clear()

                # SWIPE LEFT → PREVIOUS SONG
                elif movement < -0.18 and now - last_swipe > SWIPE_COOLDOWN:
                    media(VK_PREV)
                    gesture = "prev_song"
                    last_swipe = now
                    history.clear()

            # ------------ PINCH = CLICK -------------
            if dist(thumb, index) < 0.05:
                if now - last_click > CLICK_COOLDOWN:
                    pyautogui.click()
                    gesture = "click"
                    last_click = now

            # ------------ POINT = CURSOR -------------
            elif dist(index, wrist) > 0.15 and dist(middle, wrist) < 0.12:
                cx = int(index[0] * screen_w)
                cy = int(index[1] * screen_h)

                if smooth_x is None:
                    smooth_x, smooth_y = cx, cy
                else:
                    smooth_x = int(smooth_x*(1-SMOOTH) + cx*SMOOTH)
                    smooth_y = int(smooth_y*(1-SMOOTH) + cy*SMOOTH)

                pyautogui.moveTo(smooth_x, smooth_y, duration=0.01)
                gesture = "cursor"

            # ------------ INDEX UP = SCROLL UP -------------
            elif index[1] < middle[1] - 0.05:
                if now - last_scroll > SCROLL_COOLDOWN:
                    pyautogui.scroll(300)
                    gesture = "scroll_up"
                    last_scroll = now

            # ------------ INDEX DOWN = SCROLL DOWN -------------
            elif index[1] > middle[1] + 0.05:
                if now - last_scroll > SCROLL_COOLDOWN:
                    pyautogui.scroll(-300)
                    gesture = "scroll_down"
                    last_scroll = now

            # ------------ V SIGN = PLAY -------------
            elif dist(index, middle) > 0.12:
                if now - last_play > 1:
                    media(VK_PLAY)
                    gesture = "play"
                    last_play = now

            # ------------ OPEN PALM = PAUSE -------------
            elif all(dist(f,wrist) > 0.15 for f in [thumb,index,middle,ring,pinky]):
                if now - last_play > 1:
                    media(VK_PLAY)
                    gesture = "pause"
                    last_play = now

        cv2.putText(frame, gesture, (8,30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,255), 2)

        cv2.imshow(win, frame)
        if cv2.waitKey(1) & 0xFF == 27:
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__=="__main__":
    main()
