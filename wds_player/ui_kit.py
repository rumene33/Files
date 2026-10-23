"""Малък UI комплект за Tkinter в стил Apple/Android (тъмна тема): карти със секции, редове с
шеврон, превключватели, сегментиран избор, плъзгане за превъртане, навигация с „‹ Назад“ и
екранна клавиатура. Само стандартен tkinter (без допълнителни пакети)."""

from __future__ import annotations

import tkinter as tk

FONT = "DejaVu Sans"

# --- палитра (iOS тъмна тема / Material) ---
BG = "#000000"
CARD = "#1c1c1e"
CARD2 = "#2c2c2e"          # повдигнат елемент (бутони в карта)
SEP = "#38383a"
FG = "#ffffff"
MUTED = "#8e8e93"
ACCENT = "#0a84ff"
GREEN = "#30d158"
RED = "#ff453a"
ORANGE = "#ff9f0a"
TRACK = "#3a3a3c"

ROW_H = 58
DRAG = {"moved": False}     # плъзгане в ScrollView: след плъзгане докосването не е „тап“


def rounded_rect(c: tk.Canvas, x1, y1, x2, y2, r, **kw):
    """Закръглен правоъгълник (полигон с изгладени ъгли)."""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
           x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


class Switch(tk.Canvas):
    """Превключвател като на iOS (зелен, когато е включен)."""

    W, H = 56, 32

    def __init__(self, master, value: bool, command, bg=CARD):
        super().__init__(master, width=self.W, height=self.H, bg=bg, highlightthickness=0, bd=0)
        self.value = bool(value)
        self._command = command
        self.bind("<Button-1>", lambda e: self.toggle())
        self._draw()

    def _draw(self):
        self.delete("all")
        track = GREEN if self.value else TRACK
        rounded_rect(self, 2, 2, self.W - 2, self.H - 2, (self.H - 4) / 2, fill=track, outline=track)
        x = self.W - 17 if self.value else 17
        self.create_oval(x - 13, self.H / 2 - 13, x + 13, self.H / 2 + 13, fill="#ffffff", outline="#ffffff")

    def set(self, value: bool):
        self.value = bool(value)
        self._draw()

    def toggle(self):
        self.value = not self.value
        self._draw()
        if self._command:
            self._command(self.value)


