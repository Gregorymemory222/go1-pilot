"""Go1 Pilot – okienko do sterowania Unitree Go1 z laptopa."""
import queue
import tkinter as tk
from tkinter import colorchooser, messagebox, ttk

from go1_client import DEFAULT_HOST, Go1Client

POSTURE = [
    ("Wstań", "standUp"),
    ("Połóż się", "standDown"),
    ("Podnieś po upadku", "recoverStand"),
    ("Stój (poza)", "stand"),
    ("Chód", "walk"),
    ("Bieg", "run"),
    ("Wspinaczka", "climb"),
]
TRICKS = [
    ("Taniec 1", "dance1"),
    ("Taniec 2", "dance2"),
    ("Podaj łapę", "straightHand1"),
]
# klawisz -> (oś, kierunek); osie: 0 lewo/prawo, 1 obrót, 2 głowa, 3 przód/tył
KEYS = {
    "w": (3, +1), "s": (3, -1),
    "a": (0, -1), "d": (0, +1),
    "q": (1, -1), "e": (1, +1),
    "r": (2, +1), "f": (2, -1),
}
HELP = (
    "W / S – przód / tył\n"
    "A / D – bokiem w lewo / prawo\n"
    "Q / E – obrót w lewo / prawo\n"
    "R / F – głowa w górę / dół (w trybie „Stój”)\n"
    "Spacja – zatrzymaj ruch"
)


class App:
    def __init__(self, root):
        self.root = root
        self.client = None
        self.pressed = set()
        self.events = queue.Queue()

        root.title("Go1 Pilot")
        root.resizable(False, False)
        pad = {"padx": 6, "pady": 4}

        top = ttk.Frame(root)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Adres psa:").pack(side="left")
        self.host = tk.StringVar(value=DEFAULT_HOST)
        self.host_entry = ttk.Entry(top, textvariable=self.host, width=16)
        self.host_entry.pack(side="left", padx=4)
        self.connect_btn = ttk.Button(top, text="Połącz", command=self.toggle_connection)
        self.connect_btn.pack(side="left")
        self.status = tk.StringVar(value="Niepołączono")
        ttk.Label(top, textvariable=self.status).pack(side="left", padx=8)

        body = ttk.Frame(root)
        body.pack(fill="both", **pad)
        self._button_column(body, "Postawa i tryby", POSTURE).grid(row=0, column=0, sticky="n", **pad)
        self._button_column(body, "Sztuczki", TRICKS).grid(row=0, column=1, sticky="n", **pad)

        move = ttk.LabelFrame(body, text="Ruch (klawiatura)")
        move.grid(row=0, column=2, sticky="n", **pad)
        ttk.Label(move, text=HELP, justify="left").pack(anchor="w", **pad)
        ttk.Label(move, text="Prędkość:").pack(anchor="w", padx=6)
        self.speed = tk.DoubleVar(value=0.4)
        ttk.Scale(move, from_=0.1, to=1.0, variable=self.speed,
                  command=lambda _: self.update_stick()).pack(fill="x", padx=6)
        self.motion = tk.StringVar(value="stoi")
        ttk.Label(move, textvariable=self.motion, font=("Segoe UI", 10, "bold")).pack(anchor="w", **pad)

        bottom = ttk.Frame(root)
        bottom.pack(fill="x", **pad)
        ttk.Button(bottom, text="Kolor LED…", command=self.pick_led).pack(side="left")
        tk.Button(bottom, text="ZWIOTCZ SILNIKI", bg="#c62828", fg="white",
                  command=self.damp).pack(side="right")

        root.bind_all("<KeyPress>", self.on_key_press)
        root.bind_all("<KeyRelease>", self.on_key_release)
        root.bind("<FocusOut>", lambda _: self.stop_motion())
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_events()

    def _button_column(self, parent, title, items):
        frame = ttk.LabelFrame(parent, text=title)
        for label, mode in items:
            ttk.Button(frame, text=label, width=20,
                       command=lambda m=mode: self.send_mode(m)).pack(padx=6, pady=2)
        return frame

    # --- połączenie ---
    def toggle_connection(self):
        if self.client:
            self.client.disconnect()
            self.client = None
            self.connect_btn.config(text="Połącz")
            self.status.set("Niepołączono")
            return
        self.client = Go1Client(self.host.get().strip(), on_status=self.events.put)
        self.client.connect()
        self.connect_btn.config(text="Rozłącz")
        self.root.focus_set()

    def poll_events(self):
        while not self.events.empty():
            self.status.set(self.events.get())
        self.root.after(100, self.poll_events)

    def ready(self):
        if self.client and self.client.connected:
            return True
        self.status.set("Najpierw połącz się z psem")
        return False

    # --- komendy ---
    def send_mode(self, mode):
        if self.ready():
            self.stop_motion()
            self.client.send_mode(mode)
            self.status.set(f"Wysłano: {mode}")

    def damp(self):
        if self.ready() and messagebox.askyesno(
                "Zwiotczenie", "Silniki puszczą i pies opadnie na ziemię. Kontynuować?"):
            self.send_mode("damping")

    def pick_led(self):
        if not self.ready():
            return
        rgb, _ = colorchooser.askcolor(title="Kolor LED")
        if rgb:
            self.client.set_led(*(int(c) for c in rgb))

    # --- ruch z klawiatury ---
    def on_key_press(self, event):
        if event.widget is self.host_entry:
            return
        key = event.keysym.lower()
        if key == "space":
            self.stop_motion()
        elif key in KEYS:
            self.pressed.add(key)
            self.update_stick()

    def on_key_release(self, event):
        key = event.keysym.lower()
        if key in self.pressed:
            self.pressed.discard(key)
            self.update_stick()

    def stop_motion(self):
        self.pressed.clear()
        self.update_stick()

    def update_stick(self):
        axes = [0.0, 0.0, 0.0, 0.0]
        for key in self.pressed:
            axis, sign = KEYS[key]
            axes[axis] += sign * self.speed.get()
        if self.client:
            self.client.set_stick(*axes)
        self.motion.set(" + ".join(sorted(k.upper() for k in self.pressed)) or "stoi")

    def close(self):
        if self.client:
            self.client.disconnect()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
