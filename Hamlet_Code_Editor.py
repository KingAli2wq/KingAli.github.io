import os
import sys
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk
import json
from tkcode import CodeEditor
from PIL import Image, ImageTk
import keyword
import subprocess

PYTHON_KEYWORDS = set(keyword.kwlist + dir(__builtins__))

class LineNumberText(tk.Text):
    def __init__(self, master, text_widget, **kwargs):
        super().__init__(
            master,
            width=5,
            padx=4,
            takefocus=0,
            border=0,
            highlightthickness=0,
            state='disabled',
            bg="#2e2e2e",
            fg="#888888",
            font=text_widget['font'],
            **kwargs
        )
        self.textwidget = text_widget
        self.textwidget.bind("<<Change>>", self.redraw)
        self.textwidget.bind("<Configure>", self.redraw)
        self.textwidget.bind("<KeyRelease>", self.redraw)
        self.textwidget.bind("<MouseWheel>", self.redraw)
        self.textwidget.bind("<Button-1>", self.redraw)
        self.textwidget.bind("<ButtonRelease-1>", self.redraw)
        self.textwidget['yscrollcommand'] = self.sync_scroll
        self['yscrollcommand'] = self.sync_scroll
        self.redraw()

    def sync_scroll(self, *args):
        self.yview_moveto(self.textwidget.yview()[0])

    def redraw(self, event=None):
        self.config(state='normal')
        self.delete("1.0", tk.END)
        # Get visible lines
        first = self.textwidget.index("@0,0")
        last = self.textwidget.index(f"@0,{self.textwidget.winfo_height()}")
        first_line = int(first.split('.')[0])
        last_line = int(last.split('.')[0])
        lines = [str(i) for i in range(first_line, last_line + 1)]
        self.insert("1.0", "\n".join(lines))
        self.config(state='disabled')

class CustomConsole(tk.Text):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.configure(state='disabled')
        self.input_queue = queue.Queue()
        self.tag_configure("error", foreground="#ff5555")  # red for errors

    def write(self, text):
        self.configure(state='normal')
        if "Traceback" in text or "Error:" in text or "Exception" in text:
            self.insert("end", str(text), "error")
        else:
            self.insert("end", str(text))
        self.configure(state='disabled')
        self.see("end")

    def flush(self):
        pass

    def readline(self):
        return self.input_queue.get() + "\n"

    def isatty(self):
        return True

    def schedule_redraw(self, event=None):
        if self._after_id:
            self.after_cancel(self._after_id)
        self._after_id = self.after(10, self.redraw)

    def redraw(self, event=None):
        self.delete("all")
        try:
            first = self.textwidget.index("@0,0")
            last = self.textwidget.index(f"@0,{self.textwidget.winfo_height()}")
            first_line = int(first.split('.')[0])
            last_line = int(last.split('.')[0])
        except Exception:
            return

        import tkinter.font as tkfont
        base_font = tkfont.Font(font=self.line_font)
        bold_font = base_font.copy()
        bold_font.configure(weight="bold")

        current_line = int(self.textwidget.index(tk.INSERT).split('.')[0])

        for i in range(first_line, last_line + 1):
            dline = self.textwidget.dlineinfo(f"{i}.0")
            if dline:
                y = dline[1]
                if i == current_line:
                    self.create_text(38, y, anchor="ne", text=str(i), fill="#ffcc00", font=bold_font)
                else:
                    self.create_text(38, y, anchor="ne", text=str(i), fill="#888888", font=base_font)

