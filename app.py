"""EasySlice - eenvoudige slicer voor Windows (Tkinter + Sun Valley thema)."""
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import sv_ttk
import slicer as S

FONT = ("Segoe UI", 10)
FONT_B = ("Segoe UI Semibold", 10)
KINDS = [("outer", "Buitenwand", "#e4572e"), ("inner", "Binnenwand", "#f2a541"),
         ("solid", "Boven/onder", "#2a9d8f"), ("infill", "Infill", "#4c78c9"),
         ("support", "Support", "#9b5de5"), ("skirt", "Skirt / brim", "#8d99ae")]
COLORS = {k: c for k, _, c in KINDS}
FILETYPES = [("3D-modellen", "*.stl *.obj *.ply *.off *.3mf *.glb *.gltf *.dae"), ("Alle bestanden", "*.*")]


def res(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def fmt(v):
    return v if isinstance(v, str) else f"{v:g}"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        sv_ttk.set_theme("light")
        self.title("EasySlice")
        self.geometry("1200x780")
        self.minsize(980, 640)
        try:
            self.iconbitmap(default=res("icon.ico"))
        except tk.TclError:
            pass
        self.mesh = self.layers = self.gcode = None
        self.name = ""
        self.vars = {}
        self._lock = False

        side = ttk.Frame(self, padding=(16, 14, 8, 14))
        side.pack(side="left", fill="y")
        head = ttk.Frame(side)
        head.pack(fill="x", pady=(0, 12))
        try:
            self.logo = tk.PhotoImage(file=res("logo.png"))
            ttk.Label(head, image=self.logo).pack(side="left", padx=(0, 10))
        except tk.TclError:
            pass
        box = ttk.Frame(head)
        box.pack(side="left")
        ttk.Label(box, text="EasySlice", font=("Segoe UI Semibold", 18)).pack(anchor="w")
        ttk.Label(box, text="Snel en simpel slicen", foreground="#777").pack(anchor="w")

        ttk.Button(side, text="Model openen…", command=self.open).pack(fill="x")
        card = ttk.LabelFrame(side, text="Model", padding=10)
        card.pack(fill="x", pady=10)
        self.info = ttk.Label(card, text="Nog geen model geladen", justify="left", wraplength=320)
        self.info.pack(anchor="w")
        self.warn = ttk.Label(card, text="", foreground="#c0392b", justify="left", wraplength=320)
        self.warn.pack(anchor="w")

        nb = ttk.Notebook(side)
        nb.pack(fill="both", expand=True)
        tabs = {}
        for n in ("Model", "Kwaliteit", "Supports", "Printer"):
            f = ttk.Frame(nb, padding=12)
            f.columnconfigure(0, weight=1)
            nb.add(f, text=n)
            tabs[n] = f

        t = tabs["Model"]
        self.heading(t, "Schaal")
        self.field(t, "sx", "X", "%")
        self.field(t, "sy", "Y", "%")
        self.field(t, "sz", "Z", "%")
        self.uniform = tk.BooleanVar(value=True)
        ttk.Checkbutton(t, text="Gelijkmatig schalen", variable=self.uniform,
                        style="Switch.TCheckbutton").grid(row=t.grid_size()[1], column=0, columnspan=3, sticky="w", pady=6)
        self.buttons(t, [("Pas op bouwplaat", self.fit), ("100%", lambda: self.set_scale(100))])
        self.heading(t, "Rotatie")
        self.field(t, "rot_z", "Om Z-as", "°")
        self.buttons(t, [("+90°", self.rotate)])

        t = tabs["Kwaliteit"]
        self.heading(t, "Voorinstelling")
        self.preset = ttk.Combobox(t, values=list(S.PRESETS), state="readonly")
        self.preset.set("Normaal (0.20 mm)")
        self.preset.grid(row=t.grid_size()[1], column=0, columnspan=3, sticky="ew", pady=3)
        self.preset.bind("<<ComboboxSelected>>", self.apply_preset)
        self.heading(t, "Lagen")
        self.field(t, "layer", "Laaghoogte", "mm")
        self.field(t, "first", "Eerste laag", "mm")
        self.heading(t, "Sterkte")
        self.field(t, "walls", "Wanden", "")
        self.field(t, "top", "Toplagen", "")
        self.field(t, "bottom", "Bodemlagen", "")
        self.field(t, "infill", "Infill", "%")
        self.heading(t, "Snelheid")
        self.field(t, "speed", "Printen", "mm/s")
        self.field(t, "outer", "Buitenwand", "mm/s")
        self.field(t, "first_speed", "Eerste laag", "mm/s")
        self.field(t, "travel", "Verplaatsen", "mm/s")
        self.field(t, "flow", "Flow", "%")

        t = tabs["Supports"]
        self.heading(t, "Supports")
        self.field(t, "support", "Modus", choices=S.SUPPORT_MODES)
        self.field(t, "support_angle", "Overhanghoek", "°")
        self.field(t, "support_spacing", "Tussenruimte", "mm")
        self.field(t, "support_gap", "Afstand tot model", "mm")
        self.heading(t, "Hechting")
        self.field(t, "adhesion", "Type", choices=S.ADHESION)
        self.field(t, "brim", "Brimbreedte", "mm")

        t = tabs["Printer"]
        self.heading(t, "Bouwplaat")
        self.field(t, "bed_x", "Breedte X", "mm")
        self.field(t, "bed_y", "Diepte Y", "mm")
        self.field(t, "bed_z", "Hoogte Z", "mm")
        self.heading(t, "Extruder")
        self.field(t, "nozzle", "Nozzle", "mm")
        self.field(t, "fil", "Filament", "mm")
        self.field(t, "hotend", "Nozzle temp", "°C")
        self.field(t, "bed_temp", "Bed temp", "°C")
        self.field(t, "fan", "Ventilator", "%")
        self.field(t, "retract", "Retractie", "mm")
        self.field(t, "retract_speed", "Retractiesnelheid", "mm/s")

        for k in ("sx", "sy", "sz", "rot_z", "bed_x", "bed_y", "bed_z"):
            self.vars[k].trace_add("write", self.on_change)

        right = ttk.Frame(self, padding=(8, 14, 16, 14))
        right.pack(side="right", fill="both", expand=True)
        self.cv = tk.Canvas(right, bg="#f3f4f6", highlightthickness=1, highlightbackground="#dcdfe4")
        self.cv.pack(fill="both", expand=True)
        self.cv.bind("<Configure>", lambda e: self.draw())

        srow = ttk.Frame(right)
        srow.pack(fill="x", pady=(10, 0))
        self.layer_lbl = ttk.Label(srow, text="Laag", font=FONT_B, width=22)
        self.layer_lbl.pack(side="left")
        self.slider = ttk.Scale(srow, from_=1, to=1, command=self.on_slider)
        self.slider.pack(side="left", fill="x", expand=True)

        row = ttk.Frame(right)
        row.pack(fill="x", pady=(12, 0))
        self.btn_slice = ttk.Button(row, text="Slicen", style="Accent.TButton", command=self.run_slice, width=14)
        self.btn_slice.pack(side="left")
        self.btn_save = ttk.Button(row, text="G-code opslaan…", command=self.save, state="disabled")
        self.btn_save.pack(side="left", padx=8)
        self.pb = ttk.Progressbar(row, length=200)
        self.pb.pack(side="right")
        self.status = ttk.Label(right, text="Open een model om te beginnen.", foreground="#555")
        self.status.pack(fill="x", pady=(8, 0))

        self.bind("<Control-o>", lambda e: self.open())
        self.bind("<Control-s>", lambda e: self.save())

    # ---------- opbouw ----------
    def heading(self, parent, text):
        r = parent.grid_size()[1]
        ttk.Label(parent, text=text, font=FONT_B).grid(row=r, column=0, columnspan=3, sticky="w", pady=(12 if r else 0, 2))

    def field(self, parent, key, label, unit="", choices=None):
        r = parent.grid_size()[1]
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=3)
        v = tk.StringVar(value=fmt(S.DEFAULTS[key]))
        self.vars[key] = v
        if choices:
            ttk.Combobox(parent, textvariable=v, values=choices, state="readonly",
                         width=22).grid(row=r, column=1, columnspan=2, sticky="e", pady=3)
        else:
            ttk.Entry(parent, textvariable=v, width=9, justify="right").grid(row=r, column=1, sticky="e", pady=3)
            ttk.Label(parent, text=unit, foreground="#888", width=5).grid(row=r, column=2, sticky="w", padx=(4, 0))

    def buttons(self, parent, items):
        f = ttk.Frame(parent)
        f.grid(row=parent.grid_size()[1], column=0, columnspan=3, sticky="w", pady=4)
        for text, cmd in items:
            ttk.Button(f, text=text, command=cmd).pack(side="left", padx=(0, 6))

    # ---------- instellingen ----------
    def settings(self):
        s = dict(S.DEFAULTS)
        for k, v in self.vars.items():
            s[k] = v.get() if isinstance(S.DEFAULTS[k], str) else float(v.get().replace(",", "."))
        for k in ("sx", "sy", "sz", "layer", "first", "nozzle", "fil", "support_spacing"):
            if s[k] <= 0:
                raise ValueError(k)
        return s

    def apply_preset(self, _=None):
        for k, val in S.PRESETS[self.preset.get()].items():
            self.vars[k].set(fmt(val))

    def set_scale(self, p):
        for k in ("sx", "sy", "sz"):
            self.vars[k].set(f"{p:.1f}")

    def fit(self):
        if self.mesh is None:
            return
        try:
            self.uniform.set(True)
            self.set_scale(S.fit_percent(self.mesh, self.settings()))
        except ValueError:
            pass

    def rotate(self):
        try:
            self.vars["rot_z"].set(fmt((float(self.vars["rot_z"].get()) + 90) % 360))
        except ValueError:
            pass

    def on_change(self, *_):
        if self.uniform.get() and not self._lock and self.vars["sx"].get():
            self._lock = True
            self.vars["sy"].set(self.vars["sx"].get())
            self.vars["sz"].set(self.vars["sx"].get())
            self._lock = False
        self.update_info()

    def update_info(self):
        if self.mesh is None:
            return
        try:
            s = self.settings()
            e = S.extents(self.mesh, s)
        except ValueError:
            return
        self.info.config(text=f"{self.name}\n{e[0]:.1f} × {e[1]:.1f} × {e[2]:.1f} mm")
        w = []
        if e[0] > s["bed_x"] or e[1] > s["bed_y"] or e[2] > s["bed_z"]:
            w.append("Past niet op de bouwplaat")
        if not self.mesh.is_watertight:
            w.append("Model is niet waterdicht (kan slicefouten geven)")
        self.warn.config(text="\n".join("⚠ " + x for x in w))
        self.draw()

    # ---------- acties ----------
    def open(self):
        path = filedialog.askopenfilename(filetypes=FILETYPES)
        if not path:
            return
        try:
            self.mesh = S.load_mesh(path)
        except Exception as ex:
            messagebox.showerror("Kan model niet laden", str(ex))
            return
        self.name = os.path.basename(path)
        self.layers = self.gcode = None
        self.btn_save.state(["disabled"])
        self.slider.config(from_=1, to=1)
        self.layer_lbl.config(text="Laag")
        self.status.config(text="Model geladen. Pas instellingen aan en klik op Slicen.")
        self.update_info()

    def run_slice(self):
        if self.mesh is None:
            messagebox.showinfo("EasySlice", "Open eerst een model.")
            return
        try:
            s = self.settings()
        except ValueError:
            messagebox.showerror("Fout", "Ongeldige waarde in de instellingen.")
            return
        self.btn_slice.state(["disabled"])

        def work():
            try:
                layers = S.slice_model(self.mesh, s, lambda f, t: self.after(0, self.progress, f, t))
                gcode, stats = S.write_gcode(layers, s)
                self.after(0, self.done, layers, gcode, stats)
            except Exception as ex:
                self.after(0, self.fail, ex)

        threading.Thread(target=work, daemon=True).start()

    def progress(self, f, t):
        self.pb["value"] = f * 100
        self.status.config(text=t)

    def fail(self, ex):
        self.btn_slice.state(["!disabled"])
        self.status.config(text="Slicen mislukt")
        messagebox.showerror("Slicen mislukt", str(ex))

    def done(self, layers, gcode, stats):
        self.layers, self.gcode = layers, gcode
        self.slider.config(from_=1, to=len(layers))
        self.slider.set(1)
        t = int(stats["time"])
        self.status.config(text=f"{len(layers)} lagen  ·  ±{t // 3600}u {t % 3600 // 60:02d}m  ·  "
                                f"{stats['filament'] / 1000:.1f} m filament (±{stats['grams']:.0f} g)")
        self.btn_slice.state(["!disabled"])
        self.btn_save.state(["!disabled"])
        self.on_slider()

    def save(self):
        if not self.gcode:
            return
        path = filedialog.asksaveasfilename(defaultextension=".gcode", filetypes=[("G-code", "*.gcode")],
                                            initialfile=os.path.splitext(self.name)[0] + ".gcode")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.gcode)
            self.status.config(text="Opgeslagen: " + path)

    # ---------- voorbeeld ----------
    def cur_layer(self):
        return max(0, min(len(self.layers) - 1, int(round(float(self.slider.get()))) - 1))

    def on_slider(self, _=None):
        if self.layers:
            i = self.cur_layer()
            self.layer_lbl.config(text=f"Laag {i + 1} / {len(self.layers)}  ·  z {self.layers[i]['z']:.2f} mm")
        self.draw()

    def draw(self):
        cv = self.cv
        cv.delete("all")
        try:
            s = self.settings()
        except ValueError:
            return
        W, H = max(cv.winfo_width(), 60), max(cv.winfo_height(), 60)
        k = min((W - 40) / s["bed_x"], (H - 40) / s["bed_y"])
        ox, oy = (W - s["bed_x"] * k) / 2, (H + s["bed_y"] * k) / 2
        P = lambda x, y: (ox + x * k, oy - y * k)
        cv.create_rectangle(*P(0, s["bed_y"]), *P(s["bed_x"], 0), outline="#c3c7cf", fill="#ffffff")
        step = 10 if k * 10 >= 8 else 50
        for gx in range(step, int(s["bed_x"]), step):
            cv.create_line(*P(gx, 0), *P(gx, s["bed_y"]), fill="#eef0f3")
        for gy in range(step, int(s["bed_y"]), step):
            cv.create_line(*P(0, gy), *P(s["bed_x"], gy), fill="#eef0f3")
        if self.layers:
            i = self.cur_layer()
            if i > 0:
                for kind, pts in self.layers[i - 1]["paths"]:
                    if kind == "outer":
                        cv.create_line(*[c for p in pts for c in P(*p)], fill="#d3d7de", width=1)
            lw = max(1, s["nozzle"] * 1.1 * k)
            for kind, pts in self.layers[i]["paths"]:
                cv.create_line(*[c for p in pts for c in P(*p)], fill=COLORS[kind], width=lw)
            y0 = 12 + 18 * len(KINDS)
            cv.create_rectangle(8, 8, 150, y0 + 4, fill="#ffffff", outline="#e1e4e8")
            for n, (_, label, color) in enumerate(KINDS):
                y = 20 + 18 * n
                cv.create_line(16, y, 34, y, fill=color, width=3)
                cv.create_text(42, y, text=label, anchor="w", fill="#444", font=("Segoe UI", 9))
        elif self.mesh is not None:
            e = S.extents(self.mesh, s)
            x0, y0 = (s["bed_x"] - e[0]) / 2, (s["bed_y"] - e[1]) / 2
            cv.create_rectangle(*P(x0, y0 + e[1]), *P(x0 + e[0], y0), outline="#0067c0", width=2, dash=(5, 3))
        else:
            cv.create_text(W / 2, H / 2, text="Open een model met Ctrl+O", fill="#999", font=("Segoe UI", 14))


if __name__ == "__main__":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("easyslice.app")
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    App().mainloop()