class Pill(tk.Canvas):
    """Закръглен бутон (primary = син, danger = червен, quiet = сив)."""

    def __init__(self, master, text, command, kind="primary", width=140, height=46, font_size=15,
                 bg=BG):
        super().__init__(master, width=width, height=height, bg=bg, highlightthickness=0, bd=0)
        # не self._w: в Tkinter _w е името на елемента и подмяната му чупи всички извиквания към Tk
        self._pw, self._ph, self._text, self._command, self._kind = width, height, text, command, kind
        self._font = (FONT, font_size, "bold")
        self._enabled = True
        self.bind("<Button-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self._draw(False)

    COLORS = {"primary": (ACCENT, "#0060df"), "danger": (RED, "#d0342b"), "quiet": (CARD2, "#48484a"),
              "good": (GREEN, "#24a844")}

    def _draw(self, pressed: bool):
        self.delete("all")
        base, dark = self.COLORS.get(self._kind, self.COLORS["primary"])
        col = dark if pressed else base
        if not self._enabled:
            col = "#2a2a2c"
        rounded_rect(self, 1, 1, self._pw - 1, self._ph - 1, self._ph / 2, fill=col, outline=col)
        self.create_text(self._pw / 2, self._ph / 2, text=self._text, font=self._font,
                         fill="#ffffff" if self._enabled else "#6b6b70")

    def set_text(self, text):
        self._text = text
        self._draw(False)

    def set_kind(self, kind):
        self._kind = kind
        self._draw(False)

    def set_enabled(self, on: bool):
        self._enabled = bool(on)
        self._draw(False)

    def _press(self, _e):
        if self._enabled:
            self._draw(True)

    def _release(self, e):
        if not self._enabled:
            return
        self._draw(False)
        if 0 <= e.x <= self._pw and 0 <= e.y <= self._ph and self._command:
            self._command()


class ProgressBar(tk.Canvas):
    """Лента за напредъка на шоуто/песента: закръглена, с кръгче и процент. set(0..1)."""

    def __init__(self, master, height=34, bg=BG):
        super().__init__(master, height=height, bg=bg, highlightthickness=0, bd=0)
        self._frac = 0.0
        self._h = height
        self.bind("<Configure>", lambda e: self._draw())

    def set(self, frac: float):
        frac = min(1.0, max(0.0, float(frac)))
        if abs(frac - self._frac) > 0.0005:
            self._frac = frac
            self._draw()

    def __setitem__(self, key, value):          # съвместимост с ttk.Progressbar["value"] (0..1000)
        if key == "value":
            self.set(float(value) / 1000.0)

    def _draw(self):
        w = self.winfo_width()
        if w < 40:
            return
        self.delete("all")
        h = self._h
        tr = 12                                        # дебелина на лентата
        y1, y2 = (h - tr) / 2, (h + tr) / 2
        pad = 12
        rounded_rect(self, pad, y1, w - pad, y2, tr / 2, fill=TRACK, outline=TRACK)
        x = pad + (w - 2 * pad) * self._frac
        if self._frac > 0:
            rounded_rect(self, pad, y1, max(pad + tr, x), y2, tr / 2, fill=ACCENT, outline=ACCENT)
        self.create_oval(x - 11, h / 2 - 11, x + 11, h / 2 + 11, fill="#ffffff", outline="#ffffff")


class Segmented(tk.Frame):
    """Сегментиран избор (като UISegmentedControl)."""

    def __init__(self, master, options, current, on_change, bg=CARD, font_size=13, pad_x=14):
        super().__init__(master, bg=CARD2)
        self._on_change = on_change
        self._btns = {}
        for value, label in options:
            b = tk.Button(self, text=label, font=(FONT, font_size, "bold"), relief="flat", bd=0,
                          padx=pad_x, pady=7, activebackground=ACCENT, activeforeground="#ffffff",
                          command=lambda v=value: self._pick(v))
            b.pack(side="left", padx=2, pady=2)
            self._btns[value] = b
        self.set(current)

    def set(self, value):
        for v, b in self._btns.items():
            b.config(bg=ACCENT if v == value else CARD2, fg="#ffffff" if v == value else MUTED)
        self.current = value

    def _pick(self, value):
        self.set(value)
        self._on_change(value)


class Stepper(tk.Frame):
    """− стойност + със задържане за бързо повторение."""

    def __init__(self, master, get, set_, lo, hi, step=1, fmt=str, big_step=None, width=7, bg=CARD):
        super().__init__(master, bg=bg)
        self._get, self._set, self.lo, self.hi, self.step = get, set_, lo, hi, step
        self._big = big_step
        self._fmt = fmt
        self._job = None
        kw = dict(font=(FONT, 18, "bold"), bg=CARD2, fg=FG, activebackground=ACCENT, relief="flat",
                  bd=0, width=3, pady=2)
        self.minus = tk.Button(self, text="−", **kw)
        self.minus.pack(side="left")
        self.lbl = tk.Label(self, font=(FONT, 16, "bold"), bg=bg, fg=FG, width=width)
        self.lbl.pack(side="left", padx=4)
        self.plus = tk.Button(self, text="+", **kw)
        self.plus.pack(side="left")
        for btn, d in ((self.minus, -1), (self.plus, 1)):
            btn.bind("<ButtonPress-1>", lambda e, d=d: self._press(d))
            btn.bind("<ButtonRelease-1>", lambda e: self._release())
        self.show()

    def show(self):
        self.lbl.config(text=self._fmt(self._get()))

    def _apply(self, d, mult=1):
        v = min(self.hi, max(self.lo, self._get() + d * self.step * mult))
        self._set(v)
        self.show()

    def _press(self, d):
        self._apply(d)
        self._job = self.after(450, lambda: self._repeat(d, 0))

    def _repeat(self, d, n):
        self._apply(d, 5 if (self._big and n > 8) else 1)
        self._job = self.after(90, lambda: self._repeat(d, n + 1))

    def _release(self):
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None

    def destroy(self):
        self._release()
        super().destroy()


# ---------------- карти и редове ----------------
def section(parent, title: str | None = None):
    """Заглавие на секция (малки сиви букви) + карта; връща картата."""
    if title:
        tk.Label(parent, text=title.upper(), font=(FONT, 11, "bold"), bg=BG, fg=MUTED,
                 anchor="w").pack(fill="x", padx=22, pady=(16, 5))
    else:
        tk.Frame(parent, height=12, bg=BG).pack(fill="x")
    card = tk.Frame(parent, bg=CARD)
    card.pack(fill="x", padx=14)
    card._rows = 0
    return card


def _separator(card):
    if card._rows:
        tk.Frame(card, height=1, bg=SEP).pack(fill="x", padx=16)
    card._rows += 1


def row(card, title: str, value: str | None = None, command=None, chevron: bool = False,
        subtitle: str | None = None, title_fg=FG, widget=None):
    """Ред в карта: заглавие (+ подзаглавие) вляво; стойност / шеврон / елемент вдясно.
    widget(parent) -> създава контрол вдясно (Switch, Stepper, Segmented). Връща реда."""
    _separator(card)
    f = tk.Frame(card, bg=CARD, height=ROW_H)
    f.pack(fill="x")
    f.pack_propagate(False)
    left = tk.Frame(f, bg=CARD)
    left.pack(side="left", fill="y", padx=(16, 8))
    t = tk.Label(left, text=title, font=(FONT, 15), bg=CARD, fg=title_fg, anchor="w")
    t.pack(side="top", anchor="w", expand=True if not subtitle else False, pady=(8 if subtitle else 0, 0))
    f.title_lbl = t
    if subtitle:
        s = tk.Label(left, text=subtitle, font=(FONT, 11), bg=CARD, fg=MUTED, anchor="w")
        s.pack(side="top", anchor="w")
        f.sub_lbl = s
    right = tk.Frame(f, bg=CARD)
    right.pack(side="right", fill="y", padx=(8, 14))
    f.value_lbl = None
    if widget is not None:
        w = widget(right)
        w.pack(side="right", anchor="e", expand=True)
        f.widget = w
    else:
        if chevron:
            tk.Label(right, text="›", font=(FONT, 24), bg=CARD, fg=MUTED).pack(side="right")
        if value is not None:
            f.value_lbl = tk.Label(right, text=value, font=(FONT, 14), bg=CARD, fg=MUTED)
            f.value_lbl.pack(side="right", padx=(0, 6))
    if command is not None:
        def tap(_e, c=command):
            if not DRAG["moved"]:
                c()
        for w in (f, left, t, right) + tuple(right.winfo_children()):
            w.bind("<ButtonRelease-1>", tap, add="+")
    return f


def note(parent, text: str, fg=MUTED):
    tk.Label(parent, text=text, font=(FONT, 11), bg=BG, fg=fg, anchor="w", justify="left",
             wraplength=740).pack(fill="x", padx=24, pady=(6, 0))


def switch_row(card, title, value, on_change, subtitle=None):
    return row(card, title, subtitle=subtitle,
               widget=lambda p: Switch(p, value, on_change))


# ---------------- превъртане с плъзгане ----------------
class ScrollView(tk.Frame):
    """Вертикално превъртащо се съдържание; плъзга се с пръст (и колелце на мишка)."""

    def __init__(self, master, bg=BG):
        super().__init__(master, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, yscrollincrement=1)
        self.canvas.pack(fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._on_body)
        self.canvas.bind("<Configure>", self._on_canvas)
        self._y0 = None
        self._moved = False
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-e.delta, "units"))
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-60, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(60, "units"))
        self.enable_drag(self.canvas)

    def _on_body(self, _e):
        self.canvas.configure(scrollregion=(0, 0, self.body.winfo_reqwidth(), self.body.winfo_reqheight()))

    def _on_canvas(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)

    def enable_drag(self, widget):
        """Включва плъзгането върху елемент и всички негови наследници."""
        if isinstance(widget, (tk.Scale, tk.Listbox)):
            return
        widget.bind("<ButtonPress-1>", self._down, add="+")
        widget.bind("<B1-Motion>", self._move, add="+")
        for child in widget.winfo_children():
            self.enable_drag(child)

    def finish(self):
        """Извикай след като съдържанието е построено."""
        self.enable_drag(self.body)

    def _down(self, e):
        self._y0 = e.y_root
        self._start = e.y_root
        DRAG["moved"] = False

    def _move(self, e):
        if self._y0 is None:
            return
        if abs(e.y_root - self._start) > 8:
            DRAG["moved"] = True
        dy = self._y0 - e.y_root
        if abs(dy) >= 2:
            self.canvas.yview_scroll(int(dy), "units")
            self._y0 = e.y_root

    def position(self) -> float:
        return self.canvas.yview()[0]

    def restore(self, frac: float):
        self.update_idletasks()
        self.canvas.yview_moveto(frac)