class CustomCodeEditor(CodeEditor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bind("<<Modified>>", self._on_change)

    def _on_change(self, event=None):
        self.event_generate("<<Change>>")
        self.edit_modified(False)

class CodeEditorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Hamlet - Python Code Editor")
        self.dark_mode = True
        self.config_file = "last_file.txt"
        self.font_family = "Consolas"
        self.font_size = 14
        self.syntax_theme = "monokai"
        self.style = ttk.Style()
        self.create_menu()  # This creates and packs self.menu_frame at the top
        # --- MAIN EDITOR AREA ---
        self.main_frame = tk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.main_frame.pack(fill=tk.BOTH, expand=1)

        self.sidebar = ttk.Treeview(self.main_frame, style="Custom.Treeview")
        self.sidebar.bind("<Double-1>", self.open_file_from_sidebar)
        self.populate_sidebar(os.getcwd())
        self.main_frame.add(self.sidebar, width=250)

        self.editor_frame = tk.Frame(self.main_frame, bg="#1e1e1e", bd=2, relief=tk.FLAT)
        self.main_frame.add(self.editor_frame)

        self.notebook = ttk.Notebook(self.editor_frame)
        self.notebook.pack(fill=tk.BOTH, expand=1)

        self.tabs = []
        self.new_tab()

        self.filename = None

        self.bottom_frame = tk.Frame(self.root, bg="#1e1e1e")
        self.bottom_frame.pack(side="bottom", fill=tk.X)

        self.console = CustomConsole(
            self.bottom_frame,
            height=10,
            font=(self.font_family, 12),
            bg="#282a36",
            fg="#f8f8f2",
            bd=2,
            relief=tk.FLAT
        )
        self.console.pack(fill=tk.X, padx=10, pady=(5, 0))

        self.input_entry = tk.Entry(
            self.bottom_frame,
            font=(self.font_family, 12),
            bg="#1e1e1e",
            fg="#f8f8f2",
            insertbackground="white",
            relief=tk.FLAT
        )
        self.input_entry.pack(fill=tk.X, padx=10, pady=(0, 10))
        self.input_entry.bind("<Return>", self.send_input_to_console)
        self.input_entry.bind("<Up>", self.history_up)
        self.input_entry.bind("<Down>", self.history_down)

        self.input_history = []
        self.history_index = None

        self.set_theme(self.dark_mode)
        self.load_last_file()
        self.show_splash()

        self.running_thread = None
        self.terminal_mode = False

    def create_menu(self):
        # Custom menu bar frame
        self.menu_frame = tk.Frame(self.root, bg="#23272e", height=32)
        self.menu_frame.pack(side="top", fill="x")

        style = ttk.Style()
        style.configure("Menu.TButton", background="#23272e", foreground="#d4d4d4", borderwidth=0, focusthickness=0, font=(self.font_family, 12))
        style.map("Menu.TButton", background=[("active", "#282a36")], foreground=[("active", "#61dafb")])

        # File menu
        file_btn = ttk.Menubutton(self.menu_frame, text="File", style="Menu.TButton")
        file_menu = tk.Menu(file_btn, tearoff=0, bg="#23272e", fg="#d4d4d4", activebackground="#282a36", activeforeground="#61dafb")
        file_menu.add_command(label="New File", command=self.new_file)
        file_menu.add_command(label="Open File", command=self.open_file)
        file_menu.add_command(label="Save", command=self.save_file)
        file_menu.add_command(label="Save As", command=self.save_file_as)
        file_menu.add_separator()
        file_menu.add_command(label="New Tab", command=self.new_tab)  # <-- Add this line
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        file_btn["menu"] = file_menu
        file_btn.pack(side="left", padx=2, pady=2)

        # Edit menu
        edit_btn = ttk.Menubutton(self.menu_frame, text="Edit", style="Menu.TButton")
        edit_menu = tk.Menu(edit_btn, tearoff=0, bg="#23272e", fg="#d4d4d4", activebackground="#282a36", activeforeground="#61dafb")
        edit_menu.add_command(label="Find/Replace", command=self.show_find_replace)
        edit_menu.add_command(label="Goto Line", command=self.goto_line)
        edit_menu.add_command(label="Goto Definition", command=self.goto_definition)
        edit_menu.add_command(label="Go to Symbol", command=self.goto_symbol)
        snippets_menu = tk.Menu(edit_menu, tearoff=0, bg="#23272e", fg="#d4d4d4")
        snippets_menu.add_command(label="Main Guard", command=lambda: self.insert_snippet("main_guard"))
        snippets_menu.add_command(label="Function", command=lambda: self.insert_snippet("function"))
        snippets_menu.add_command(label="Class", command=lambda: self.insert_snippet("class"))
        snippets_menu.add_command(label="For Loop", command=lambda: self.insert_snippet("for_loop"))
        edit_menu.add_cascade(label="Snippets", menu=snippets_menu)
        edit_btn["menu"] = edit_menu
        edit_btn.pack(side="left", padx=2, pady=2)

        # Run menu
        run_btn = ttk.Menubutton(self.menu_frame, text="Run", style="Menu.TButton")
        run_menu = tk.Menu(run_btn, tearoff=0, bg="#23272e", fg="#d4d4d4", activebackground="#282a36", activeforeground="#61dafb")
        run_menu.add_command(label="Run", command=self.run_code)
        run_menu.add_command(label="Stop", command=self.stop_code)
        run_menu.add_command(label="Clear Console", command=self.clear_console)
        run_menu.add_separator()
        run_menu.add_command(label="Open Terminal", command=self.open_terminal)
        run_btn["menu"] = run_menu
        run_btn.pack(side="left", padx=2, pady=2)

        # Settings menu
        settings_btn = ttk.Menubutton(self.menu_frame, text="Settings", style="Menu.TButton")
        settings_menu = tk.Menu(settings_btn, tearoff=0, bg="#23272e", fg="#d4d4d4", activebackground="#282a36", activeforeground="#61dafb")
        settings_menu.add_command(label="Toggle Theme", command=self.toggle_theme)
        settings_menu.add_command(label="Change Font", command=self.change_font)
        settings_menu.add_command(label="Change Syntax Highlighting", command=self.change_syntax_theme)
        settings_menu.add_separator()
        settings_menu.add_command(label="Close Tree", command=self.close_sidebar)
        settings_menu.add_command(label="Open Tree", command=self.open_sidebar)
        settings_btn["menu"] = settings_menu
        settings_btn.pack(side="left", padx=2, pady=2)

    def create_editor(self):
        return CustomCodeEditor(
            self.editor_frame,
            language='python',
            highlighter=self.syntax_theme,
            autofocus=True,
            blockcursor=True,
            font=(self.font_family, self.font_size),
            padx=10,
            pady=10,
            insertofftime=0
        )

    def change_highlight_color(self, tag):
        # No-op, since no highlighting is used
        pass

    def send_input_to_console(self, event=None):
        user_input = self.input_entry.get()
        if user_input.strip():
            self.input_history.append(user_input)
        self.history_index = None
        self.console.write(f">>> {user_input}\n")
        self.input_entry.delete(0, tk.END)
        # Send input to subprocess if running
        if hasattr(self, 'proc') and self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write(user_input + '\n')
                self.proc.stdin.flush()
            except Exception as e:
                self.console.write(f"[Input Error: {e}]\n")

    def history_up(self, event=None):
        if not self.input_history:
            return "break"
        if self.history_index is None:
            self.history_index = len(self.input_history) - 1
        elif self.history_index > 0:
            self.history_index -= 1
        self.input_entry.delete(0, tk.END)
        self.input_entry.insert(0, self.input_history[self.history_index])
        return "break"

    def history_down(self, event=None):
        if self.history_index is None:
            return "break"
        if self.history_index < len(self.input_history) - 1:
            self.history_index += 1
            self.input_entry.delete(0, tk.END)
            self.input_entry.insert(0, self.input_history[self.history_index])
        else:
            self.input_entry.delete(0, tk.END)
            self.history_index = None
        return "break"

    def on_editor_activity(self, event=None):
        self.linenumbers.redraw()
        self.editor.highlight_all()
        # No highlighting functions called

    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        self.set_theme(self.dark_mode)

    def set_theme(self, dark):
        theme_values = {
            True: {
                "bg": "#23272e",  # VS Code dark
                "fg": "#d4d4d4",
                "line_bg": "#2c313a",
                "console_bg": "#1e1e1e",
                "console_fg": "#d4d4d4",
                "entry_bg": "#23272e",
                "entry_fg": "#d4d4d4",
                "insert_bg": "#61dafb"
            },
            False: {
                "bg": "#f5f6fa",  # Light pastel
                "fg": "#222222",
                "line_bg": "#e1e1e1",
                "console_bg": "#f5f6fa",
                "console_fg": "#222222",
                "entry_bg": "#ffffff",
                "entry_fg": "#222222",
                "insert_bg": "#007acc"
            }
        }
        theme = theme_values[dark]
        self.root.configure(bg=theme["bg"])
        self.style.theme_use('clam')
        self.style.configure("TFrame", background=theme["bg"])
        self.style.configure("TLabel", background=theme["bg"], foreground=theme["fg"])
        self.style.configure("Custom.Treeview", background=theme["bg"], foreground=theme["fg"], fieldbackground=theme["bg"])
        self.style.configure("TNotebook", background="#23272e", borderwidth=0)
        self.style.configure("TNotebook.Tab", background="#23272e", foreground="#d4d4d4", padding=[10, 5], font=(self.font_family, 12))
        self.style.map("TNotebook.Tab", background=[("selected", "#282a36")], foreground=[("selected", "#61dafb")])
        self.style.configure("Vertical.TScrollbar", gripcount=0, background="#23272e", darkcolor="#23272e", lightcolor="#23272e", troughcolor="#1e1e1e", bordercolor="#23272e", arrowcolor="#61dafb")
        self.console.config(bg=theme["console_bg"], fg=theme["console_fg"])
        self.input_entry.config(bg=theme["entry_bg"], fg=theme["entry_fg"], insertbackground=theme["insert_bg"])
        self.editor_frame.config(bg=theme["bg"])
        for tab in self.tabs:
            tab["linenumbers"].config(bg=theme["line_bg"])
            tab["editor"].config(bg=theme["bg"], fg=theme["fg"])

    def change_font(self):
        font_window = tk.Toplevel(self.root)
        font_window.title("Select Font")
        font_window.geometry("300x200")
        font_window.grab_set()

        tk.Label(font_window, text="Choose Font:").pack(pady=5)
        font_options = ["Consolas", "Courier New", "Lucida Console", "Arial", "Verdana"]
        selected_font = tk.StringVar(value=self.font_family)
        font_dropdown = ttk.Combobox(font_window, values=font_options, textvariable=selected_font, state="readonly")
        font_dropdown.pack(pady=5)

        tk.Label(font_window, text="Font Size:").pack(pady=5)
        size_spinbox = tk.Spinbox(font_window, from_=8, to=32, increment=1)
        size_spinbox.delete(0, "end")
        size_spinbox.insert(0, str(self.font_size))
        size_spinbox.pack(pady=5)

        def apply_font():
            font = selected_font.get()
            size = int(size_spinbox.get())
            self.font_family = font
            self.font_size = size
            self.editor.config(font=(font, size))
            self.input_entry.config(font=(font, 12))
            self.console.config(font=(font, 12))
            self.linenumbers.line_font = (font, size)
            self.linenumbers.redraw()
            font_window.destroy()

        ttk.Button(font_window, text="Apply", command=apply_font, style="Menu.TButton").pack(pady=10, ipadx=10, ipady=3)

    def change_syntax_theme(self):
        theme_window = tk.Toplevel(self.root)
        theme_window.title("Select Syntax Highlighting Theme")
        theme_window.geometry("350x150")
        theme_window.grab_set()

        tk.Label(theme_window, text="Choose Theme:").pack(pady=5)
        themes = ["azure", "dracula", "mariana", "monokai", "monokai-plus-plus"]
        selected_theme = tk.StringVar(value=self.syntax_theme)
        dropdown = ttk.Combobox(theme_window, values=themes, textvariable=selected_theme, state="readonly")
        dropdown.pack(pady=5)

        def apply_theme():
            theme = selected_theme.get()
            if theme == "custom":
                json_path = filedialog.askopenfilename(title="Choose Custom Theme JSON", filetypes=[("JSON files", "*.json")])
                if json_path and os.path.exists(json_path):
                    with open(json_path, "r") as f:
                        try:
                            style_dict = json.load(f)
                            CodeEditor.add_highlighting_theme("custom", style_dict)
                            self.syntax_theme = "custom"
                        except Exception as e:
                            messagebox.showerror("Error", f"Invalid JSON: {e}")
                            return
                else:
                    return
            else:
                self.syntax_theme = theme

            tab = self.get_current_tab()
            if tab:
                content = tab["editor"].get("1.0", tk.END)
                tab["editor"].destroy()
                # Create a new editor with the new theme
                new_editor = CustomCodeEditor(
                    tab["frame"],
                    language='python',
                    highlighter=self.syntax_theme,
                    autofocus=True,
                    blockcursor=True,
                    font=(self.font_family, self.font_size),
                    padx=10,
                    pady=10,
                    insertofftime=0
                )
                tab["editor"] = new_editor
                tab["linenumbers"].textwidget = new_editor
                new_editor.insert("1.0", content)
                new_editor.highlight_all()
                new_editor.focus_set()
                new_editor.pack(side="right", fill=tk.BOTH, expand=1)
                new_editor.bind("<MouseWheel>", lambda e: tab["linenumbers"].redraw())
                new_editor.bind("<Button-4>", lambda e: tab["linenumbers"].redraw())
                new_editor.bind("<Button-5>", lambda e: tab["linenumbers"].redraw())
                new_editor.bind("<KeyRelease>", self.on_editor_activity)
                new_editor.bind("<<Change>>", self.on_editor_activity)
                new_editor.bind("<KeyRelease>", self.show_autocomplete)
                new_editor.bind("<Tab>", self.autocomplete_tab)
                new_editor.bind("<Key>", self.editor_key_handler)
                tab["linenumbers"].redraw()
            theme_window.destroy()

        tk.Button(theme_window, text="Apply", command=apply_theme).pack(pady=10)

    def new_file(self):
        self.editor.delete("1.0", tk.END)
        self.filename = None
        self.root.title("Untitled - Python Code Editor")

    def open_file(self):
        filepath = filedialog.askopenfilename(filetypes=[("Python Files", "*.py"), ("All Files", "*.*")])
        if filepath:
            self.load_file(filepath)

    def save_file(self):
        if self.filename:
            with open(self.filename, "w") as file:
                file.write(self.editor.get("1.0", tk.END))
            messagebox.showinfo("Success", "File Saved Successfully!")
            self.save_last_file_path(self.filename)
        else:
            self.save_file_as()

    def save_file_as(self):
        filepath = filedialog.asksaveasfilename(defaultextension=".py", filetypes=[("Python Files", "*.py"), ("All Files", "*.*")])
        if filepath:
            self.filename = filepath
            self.save_file()

    def load_file(self, filepath):
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as file:
                content = file.read()
            self.editor.delete("1.0", tk.END)
            self.editor.insert("1.0", content.rstrip())
            self.filename = filepath
            self.root.title(f"{os.path.basename(filepath)} - Python Code Editor")
            self.save_last_file_path(filepath)
        except Exception as e:
            messagebox.showerror("Error", f"Could not open file: {e}")

    def populate_sidebar(self, path):
        self.sidebar.delete(*self.sidebar.get_children())
        for root_dir, dirs, files in os.walk(path):
            for d in dirs:
                self.sidebar.insert("", "end", d, text=d, open=False)
            for f in files:
                if f.endswith(".py"):
                    self.sidebar.insert("", "end", f, text=f)
            break

    def open_file_from_sidebar(self, event):
        selected = self.sidebar.selection()
        if selected:
            item = selected[0]
            path = self.sidebar.item(item, "text")
            if os.path.isfile(path):
                self.load_file(path)

    def run_code(self):
        code = self.editor.get("1.0", tk.END)
        with open("temp_run.py", "w", encoding="utf-8") as f:
            f.write(code)
        self.proc = subprocess.Popen(
            [sys.executable, "temp_run.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        threading.Thread(target=self.read_subprocess_output, daemon=True).start()

    def read_subprocess_output(self):
        if not hasattr(self, 'proc') or self.proc is None:
            return
        for line in self.proc.stdout:
            self.console.write(line)
        for line in self.proc.stderr:
            self.console.write(line)

    def stop_code(self):
        if hasattr(self, 'proc') and self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.proc = None
        else:
            messagebox.showinfo("Info", "No code is running.")

    def clear_console(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", tk.END)
        self.console.configure(state="disabled")

    def open_terminal(self):
        # Start a shell subprocess (cmd.exe for Windows)
        if hasattr(self, 'proc') and self.proc and self.proc.poll() is None:
            messagebox.showinfo("Terminal", "Terminal is already running.")
            return
        shell = "cmd.exe" if os.name == "nt" else "/bin/bash"
        self.proc = subprocess.Popen(
            shell,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        self.console.write(f"[Terminal started: {shell}]\n")
        threading.Thread(target=self.read_subprocess_output, daemon=True).start()
        self.terminal_mode = True

    def close_sidebar(self):
        self.main_frame.forget(self.sidebar)

    def open_sidebar(self):
        panes = self.main_frame.panes()
        for pane in panes:
            self.main_frame.forget(pane)
        self.main_frame.add(self.sidebar, width=250)
        self.main_frame.add(self.editor_frame)

    def save_last_file_path(self, path):
        try:
            with open(self.config_file, "w") as f:
                f.write(path)
        except Exception:
            pass

    def load_last_file(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r") as f:
                    path = f.read().strip()
                if path and os.path.exists(path):
                    self.load_file(path)
            except Exception:
                pass

    def show_splash(self):
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = self.root.winfo_x()
        y = self.root.winfo_y()

        splash = tk.Toplevel(self.root)
        splash.overrideredirect(True)
        splash.geometry(f"{width}x{height}+{x}+{y}")

        img = Image.open("aa6k70i3u.png")
        img = img.resize((int(width * 0.5), int(height * 0.4)))
        photo = ImageTk.PhotoImage(img)
        label_img = tk.Label(splash, image=photo, bg="black")
        label_img.image = photo
        label_img.place(relx=0.5, rely=0.4, anchor="center")

        label_text = tk.Label(splash, text="Hamlet", font=("Arial", 40), fg="white", bg="black")
        label_text.place(relx=0.5, rely=0.7, anchor="center")

        splash.config(bg="black")
        self.root.after(2000, splash.destroy)
        splash.wait_window()


    def show_autocomplete(self, event=None):
        if hasattr(self, 'autocomplete_popup') and self.autocomplete_popup:
            self.autocomplete_popup.destroy()
            self.autocomplete_popup = None

        if event and not (event.char.isalnum() or event.char == '_' or event.keysym == "BackSpace"):
            return

        index = self.editor.index(tk.INSERT)
        line, col = map(int, index.split('.'))
        start = f"{line}.{max(col-1, 0)}"
        while True:
            char = self.editor.get(start)
            if not char.isidentifier() or col == 0:
                start = f"{line}.{col}"
                break
            col -= 1
            start = f"{line}.{max(col-1, 0)}"
        word = self.editor.get(start, tk.INSERT)
        if not word:
            return

        matches = [w for w in PYTHON_KEYWORDS if w.startswith(word) and w != word]
        if not matches:
            return

        self.autocomplete_popup = tk.Toplevel(self.editor)
        self.autocomplete_popup.wm_overrideredirect(True)
        self.autocomplete_popup.attributes("-topmost", True)
        x, y, _, h = self.editor.bbox(tk.INSERT)
        abs_x = self.editor.winfo_rootx() + x
        abs_y = self.editor.winfo_rooty() + y + h
        self.autocomplete_popup.geometry(f"+{abs_x}+{abs_y}")

        listbox = tk.Listbox(self.autocomplete_popup, exportselection=False)
        for match in matches:
            listbox.insert(tk.END, match)
        listbox.pack()
        listbox.select_set(0)

        def complete_from_list(event=None):
            selection = listbox.curselection()
            if selection:
                value = listbox.get(selection[0])
                self.insert_autocomplete(value, start, tk.INSERT)
            self.autocomplete_popup.destroy()
            self.autocomplete_popup = None
            self.editor.focus_set()
            return "break"

        listbox.bind("<Return>", complete_from_list)
        listbox.bind("<Tab>", complete_from_list)
        listbox.bind("<Double-Button-1>", complete_from_list)
        listbox.bind("<Escape>", lambda e: self.autocomplete_popup.destroy())

    def editor_key_handler(self, e):
        if hasattr(self, 'autocomplete_popup') and self.autocomplete_popup:
            if e.keysym in ("Up", "Down", "Tab", "Return"):
                return
            self.close_autocomplete_popup()

    def autocomplete_move_up(self, event=None):
        if hasattr(self, 'autocomplete_popup') and self.autocomplete_popup:
            listbox = self.autocomplete_popup.winfo_children()[0]
            idx = listbox.curselection()[0]
            if idx > 0:
                listbox.select_clear(idx)
                listbox.select_set(idx - 1)
                listbox.activate(idx - 1)
            return "break"
        return None

    def autocomplete_move_down(self, event=None):
        if hasattr(self, 'autocomplete_popup') and self.autocomplete_popup:
            listbox = self.autocomplete_popup.winfo_children()[0]
            idx = listbox.curselection()[0]
            if idx < listbox.size() - 1:
                listbox.select_clear(idx)
                listbox.select_set(idx + 1)
                listbox.activate(idx + 1)
            return "break"
        return None

    def close_autocomplete_popup(self):
        if hasattr(self, 'autocomplete_popup') and self.autocomplete_popup:
            self.autocomplete_popup.destroy()
            self.autocomplete_popup = None

    def autocomplete_tab(self, event=None):
        if hasattr(self, 'autocomplete_popup') and self.autocomplete_popup:
            listbox = self.autocomplete_popup.winfo_children()[0]
            selection = listbox.curselection()
            if selection:
                value = listbox.get(selection[0])
                index = self.editor.index(tk.INSERT)
                line, col = map(int, index.split('.'))
                start = f"{line}.{max(col-1, 0)}"
                while True:
                    char = self.editor.get(start)
                    if not char.isidentifier() or col == 0:
                        start = f"{line}.{col}"
                        break
                    col -= 1
                    start = f"{line}.{max(col-1, 0)}"
                self.insert_autocomplete(value, start, tk.INSERT)
            self.close_autocomplete_popup()
            return "break"
        self.editor.insert(tk.INSERT, " " * 4)
        return "break"

    def insert_autocomplete(self, word, start, end, event=None):
        self.editor.delete(start, end)
        self.editor.insert(start, word)
        self.editor.focus_set()

    def show_find_replace(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Find and Replace")
        dialog.geometry("350x120")
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="Find:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        find_entry = tk.Entry(dialog, width=25)
        find_entry.grid(row=0, column=1, padx=5, pady=5)

        tk.Label(dialog, text="Replace:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        replace_entry = tk.Entry(dialog, width=25)
        replace_entry.grid(row=1, column=1, padx=5, pady=5)

        def clear_highlight():
            self.editor.tag_remove("find_highlight", "1.0", tk.END)
            self.editor.tag_remove("sel", "1.0", tk.END)
            dialog.destroy()

        def do_find():
            self.editor.tag_remove("find_highlight", "1.0", tk.END)
            self.editor.tag_remove("sel", "1.0", tk.END)
            target = find_entry.get()
            if not target:
                return
            start = "1.0"
            first_pos = None
            while True:
                pos = self.editor.search(target, start, stopindex=tk.END)
                if not pos:
                    break
                end = f"{pos}+{len(target)}c"
                self.editor.tag_add("find_highlight", pos, end)
                if not first_pos:
                    first_pos = pos
                start = end
            self.editor.tag_configure("find_highlight", background="#ffe066")
            if first_pos:
                self.editor.see(first_pos)
                self.editor.tag_add("sel", first_pos, f"{first_pos}+{len(target)}c")
                self.editor.mark_set(tk.INSERT, first_pos)

        def do_replace():
            target = find_entry.get()
            replacement = replace_entry.get()
            content = self.editor.get("1.0", tk.END)
            new_content = content.replace(target, replacement)
            self.editor.delete("1.0", tk.END)
            self.editor.insert("1.0", new_content)
            self.editor.tag_remove("find_highlight", "1.0", tk.END)

        tk.Button(dialog, text="Find", command=do_find).grid(row=2, column=0, padx=5, pady=10)
        tk.Button(dialog, text="Replace All", command=do_replace).grid(row=2, column=1, padx=5, pady=10)

        dialog.protocol("WM_DELETE_WINDOW", clear_highlight)

    def insert_snippet(self, snippet_type):
        snippets = {
            "main_guard": (
                'if __name__ == "__main__":\n'
                '    main()\n'
            ),
            "function": (
                'def my_function():\n'
                '    """Describe your function."""\n'
                '    pass\n'
            ),
            "class": (
                'class MyClass:\n'
                '    def __init__(self):\n'
                '        pass\n'
            ),
            "for_loop": (
                'for i in range(10):\n'
                '    print(i)\n'
            ),
        }
        snippet = snippets.get(snippet_type, "")
        if snippet:
            self.editor.insert(tk.INSERT, snippet)
            self.editor.focus_set()

    def new_tab(self, filename=None, content=""):
        tab_frame = tk.Frame(self.notebook, bg="#1e1e1e")
        editor = CustomCodeEditor(
            tab_frame,
            language='python',
            highlighter=self.syntax_theme,
            autofocus=True,
            blockcursor=True,
            font=(self.font_family, self.font_size),
            padx=10,
            pady=10,
            insertofftime=0
        )
        linenumbers = LineNumberText(tab_frame, editor)
        linenumbers.pack(side="left", fill="y")
        editor.pack(side="right", fill=tk.BOTH, expand=1)
        linenumbers.textwidget = editor

        self.notebook.add(tab_frame, text=os.path.basename(filename) if filename else "Untitled")
        self.tabs.append({"frame": tab_frame, "editor": editor, "linenumbers": linenumbers, "filename": filename})

        self.notebook.select(tab_frame)

        editor.bind("<MouseWheel>", lambda e: linenumbers.redraw())
        editor.bind("<Button-4>", lambda e: linenumbers.redraw())
        editor.bind("<Button-5>", lambda e: linenumbers.redraw())
        editor.bind("<KeyRelease>", self.on_editor_activity)
        editor.bind("<<Change>>", self.on_editor_activity)
        editor.bind("<KeyRelease>", self.show_autocomplete)
        editor.bind("<Tab>", self.autocomplete_tab)
        editor.bind("<Key>", self.editor_key_handler)

        linenumbers.redraw()

    def get_current_tab(self):
        try:
            for tab in self.tabs:
                if str(tab["frame"]) == self.notebook.select():
                    return tab
        except Exception:
            pass
        return None

    @property
    def linenumbers(self):
        tab = self.get_current_tab()
        return tab["linenumbers"] if tab else None

    @property
    def filename(self):
        tab = self.get_current_tab()
        return tab["filename"] if tab else None

    @filename.setter
    def filename(self, value):
        tab = self.get_current_tab()
        if tab:
            tab["filename"] = value
            tab_title = os.path.basename(value) if value else "Untitled"
            self.notebook.tab(tab["frame"], text=tab_title)

    @property
    def editor(self):
        tab = self.get_current_tab()
        return tab["editor"] if tab else None

    def goto_line(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Goto Line")
        dialog.geometry("200x80")
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="Line number:").pack(pady=5)
        entry = tk.Entry(dialog)
        entry.pack(pady=5)
        entry.focus_set()

        def go():
            try:
                line = int(entry.get())
                if line < 1:
                    raise ValueError
                index = f"{line}.0"
                self.editor.see(index)
                self.editor.mark_set(tk.INSERT, index)
                self.editor.tag_remove("sel", "1.0", tk.END)
                self.editor.tag_add("sel", index, f"{line}.end")
                dialog.destroy()
            except Exception:
                messagebox.showerror("Error", "Invalid line number.")

        tk.Button(dialog, text="Go", command=go).pack(pady=5)
        entry.bind("<Return>", lambda e: go())

    def goto_definition(self):
        # Get the word under the cursor
        index = self.editor.index(tk.INSERT)
        line, col = map(int, index.split('.'))
        start = f"{line}.{col}"
        # Expand left
        while col > 0:
            char = self.editor.get(f"{line}.{col-1}")
            if not (char.isalnum() or char == "_"):
                break
            col -= 1
        word_start = f"{line}.{col}"
        word = self.editor.get(word_start, index)
        # Expand right
        right_col = int(index.split('.')[1])
        while True:
            try:
                char = self.editor.get(f"{line}.{right_col}")
                if not (char.isalnum() or char == "_"):
                    break
                right_col += 1
            except tk.TclError:
                break
        word += self.editor.get(index, f"{line}.{right_col}")

        if not word.strip():
            messagebox.showinfo("Goto Definition", "No word under cursor.")
            return

        # Search for def or class definition
        pattern1 = f"def {word}("
        pattern2 = f"class {word}"
        pos = self.editor.search(pattern1, "1.0", tk.END)
        if not pos:
            pos = self.editor.search(pattern2, "1.0", tk.END)
        if pos:
            self.editor.see(pos)
            self.editor.mark_set(tk.INSERT, pos)
            self.editor.tag_remove("sel", "1.0", tk.END)
            self.editor.tag_add("sel", pos, f"{pos} lineend")
        else:
            messagebox.showinfo("Goto Definition", f"No definition found for '{word}'.")

    def goto_symbol(self):
        import re
        dialog = tk.Toplevel(self.root)
        dialog.title("Go to Symbol")
        dialog.geometry("350x300")
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="Select a symbol:").pack(pady=5)
        listbox = tk.Listbox(dialog, width=40, height=15)
        listbox.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

        content = self.editor.get("1.0", tk.END)
        language = self.get_language()

        # Patterns for different languages
        patterns = {
            'python': re.compile(r'^(def|class)\s+(\w+)', re.MULTILINE),
            'javascript': re.compile(r'^(function|class)\s+(\w+)', re.MULTILINE),
            'java': re.compile(r'^(public|private|protected)?\s*(class|interface|void|[\w<>]+)\s+(\w+)\s*\(', re.MULTILINE),
            'cpp': re.compile(r'^(class|struct|void|[\w:<>]+)\s+(\w+)\s*\(', re.MULTILINE),
            'c': re.compile(r'^(void|[\w_]+)\s+(\w+)\s*\(', re.MULTILINE),
            'html': re.compile(r'^<([a-zA-Z0-9]+)', re.MULTILINE),
            # Add more as needed
        }
        pattern = patterns.get(language, patterns['python'])
        if language == 'java':
            symbols = [(m.group(2), m.group(3), m.start()) for m in pattern.finditer(content)]
        else:
            symbols = [(m.group(1), m.group(2), m.start()) for m in pattern.finditer(content)]

        for kind, name, pos in symbols:
            listbox.insert(tk.END, f"{kind} {name}")

        def goto_selected(event=None):
            idx = listbox.curselection()
            if not idx:
                return
            kind, name, _ = symbols[idx[0]]
            lines = content[:symbols[idx[0]][2]].splitlines()
            line_no = len(lines) + 1
            index = f"{line_no}.0"
            self.editor.see(index)
            self.editor.mark_set(tk.INSERT, index)
            self.editor.tag_remove("sel", "1.0", tk.END)
            self.editor.tag_add("sel", index, f"{line_no}.end")
            dialog.destroy()

        listbox.bind("<Double-Button-1>", goto_selected)
        listbox.bind("<Return>", goto_selected)

    def get_language(self):
        filename = self.filename
        if filename and filename.endswith('.py'):
            return 'python'
        elif filename and filename.endswith('.js'):
            return 'javascript'
        elif filename and filename.endswith('.java'):
            return 'java'
        elif filename and filename.endswith('.cpp'):
            return 'cpp'
        elif filename and filename.endswith('.c'):
            return 'c'
        elif filename and filename.endswith('.html'):
            return 'html'
        # Add more as needed
        return 'plain'


def run_code_in_subprocess(code):
    with open("temp_run.py", "w", encoding="utf-8") as f:
        f.write(code)
    proc = subprocess.Popen([sys.executable, "temp_run.py"])
    return proc

def main():
    root = tk.Tk()
    try:
        import sv_ttk
        sv_ttk.set_theme("dark")
    except ImportError:
        style = ttk.Style(root)
        style.theme_use("clam")
    root.iconbitmap("image_2025-05-07_222224239.ico")
    root.state('zoomed')
    app = CodeEditorApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()