# ---------------- навигация ----------------
class Navigator(tk.Toplevel):
    """Цял екран с лента „‹ Назад / Заглавие“ и стек от страници (като Settings на iOS)."""

    def __init__(self, app_root, title: str, builder, cover=None):
        super().__init__(app_root, bg=BG)
        self.title(title)
        self.transient(app_root)
        if cover is not None:
            cover(self, app_root)
        self._stack = []        # [(title, builder, ScrollView)]
        bar = tk.Frame(self, bg=BG, height=54)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)
        self.back_btn = tk.Button(bar, text="‹  Назад", font=(FONT, 16), bg=BG, fg=ACCENT,
                                  activebackground=BG, activeforeground=ACCENT, relief="flat", bd=0,
                                  command=self.back)
        self.back_btn.pack(side="left", padx=10)
        self.title_lbl = tk.Label(bar, text=title, font=(FONT, 17, "bold"), bg=BG, fg=FG)
        self.title_lbl.place(relx=0.5, rely=0.5, anchor="center")
        self.action_frame = tk.Frame(bar, bg=BG)
        self.action_frame.pack(side="right", padx=10)
        tk.Frame(self, height=1, bg=SEP).pack(fill="x")
        self.holder = tk.Frame(self, bg=BG)
        self.holder.pack(fill="both", expand=True)
        self.push(title, builder)
        self.grab_set()

    def _show(self, view):
        for _t, _b, v in self._stack:
            v.pack_forget()
        view.pack(fill="both", expand=True)

    def push(self, title, builder):
        view = ScrollView(self.holder)
        self._stack.append((title, builder, view))
        builder(self, view.body)
        view.finish()
        self._show(view)
        self.title_lbl.config(text=title)

    def back(self):
        if len(self._stack) <= 1:
            self.destroy()
            return
        _t, _b, view = self._stack.pop()
        view.destroy()
        title, _builder, prev = self._stack[-1]
        self._show(prev)
        self.title_lbl.config(text=title)
        self.rebuild()        # данните може да са се променили

    def rebuild(self):
        """Построява наново текущата страница (запазва позицията на превъртане)."""
        title, builder, view = self._stack[-1]
        pos = view.position()
        for w in view.body.winfo_children():
            w.destroy()
        builder(self, view.body)
        view.finish()
        view.restore(pos)

    def set_actions(self, *buttons):
        for w in self.action_frame.winfo_children():
            w.destroy()


# ---------------- екранна клавиатура ----------------
_ROWS_TEXT = ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm"]
_ROWS_SYM = ["!@#$%^&*()", "-_=+[]{}\\|", ";:'\",.<>/?", "`~€£§°№"]


class KeyboardDialog(tk.Toplevel):
    """Екранна клавиатура за SSID/парола ('text') и цифрова за IP/маска/DNS ('ip', 'num')."""

    def __init__(self, master, title, initial, kind, on_done, secret=False, cover=None):
        super().__init__(master, bg=BG)
        self.title(title)
        self.transient(master)
        if cover is not None:
            cover(self, master)
        self.text = initial or ""
        self.kind = kind
        self.secret = secret
        self.shown = not secret
        self.shift = False
        self.symbols = False
        self._on_done = on_done
        tk.Label(self, text=title, font=(FONT, 15), bg=BG, fg=MUTED).pack(pady=(10, 2))
        self.out = tk.Label(self, text="", font=(FONT, 22, "bold"), bg=CARD, fg=FG, anchor="w", padx=14,
                            pady=8)
        self.out.pack(fill="x", padx=14, pady=4)
        self.keys = tk.Frame(self, bg=BG)
        self.keys.pack(fill="both", expand=True, padx=10, pady=6)
        self._build()
        self._refresh()
        self.grab_set()

    # --- изграждане ---
    def _key(self, parent, label, cmd, col, row_, span=1, kind="key"):
        colors = {"key": (CARD2, FG), "accent": (ACCENT, "#ffffff"), "danger": (RED, "#ffffff"),
                  "quiet": ("#48484a", FG)}[kind]
        b = tk.Button(parent, text=label, font=(FONT, 17, "bold"), bg=colors[0], fg=colors[1],
                      activebackground=ACCENT, relief="flat", bd=0, command=cmd)
        b.grid(row=row_, column=col, columnspan=span, sticky="nsew", padx=3, pady=3)
        return b

    def _build(self):
        for w in self.keys.winfo_children():
            w.destroy()
        k = self.keys
        if self.kind in ("ip", "num"):
            layout = ["123", "456", "789"]
            for r, chars in enumerate(layout):
                for c, ch in enumerate(chars):
                    self._key(k, ch, lambda ch=ch: self._type(ch), c, r)
            extra = "." if self.kind == "ip" else ("-" if self.kind == "num" else "")
            self._key(k, extra or " ", (lambda: self._type(extra)) if extra else (lambda: None), 0, 3)
            self._key(k, "0", lambda: self._type("0"), 1, 3)
            self._key(k, "⌫", self._back, 2, 3, kind="quiet")
            self._key(k, "OK", self._ok, 3, 0, span=1, kind="accent")
            self._key(k, "✕", self.destroy, 3, 1, kind="quiet")
            if self.kind == "ip":
                self._key(k, ",", lambda: self._type(","), 3, 2)
            for c in range(4):
                k.columnconfigure(c, weight=1, uniform="k")
            for r in range(4):
                k.rowconfigure(r, weight=1, uniform="r")
            return
        rows = _ROWS_SYM if self.symbols else _ROWS_TEXT
        for r, chars in enumerate(rows):
            frame = tk.Frame(k, bg=BG)
            frame.grid(row=r, column=0, sticky="nsew")
            k.rowconfigure(r, weight=1, uniform="r")
            for i, ch in enumerate(chars):
                shown = ch.upper() if (self.shift and not self.symbols) else ch
                b = tk.Button(frame, text=shown, font=(FONT, 17, "bold"), bg=CARD2, fg=FG,
                              activebackground=ACCENT, relief="flat", bd=0,
                              command=lambda s=shown: self._type(s))
                b.grid(row=0, column=i, sticky="nsew", padx=3, pady=3)
                frame.columnconfigure(i, weight=1, uniform="c")
            frame.rowconfigure(0, weight=1)
        bottom = tk.Frame(k, bg=BG)
        bottom.grid(row=len(rows), column=0, sticky="nsew")
        k.rowconfigure(len(rows), weight=1, uniform="r")
        k.columnconfigure(0, weight=1)
        spec = [("⇧", self._shift, "quiet", 1), ("123" if not self.symbols else "abc", self._symbols, "quiet", 1),
                ("интервал", lambda: self._type(" "), "key", 3), ("⌫", self._back, "quiet", 1),
                ("OK", self._ok, "accent", 1)]
        if self.secret:
            spec.insert(2, ("👁" if False else "Покажи", self._reveal, "quiet", 1))
        c = 0
        for label, cmd, kind, weight in spec:
            colors = {"key": (CARD2, FG), "accent": (ACCENT, "#ffffff"), "quiet": ("#48484a", FG)}[kind]
            b = tk.Button(bottom, text=label, font=(FONT, 15, "bold"), bg=colors[0], fg=colors[1],
                          activebackground=ACCENT, relief="flat", bd=0, command=cmd)
            b.grid(row=0, column=c, sticky="nsew", padx=3, pady=3)
            bottom.columnconfigure(c, weight=weight, uniform=None)
            c += 1
        bottom.rowconfigure(0, weight=1)

    # --- действия ---
    def _refresh(self):
        shown = self.text if self.shown else "•" * len(self.text)
        self.out.config(text=(shown or " ") + "▏")

    def _type(self, ch):
        self.text += ch
        if self.shift and self.kind == "text":
            self.shift = False
            self._build()
        self._refresh()

    def _back(self):
        self.text = self.text[:-1]
        self._refresh()

    def _shift(self):
        self.shift = not self.shift
        self._build()

    def _symbols(self):
        self.symbols = not self.symbols
        self._build()

    def _reveal(self):
        self.shown = not self.shown
        self._refresh()

    def _ok(self):
        value = self.text
        self.destroy()
        self._on_done(value)


def restore_grab(child, parent):
    """Когато подпрозорецът се затвори, родителят отново е модален (Tk не го връща сам)."""
    def back(e):
        if e.widget is child:
            def regrab():
                try:
                    if parent.winfo_exists():
                        parent.grab_set()
                except tk.TclError:
                    pass
            parent.after(60, regrab)
    child.bind("<Destroy>", back, add="+")
