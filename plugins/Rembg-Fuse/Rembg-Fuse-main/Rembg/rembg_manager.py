"""
RemBG Setup Manager
A GUI application to manage RemBG installation and model downloads.

Author: Akascape
Version: 1.1
License: MIT License - Copyright (c) 2026 Akascape
"""

# importing built-in libraries
import os
import sys
import subprocess
import threading
import io 
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import tkinter.font as tkfont 
from pathlib import Path

try:
    from PIL import Image, ImageTk
except ImportError:
    print("Restart the application after installing RemBG to use the testing utility.")

# List of ALL rembg models (name, size in MB, identifier) 
MODELS = [
    ("u2net", 168, "u2net"),
    ("u2netp", 4, "u2netp"),
    ("u2net_human_seg", 168, "u2net_human_seg"),
    ("u2net_cloth_seg", 168, "u2net_cloth_seg"),
    ("isnet-general-use", 170, "isnet-general-use"),
    ("isnet-anime", 168, "isnet-anime"),
    ("silueta", 43, "silueta"),
    ("sam", 400, "sam_vit_b_01ec64.decoder"),
    ("birefnet-general", 928, "birefnet-general"),
    ("birefnet-general-lite", 214, "birefnet-general-lite"),
    ("birefnet-portrait", 928, "birefnet-portrait"),
    ("ben2-base", 213, "ben2-base"),
]

def is_rembg_installed():
    try:
        import rembg # Check if rembg is installed
        return True
    except ImportError:
        return False

def install_rembg(option, callback):
    def run():
        pip_cmd = [sys.executable, "-m", "pip", "install"]
        
        # --- MODIFIED LOGIC START ---
        if option == "CPU":
            pip_cmd += ["rembg[cpu]"]
        elif option == "GPU":
            pip_cmd += ["rembg[gpu]"]
        elif option == "ROCm":
            pip_cmd += ["rembg[rocm]"]
        else:
            pip_cmd += ["rembg"]

        # --- MODIFIED LOGIC END ---
        try:
            proc = subprocess.Popen(pip_cmd)
            proc.wait()
            callback(proc.returncode)
        except Exception:
            callback(False)

    threading.Thread(target=run).start()

def download_model(model_name, done_callback, self):
    """
    Triggers model download using the rembg library's internal functions.
    This is more robust than using subprocess.
    """
    def run():
        try:
            import rembg
            print(f"Attempting to download model: {model_name}...")
            self.is_installing = True 
            rembg.new_session(model_name)
            print(f"Successfully downloaded or verified model: {model_name}")
            done_callback(True)
            self.is_installing = False  
            messagebox.showinfo("Download Complete", f"Model '{model_name}' downloaded successfully.")
        except Exception as e:
            print(f"Failed to download model '{model_name}': {e}")
            done_callback(False)
            self.is_installing = False 
            messagebox.showerror("Download Failed", f"Failed to download model '{model_name}'. Please try again.")

    threading.Thread(target=run, daemon=True).start()

def check_downloaded_models():
    """Check which models are actually downloaded and save them to models.txt"""
    downloaded = set()
    models_txt_path = Path(__file__).parent / "models.txt"

    try:
        import rembg

        # Get the user's home directory
        home_dir = Path.home()
        models_dir = home_dir / ".u2net"

        # Check if the models directory exists
        if models_dir.exists() and models_dir.is_dir():
            # Get all files in the models directory
            model_files = list(models_dir.iterdir())

            # Check each model from our MODELS list
            for model_name, _, model_id in MODELS:
                for file_path in model_files:
                    if ((model_id == file_path.stem) and
                        file_path.suffix in ['.pth', '.onnx'] and
                        file_path.is_file()):
                        downloaded.add(model_name)
                        break

        # Save the downloaded model names to models.txt (one per line)
        with open(models_txt_path, "w", encoding="utf-8") as f:
            for name in sorted(downloaded):
                f.write(f"{name}\n")

    except ImportError:
        pass
    except Exception as e:
        print(f"Error checking downloaded models: {e}")
        pass

    return downloaded

class RemBGSetupApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RemBG Setup Manager")
        self.geometry("800x600")
        self.resizable(True, True)
        self.minsize(700, 500)
        
        default_font = tkfont.nametofont("TkDefaultFont")
        self.font_family = default_font.actual()["family"]

        # Dark theme colors
        self.colors = {
            'bg_primary': '#1e1e1e',      # Main background
            'bg_secondary': '#2d2d2d',    # Card/frame background
            'bg_tertiary': '#404040',      # Slightly lighter elements
            'text_primary': '#ffffff',    # Main text
            'text_secondary': '#b3b3b3',  # Secondary text
            'text_disabled': '#666666',   # Disabled text
            'accent': '#007acc',          # Accent blue
            'accent_hover': '#1e90ff',    # Lighter blue for hover
            'success': '#4caf50',         # Success green
            'warning': '#ff9800',         # Warning orange
            'error': '#f44336',           # Error red
            'border': '#555555'           # Border color
        }
        
        # Configure main window
        self.configure(bg=self.colors['bg_primary'])
        
        # Configure ttk styles for dark theme
        self.setup_dark_theme()
        
        self.rembg_installed = is_rembg_installed()
        self.selected_models = {}
        self.progressbars = {}
        self.downloaded_models = check_downloaded_models()
        
        self.is_installing = False

        self.input_image_path = None
        self.processed_image_data = None # Will store the output image bytes
        self.tk_input_image = None
        self.tk_output_image = None
        
        self.center_window()
        
        self.create_model_page()

        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_closing(self):
        """Handle the window close event, confirming if an install is running."""
        if self.is_installing:
            if messagebox.askyesno("Exit Confirmation", "An installation is in progress. Are you sure you want to exit?"):
                self.destroy()
        else:
            self.destroy()
            
    def setup_dark_theme(self):
        # Configure styles for dark theme
        style = ttk.Style()
        style.theme_use('alt')
        
        self.option_add('*TCombobox*Listbox.background', self.colors['bg_tertiary'])
        self.option_add('*TCombobox*Listbox.foreground', self.colors['text_primary'])
        self.option_add('*TCombobox*Listbox.selectBackground', self.colors['accent'])
        self.option_add('*TCombobox*Listbox.selectForeground', self.colors['text_primary'])
        
        style.configure('Dark.TFrame',
                        background=self.colors['bg_secondary'],
                        borderwidth=1,
                        relief='solid')
        
        style.configure('Dark2.TFrame',
                        background=self.colors['bg_primary'],
                        borderwidth=0,
                        relief='flat')
        
        style.configure('Main.TFrame',
                        background=self.colors['bg_primary'])
        
        style.configure('Borderless.TFrame',
                        background=self.colors['bg_secondary'],
                        borderwidth=0,
                        highlightthickness=0,
                        relief='flat')
        
        style.configure('Title.TLabel',
                        background=self.colors['bg_secondary'],
                        foreground=self.colors['text_primary'],
                        font=(self.font_family, 18, 'bold'))
        
        style.configure('Subtitle.TLabel',
                        background=self.colors['bg_secondary'],
                        foreground=self.colors['text_secondary'],
                        font=(self.font_family, 12))
        
        style.configure('Info.TLabel',
                        background=self.colors['bg_secondary'],
                        foreground=self.colors['text_secondary'],
                        font=(self.font_family, 10))
        
        style.configure('Success.TLabel',
                        background=self.colors['bg_secondary'],
                        foreground=self.colors['success'],
                        font=(self.font_family, 14, 'bold'))
        
        style.configure('Warning.TLabel',
                        background=self.colors['bg_secondary'],
                        foreground=self.colors['warning'],
                        font=(self.font_family, 10))
        
        style.configure('Error.TLabel',
                        background=self.colors['bg_secondary'],
                        foreground=self.colors['error'],
                        font=(self.font_family, 10))
        
        style.configure('Action.TButton',
                          background=self.colors['accent'],
                          foreground='white',
                          focuscolor=self.colors['accent'], 
                          font=(self.font_family, 10, 'bold'),
                          padding=(20, 8),
                          borderwidth=0)
        
        style.map('Action.TButton',
                  background=[('active', self.colors['accent_hover']),
                              ('pressed', '#005999')], relief=[('pressed', 'flat')])
        
        style.configure('Secondary.TButton',
                        background=self.colors['bg_tertiary'],
                        foreground=self.colors['text_primary'],
                        font=(self.font_family, 9),
                        focuscolor=self.colors['accent'],
                        padding=(10, 5),
                        borderwidth=1,
                        relief='flat')
        
        style.map('Secondary.TButton',
                  background=[('active', self.colors['accent_hover']),
                              ('pressed', '#005999')], relief=[('pressed', 'flat')])
        
        style.configure('Dark.TRadiobutton',
                        background=self.colors['bg_secondary'],
                        foreground=self.colors['text_primary'],
                        font=(self.font_family, 10),
                        focuscolor='none')
        
        style.configure('Dark.TCheckbutton',
                        background=self.colors['bg_secondary'],
                        foreground=self.colors['text_primary'],
                        font=(self.font_family, 11, 'bold'),
                        focuscolor='none')

        style.configure('TCombobox', 
                        selectbackground=self.colors['bg_tertiary'],
                        selectforeground=self.colors['text_primary'],
                        fieldbackground=self.colors['bg_tertiary'],
                        background=self.colors['bg_tertiary'],
                        foreground=self.colors['text_primary'],
                        arrowcolor=self.colors['text_primary'],
                        borderwidth=1,
                        padding=5)
        style.map('TCombobox',
                  fieldbackground=[('readonly', self.colors['bg_tertiary'])],
                  selectbackground=[('readonly', self.colors['bg_tertiary'])],
                  foreground=[('readonly', self.colors['text_primary'])])
        
        style.configure('Dark.Horizontal.TProgressbar',
                        background=self.colors['accent'],
                        troughcolor=self.colors['bg_tertiary'],
                        borderwidth=0,
                        lightcolor=self.colors['accent'],
                        darkcolor=self.colors['accent'])
        
        style.configure('Dark.Vertical.TScrollbar',
                          background=self.colors['border'],        
                          troughcolor=self.colors['bg_tertiary'],   
                          borderwidth=0,
                          relief='flat')
        
        style.map('Dark.TCombobox',
                  fieldbackground=[('readonly', self.colors['bg_tertiary'])],
                  selectbackground=[('readonly', self.colors['bg_tertiary'])],
                  foreground=[('readonly', self.colors['text_primary'])])
        
        style.map('Dark.Vertical.TScrollbar',
                  background=[('active', '#6e6e6e')]) 
        
    def center_window(self):
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(width, height)

    # --------------------------------------------------------------------
    # MODEL MANAGEMENT UTILITY
    # --------------------------------------------------------------------

    def create_model_page(self):
        for widget in self.winfo_children():
            widget.destroy()
        
        self.geometry("800x600")
        self.minsize(700, 500)
        
        # Main container
        main_frame = ttk.Frame(self, style='Main.TFrame')
        main_frame.pack(expand=True, fill="both", padx=30, pady=30)

        # Header section
        header_frame = ttk.Frame(main_frame, style='Dark.TFrame')
        header_frame.pack(fill="x", pady=(0, 30))
        
        title_label = ttk.Label(header_frame, text="🎨 RemBG Setup Manager", 
                                style='Title.TLabel')
        title_label.pack(pady=(20, 10))
        
        subtitle_label = ttk.Label(header_frame, 
                                     text="by Akascape | v1.1",
                                     style='Subtitle.TLabel')
        subtitle_label.pack(pady=(0, 20))
        
        # Content area
        content_frame = ttk.Frame(main_frame, style='Dark.TFrame')
        content_frame.pack(expand=True, fill="both")
        
        if self.rembg_installed:
            
            status_frame = ttk.Frame(content_frame, style='Dark.TFrame')
            status_frame.pack(expand=True, fill="both", padx=40, pady=40)
        
            uninstall_btn = tk.Button(status_frame, text="🗑️", justify="right",
                                    bg=self.colors['bg_secondary'],
                                    font=(self.font_family, 10),
                                    fg='white',
                                    activebackground=self.colors['bg_secondary'],
                                    activeforeground='white',
                                    width=4,
                                    bd=0, 
                                    cursor="hand2",
                                    command=self.confirm_uninstall)
            uninstall_btn.place(relx=1.0, y=5, x=-1, anchor="ne")

            success_label = tk.Label(status_frame, text="✅", 
                                     font=(self.font_family, 24),
                                     bg=self.colors['bg_secondary'],
                                     fg=self.colors['text_primary'])
            success_label.pack(pady=(40, 20))
            
            installed_label = ttk.Label(status_frame, 
                                        text="RemBG is installed!",
                                        style='Success.TLabel')
            installed_label.pack(pady=(0, 10))
            
            info_label = ttk.Label(status_frame, 
                                   text="You can now manage your RemBG models or test the tool",
                                   style='Subtitle.TLabel')
            info_label.pack(pady=(0, 40))
            
            action_buttons_frame = ttk.Frame(status_frame, style='Dark.TFrame')
            action_buttons_frame.pack(pady=20)

            manage_btn = ttk.Button(action_buttons_frame, 
                                    text="Manage Rembg Models 📦",
                                    command=self.create_second_page,
                                    style='Action.TButton')
            manage_btn.pack(side="left", padx=5)

            test_btn = ttk.Button(action_buttons_frame, 
                                  text="Test Rembg 🧪",
                                  command=self.create_test_page,
                                  style='Action.TButton')
            test_btn.pack(side="left", padx=5)

        else:
            install_frame = ttk.Frame(content_frame, style='Dark.TFrame')
            install_frame.pack(expand=True, fill="both", padx=20, pady=20)

            header_container = tk.Frame(install_frame, bg=self.colors['bg_secondary'])
            header_container.pack(fill="x", pady=(20, 30), padx=5)
            
            install_icon = tk.Label(header_container, text="⚙️", 
                                    font=(self.font_family, 20),
                                    bg=self.colors['bg_secondary'],
                                    fg=self.colors['text_primary'])
            install_icon.pack(pady=(0, 10))
            
            install_title = tk.Label(header_container, 
                                     text="Choose your installation type:",
                                     font=(self.font_family, 14, 'bold'),
                                     bg=self.colors['bg_secondary'],
                                     fg=self.colors['text_primary'])
            install_title.pack(pady=(0, 5))
            
            install_subtitle = tk.Label(header_container, 
                                        text="Select the best option for your system",
                                        font=(self.font_family, 10),
                                        bg=self.colors['bg_secondary'],
                                        fg=self.colors['text_secondary'])
            install_subtitle.pack(pady=(0, 10))
            
            options_container = tk.Frame(install_frame, bg=self.colors['bg_secondary'])
            options_container.pack(fill="both", pady=(0, 5), padx=2, expand=True)
            
            self.install_type = tk.StringVar(value="Standard Installation")
            
            # --- MODIFIED OPTIONS LIST START ---
            options = [
                ("Standard", "💻", "Standard Installation", "Basic installation. Best compatibility."),
                ("CPU", "🔴", "CPU Only", "Optimized for CPU processing - rembg[cpu]"),
                ("GPU", "🚀", "CUDA \nSupport", "GPU acceleration for NVIDIA GPU users - rembg[gpu]"),
                ("ROCm", "⚡", "ROCM \nSupport", "GPU acceleration for AMD Radeon users - rembg[rocm]")
            ]
            # --- MODIFIED OPTIONS LIST END ---
            
            self.option_frames = []
            
            for i, (value, icon, title, description) in enumerate(options):
                # Create option card
                option_card = tk.Frame(options_container, 
                                     bg=self.colors['bg_tertiary'],
                                     relief='solid',
                                     bd=1,
                                     highlightbackground=self.colors['border'])
                option_card.pack(fill="both", pady=5, padx=2, side="left", expand=True)

                inner_frame = tk.Frame(option_card, bg=self.colors['bg_tertiary'])
                inner_frame.pack(fill="both", expand=True, padx=10, pady=15)
                
                top_row = tk.Frame(inner_frame, bg=self.colors['bg_tertiary'])
                top_row.pack(fill="x", anchor='w')
                
                radio = tk.Radiobutton(top_row,
                                       text="",
                                       variable=self.install_type,
                                       value=value,
                                       bg=self.colors['bg_tertiary'],
                                       fg=self.colors['text_primary'],
                                       selectcolor=self.colors['bg_primary'],
                                       activebackground=self.colors['bg_tertiary'],
                                       activeforeground=self.colors['text_primary'],
                                       relief='flat',
                                       command=lambda: self.update_option_selection())
                radio.pack(side="left", padx=(0, 5))
                
                icon_label = tk.Label(top_row, 
                                      text=icon,
                                      font=(self.font_family, 16),
                                      bg=self.colors['bg_tertiary'],
                                      fg=self.colors['text_primary'])
                icon_label.pack(side="left", padx=(0, 5))
                
                title_label = tk.Label(top_row,
                                       text=title,
                                       font=(self.font_family, 10, 'bold'),
                                       bg=self.colors['bg_tertiary'],
                                       fg=self.colors['text_primary'],
                                       wraplength=100, 
                                       justify='left')
                title_label.pack(side="left")
                
                desc_label = tk.Label(inner_frame,
                                      text=description,
                                      font=(self.font_family, 8),
                                      bg=self.colors['bg_tertiary'],
                                      fg=self.colors['text_secondary'],
                                      wraplength=140,  
                                      justify='left')
                desc_label.pack(anchor="w", pady=(8, 0))
                
                self.option_frames.append((option_card, value))
                
                # Make the entire card clickable
                def make_clickable(card, val):
                    def on_click(event):
                        self.install_type.set(val)
                        self.update_option_selection()
                    
                    card.bind("<Button-1>", on_click)
                    inner_frame.bind("<Button-1>", on_click)
                    icon_label.bind("<Button-1>", on_click)
                    title_label.bind("<Button-1>", on_click)
                    desc_label.bind("<Button-1>", on_click)
                
                make_clickable(option_card, value)
            
            self.update_option_selection()
            
            action_frame = tk.Frame(install_frame, bg=self.colors['bg_secondary'])
            action_frame.pack(fill="both", expand=True, padx=5, pady=5)
            
            # Install button
            self.install_btn = ttk.Button(action_frame, 
                                          text="📩 Install RemBG",
                                          command=self.start_install,
                                          style='Action.TButton')
            self.install_btn.pack(fill="x", side="bottom")

    def confirm_uninstall(self):
        """Confirm with the user and uninstall rembg."""
        if messagebox.askyesno("Uninstall RemBG?", "Are you sure you want to uninstall RemBG from this device?"):
            self.uninstall_rembg()

    def uninstall_rembg(self):
        """Uninstalls rembg using pip and closes the app."""
        try:
            # Run pip uninstall command
            # -y flag is used to automatically confirm uninstallation
            subprocess.check_call([sys.executable, "-m", "pip", "uninstall", "rembg", "-y"])
            
            messagebox.showinfo("Uninstall Successful", 
                              "RemBG has been successfully uninstalled.\nThe application will now close.")
            self.destroy() # Close the application
            
        except subprocess.CalledProcessError as e:
            messagebox.showerror("Uninstall Failed", f"Failed to uninstall RemBG.\nError: {e}")
        except Exception as e:
             messagebox.showerror("Error", f"An unexpected error occurred: {e}")

    def update_option_selection(self):
        """Update visual feedback for selected option"""
        selected_value = self.install_type.get()
        
        for option_card, value in self.option_frames:
            if value == selected_value:
                option_card.config(bg=self.colors['accent'], 
                                   highlightbackground=self.colors['accent'])
                self.update_frame_colors(option_card, self.colors['accent'], '#ffffff')
            else:
                option_card.config(bg=self.colors['bg_tertiary'],
                                   highlightbackground=self.colors['border'])
                self.update_frame_colors(option_card, self.colors['bg_tertiary'], self.colors['text_primary'])

    def update_frame_colors(self, parent, bg_color, fg_color):
        """Recursively update colors for all child widgets"""
        try:
            for child in parent.winfo_children():
                if isinstance(child, tk.Frame):
                    child.config(bg=bg_color)
                    self.update_frame_colors(child, bg_color, fg_color)
                elif isinstance(child, (tk.Label, tk.Radiobutton)):
                    child.config(bg=bg_color)
                    if isinstance(child, tk.Label):
                        # Adjust condition for font size 8 (description)
                        if child.cget('font').split()[0] == self.font_family and int(child.cget('font').split()[1]) == 8:  # Description labels
                            child.config(fg=self.colors['text_secondary'] if bg_color == self.colors['bg_tertiary'] else '#e0e0e0')
                        else:
                            child.config(fg=fg_color)
                    elif isinstance(child, tk.Radiobutton):
                        child.config(fg=fg_color, activebackground=bg_color)
        except (tk.TclError, IndexError):
            pass  # Widget might be destroyed or font string format is unexpected

    def start_install(self):
        self.is_installing = True
        self.install_btn.config(state="disabled", text="Installing...")
        install_rembg(self.install_type.get(), self.install_callback)

    def install_callback(self, success):
        self.is_installing = False
        self.install_btn.config(state="normal")
        if is_rembg_installed():
            self.rembg_installed = True
            
            self.create_model_page()
        else:
            self.install_btn.config(text="📩 Install RemBG")
            messagebox.showerror("Installation Failed", "Please try again. Check the logs for more details")

    def create_second_page(self):
        for widget in self.winfo_children():
            widget.destroy()
        
        # Main container
        main_frame = ttk.Frame(self, style='Main.TFrame')
        main_frame.pack(expand=True, fill="both", padx=30, pady=30)
        
        # Header
        header_frame = ttk.Frame(main_frame, style='Dark.TFrame')
        header_frame.pack(fill="x", pady=(0, 20))
        
        title_label = ttk.Label(header_frame, text="📦 Model Management", 
                                style='Title.TLabel')
        title_label.pack(pady=(20, 5))
        
        subtitle_label = ttk.Label(header_frame, 
                                     text="Choose models to download for different use cases",
                                     style='Subtitle.TLabel')
        subtitle_label.pack(pady=(0, 20))
        
        models_container = ttk.Frame(main_frame, style='Dark.TFrame')
        models_container.pack(expand=True, fill="both", padx=10)
        
        canvas_frame = ttk.Frame(models_container, style='Dark.TFrame')
        canvas_frame.pack(fill="both", expand=True)
        
        # Scrollable frame for models
        canvas = tk.Canvas(canvas_frame, 
                           bg=self.colors['bg_secondary'], 
                           highlightthickness=0,
                           bd=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview, style='Dark.Vertical.TScrollbar')
        scrollable_frame = ttk.Frame(canvas, style='Dark.TFrame')
        
        def configure_scroll_region(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas_width = canvas_frame.winfo_width() - scrollbar.winfo_reqwidth()
            canvas.itemconfig(canvas_window, width=canvas_width)
        
        scrollable_frame.bind("<Configure>", configure_scroll_region)
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        self.model_vars = {}
        self.progressbars = {}
        self.model_checkboxes = {}
        
        # Updated model descriptions with ALL models
        model_descriptions = {
            "u2net": "General purpose background removal - most versatile",
            "u2netp": "Lightweight version - faster processing",
            "isnet-general-use": "High accuracy general model - best quality",
            "isnet-anime": "High accuracy segmentation for anime characters",
            "u2net_human_seg": "Optimized for human subjects and portraits",
            "u2net_cloth_seg": "Specialized for clothing and fashion items",
            "silueta": "Ultra-light model - minimal resource usage",
            "sam": "Segment Anything Model - pre-trained model for any use cases",
            "birefnet-general": "BiRefNet general purpose - latest architecture",
            "birefnet-general-lite": "Lightweight BiRefNet for faster processing",
            "birefnet-portrait": "BiRefNet optimized for human portraits",
            "ben2-base": "Confidence Guided Matting (CGM) pipeline"
        }
        
        for i, (name, size, pip_id) in enumerate(MODELS):
            var = tk.BooleanVar()
            self.model_vars[name] = var
            
            # Check if model is downloaded
            is_downloaded = name in self.downloaded_models
            
            bg_color = self.colors['bg_tertiary'] if not is_downloaded else '#2a2a2a'
            model_frame = tk.Frame(scrollable_frame, 
                                   bg=bg_color,
                                   relief='solid', 
                                   bd=1,
                                   highlightbackground=self.colors['border'])
            model_frame.pack(fill="x", pady=8, padx=10)
            
            inner_frame = tk.Frame(model_frame, bg=bg_color)
            inner_frame.pack(fill="both", expand=True, padx=15, pady=15)
            
            top_row = tk.Frame(inner_frame, bg=bg_color)
            top_row.pack(fill="x")
            
            left_frame = tk.Frame(top_row, bg=bg_color)
            left_frame.pack(side="left", fill="x", expand=True)
            
            model_text = f"{name}"
            
            cb = tk.Checkbutton(left_frame,
                                text=model_text,
                                variable=var,
                                bg=bg_color,
                                fg=self.colors['text_disabled'] if is_downloaded else self.colors['text_primary'],
                                selectcolor=self.colors['bg_primary'],
                                activebackground=bg_color,
                                activeforeground=self.colors['text_primary'],
                                font=(self.font_family, 11, 'bold'),
                                relief='flat',
                                bd=0,
                                state='disabled' if is_downloaded else 'normal')
            cb.pack(anchor="w")

            self.model_checkboxes[name] = cb
            
            badge_color = '#666666' if is_downloaded else self.colors['accent']
            size_text = "Downloaded" if is_downloaded else f"{size} MB"

            size_label = tk.Label(top_row,
                                  text=size_text,
                                  font=(self.font_family, 9, 'bold'),
                                  fg='white',
                                  bg=badge_color,
                                  padx=8,
                                  pady=2)
            size_label.pack(side="right")
            
            desc_text = model_descriptions.get(name, "AI model for background removal")
            if is_downloaded:
                cb.select()
            
            desc_label = tk.Label(inner_frame,
                                  text=desc_text,
                                  font=(self.font_family, 9),
                                  fg=self.colors['text_disabled'] if is_downloaded else self.colors['text_secondary'],
                                  bg=bg_color,
                                  wraplength=500,
                                  justify='left')
            desc_label.pack(anchor="w", pady=(8, 8))
            
            pb = ttk.Progressbar(inner_frame, 
                                length=300, 
                                mode="determinate",
                                style='Dark.Horizontal.TProgressbar')
            pb.pack(fill="x", pady=(0, 5))
            
            if is_downloaded:
                pb.config(value=100)
            
            self.progressbars[name] = pb
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        button_frame = ttk.Frame(main_frame, style='Dark2.TFrame')
        button_frame.pack(fill="both", pady=10)
        
        select_frame = ttk.Frame(button_frame, style='Dark2.TFrame')
        select_frame.pack(side="left")
        
        self.select_all_btn = ttk.Button(select_frame, text="Select All", 
                                         command=self.select_all_models,
                                         style='Secondary.TButton')
        self.select_all_btn.pack(side="left", padx=(0, 10))
        
        self.select_none_btn = ttk.Button(select_frame, text="Clear All", 
                                          command=self.select_no_models,
                                          style='Secondary.TButton')
        self.select_none_btn.pack(side="left")
        
        self.open_folder_btn = ttk.Button(button_frame, text="Open Model Folder", 
                                 command=self.open_model_folder,
                                 style='Secondary.TButton')
        self.open_folder_btn.pack(side="left", padx=(10, 0))

        self.download_btn = ttk.Button(button_frame, 
                                       text="⇣ Download Selected Models",
                                       command=self.download_selected_models,
                                       style='Action.TButton')
        self.download_btn.pack(side="right")
        
        self.back_btn = ttk.Button(button_frame, text="← Back", 
                                   command=self.create_model_page,
                                   style='Secondary.TButton')
        self.back_btn.pack(side="right", padx=(0, 10))
        
        def on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
        
        canvas.bind('<Configure>', on_canvas_configure)

    def _toggle_second_page_controls(self, state='normal'):
        """Enable or disable all interactive widgets on the model management page."""

        for btn in [self.select_all_btn, self.select_none_btn, self.open_folder_btn, self.back_btn, self.download_btn]:
            btn.config(state=state)

        for name, cb in self.model_checkboxes.items():
            if name not in self.downloaded_models:
                cb.config(state=state)
                
    def select_all_models(self):
        for name, var in self.model_vars.items():
            if name not in self.downloaded_models:  # Only select non-downloaded models
                var.set(True)
    
    def select_no_models(self):
        for name, var in self.model_vars.items():
            if name not in self.downloaded_models:  # Only clear non-downloaded models
                var.set(False)

    def download_selected_models(self):
        selected = [name for name, var in self.model_vars.items() if var.get() and name not in self.downloaded_models]
        if not selected:
            messagebox.showinfo("No Selection", "Please select one or more models to download.")
            return
        
        self._toggle_second_page_controls(state='disabled')
        self.download_btn.config(text="Downloading...")
        
        self.active_downloads = len(selected)

        for name in selected:
            pb = self.progressbars[name]
            # Set to indeterminate mode for visual feedback
            pb.config(mode="indeterminate")
            pb.start(15) # Speed of animation
            download_model(name, lambda success, n=name: self.download_complete(n, success), self)
    
    def open_model_folder(self):
        home_dir = Path.home()
        models_dir = home_dir / ".u2net"
        
        # Check if the models directory exists
        if models_dir.exists() and models_dir.is_dir():
            try:
                if sys.platform == 'win32':      # Windows
                    os.startfile(models_dir)
                elif sys.platform == 'darwin':   # macOS
                    subprocess.run(['open', str(models_dir)])
                else:                            # Linux and other POSIX
                    subprocess.run(['xdg-open', str(models_dir)])
            except Exception as e:
                messagebox.showerror("Error", f"Could not open model folder: {e}")

    def download_complete(self, model_name, success):
        self.active_downloads -= 1
        
        pb = self.progressbars[model_name]
        pb.stop()
        pb.config(mode="determinate")
        
        if success:
            pb.config(value=100)
            self.downloaded_models.add(model_name)
        else:
            pb.config(value=0)
            messagebox.showwarning("Download Failed", f"Failed to download model: {model_name}. Please check your internet connection.")

        # When all downloads are finished, re-enable button and refresh the page
        if self.active_downloads == 0:
            messagebox.showinfo("Downloads Finished", "Model downloads are complete.")
            self.create_second_page()
            self.downloaded_models = check_downloaded_models()
            
    # --------------------------------------------------------------------
    # TESTING UTILITY
    # --------------------------------------------------------------------

    def create_test_page(self):
        """Creates the page for testing RemBG functionality."""
        for widget in self.winfo_children():
            widget.destroy()

        self.geometry("950x700") # Resize for better image viewing
        self.minsize(850, 600)

        # Main container
        main_frame = ttk.Frame(self, style='Main.TFrame')
        main_frame.pack(expand=True, fill="both", padx=30, pady=30)
        
        header_frame = ttk.Frame(main_frame, style='Dark.TFrame')
        header_frame.pack(fill="x", pady=(0, 20))
        
        title_label = ttk.Label(header_frame, text="🧪 RemBG Testing Utility", style='Title.TLabel')
        title_label.pack(pady=(20, 5))
        
        subtitle_label = ttk.Label(header_frame, text="Test your downloaded models on an image", style='Subtitle.TLabel')
        subtitle_label.pack(pady=(0, 20))
        
        content_frame = ttk.Frame(main_frame, style='Dark.TFrame')
        content_frame.pack(expand=True, fill="both")
        
        content_frame.columnconfigure(0, weight=1)
        content_frame.rowconfigure(1, weight=1)

        controls_frame = ttk.Frame(content_frame, style='Dark.TFrame')
        controls_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=10)
        
        self.process_btn = ttk.Button(controls_frame, text="Process Image", command=self.start_image_processing, style='Action.TButton')
        self.process_btn.pack(side="right", padx=(5,0))

        self.save_btn = ttk.Button(controls_frame, text="Save Image...", command=self.save_processed_image, style='Secondary.TButton', state="disabled")
        self.save_btn.pack(side="right")
        
        choose_btn = ttk.Button(controls_frame, text="Choose Image...", command=self.select_image_for_test, style='Secondary.TButton')
        choose_btn.pack(side="left", padx=(0, 15))

        model_label = ttk.Label(controls_frame, text="Model:", style='Info.TLabel')
        model_label.pack(side="left", padx=(0, 5))
        
        self.test_model_var = tk.StringVar()
        self.model_combo = ttk.Combobox(controls_frame, textvariable=self.test_model_var, state="readonly", width=20)
        self.model_combo['values'] = sorted(list(self.downloaded_models), reverse=True)
        if self.model_combo['values']:
            self.model_combo.set(self.model_combo['values'][0])
        self.model_combo.pack(side="left", padx=(0, 15))

        # --- Image Display Area ---
        image_area_frame = ttk.Frame(content_frame, style='Dark.TFrame')
        image_area_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=10)
        image_area_frame.columnconfigure(0, weight=1)
        image_area_frame.columnconfigure(1, weight=1)
        image_area_frame.rowconfigure(1, weight=1)

        # Original Image
        original_label = ttk.Label(image_area_frame, text="Original Image", style='Subtitle.TLabel')
        original_label.grid(row=0, column=0, pady=(0, 5))
        self.original_canvas = tk.Canvas(image_area_frame, bg=self.colors['bg_primary'], bd=0, highlightthickness=0)
        self.original_canvas.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        
        # Processed Image
        processed_label = ttk.Label(image_area_frame, text="Processed Image", style='Subtitle.TLabel')
        processed_label.grid(row=0, column=1, pady=(0, 5))
        self.processed_canvas = tk.Canvas(image_area_frame, bg=self.colors['bg_primary'], bd=0, highlightthickness=0)
        self.processed_canvas.grid(row=1, column=1, sticky="nsew", padx=(10, 0))

        button_frame = ttk.Frame(main_frame, style='Dark2.TFrame')
        button_frame.pack(fill="x", pady=10, side="bottom")

        self.back_btn_test = ttk.Button(button_frame, text="← Back", command=self.create_model_page, style='Secondary.TButton')
        self.back_btn_test.pack(side="left")

    def select_image_for_test(self):
        """Opens a file dialog to select an image for testing."""
        path = filedialog.askopenfilename(
            title="Select an Image",
            filetypes=[("Image Files", "*.png *.jpg *.jpeg *.bmp *.webp"), ("All files", "*.*")]
        )
        if not path:
            return
        
        self.input_image_path = Path(path)
        
        self.processed_canvas.delete("all")
        self.tk_output_image = None
        self.processed_image_data = None
        self.save_btn.config(state="disabled")

        self.display_image_on_canvas(self.original_canvas, self.input_image_path, "input")

    def display_image_on_canvas(self, canvas, image_source, image_type, in_memory=False):
        """Loads, resizes, and displays an image on a given canvas from path or memory."""
        canvas.delete("all")
        
        self.update_idletasks()
        canvas_width = canvas.winfo_width()
        canvas_height = canvas.winfo_height()

        if canvas_width <= 1 or canvas_height <= 1: return

        try:
            image_object = Image.open(image_source) if not in_memory else image_source
            
            with image_object as img:
                img.thumbnail((canvas_width - 10, canvas_height - 10), Image.Resampling.LANCZOS)
                
                # Store reference to avoid garbage collection
                if image_type == "input":
                    self.tk_input_image = ImageTk.PhotoImage(img)
                    canvas.create_image(canvas_width / 2, canvas_height / 2, anchor="center", image=self.tk_input_image)
                else:
                    self.tk_output_image = ImageTk.PhotoImage(img)
                    canvas.create_image(canvas_width / 2, canvas_height / 2, anchor="center", image=self.tk_output_image)

        except Exception as e:
            messagebox.showerror("Image Error", f"Could not load or display image: {e}")

    def start_image_processing(self):
        """Validates inputs and starts the background removal process in a thread."""
        if not self.input_image_path:
            messagebox.showwarning("Input Missing", "Please choose an image first.")
            return
        if not self.test_model_var.get():
            messagebox.showwarning("Input Missing", "Please select a model.")
            return

        self.process_btn.config(state="disabled", text="Processing...")
        self.save_btn.config(state="disabled")
        self.back_btn_test.config(state="disabled")
        
        # Clear previous output
        self.processed_canvas.delete("all")
        self.tk_output_image = None
        self.processed_image_data = None

        model_name = self.test_model_var.get()
        threading.Thread(target=self.run_rembg_processing, args=(model_name,), daemon=True).start()

    def run_rembg_processing(self, model_name):
        """The actual processing logic that runs in a separate thread."""
        try:
            import rembg
            
            with open(self.input_image_path, 'rb') as i:
                input_data = i.read()
                
            session = rembg.new_session(model_name)
            output_data = rembg.remove(input_data, session=session)
            
            self.processed_image_data = output_data
                
            self.after(0, self.processing_finished, True)
            
        except Exception as e:
            print(f"Error during RemBG processing: {e}")
            self.after(0, self.processing_finished, False, str(e))

    def processing_finished(self, success, error_msg=None):
        """Callback to update the GUI after processing is done."""
        self.process_btn.config(state="normal", text="Process Image")
        self.back_btn_test.config(state="normal")

        if success:
            image_stream = io.BytesIO(self.processed_image_data)
            processed_image = Image.open(image_stream)
            self.display_image_on_canvas(self.processed_canvas, processed_image, "output", in_memory=True)
            self.save_btn.config(state="normal")
        else:
            messagebox.showerror("Processing Failed", f"An error occurred: {error_msg}")

    def save_processed_image(self):
        """Opens a 'Save As' dialog and saves the processed image data."""
        if not self.processed_image_data:
            messagebox.showwarning("No Image", "There is no processed image to save.")
            return

        # Create a default filename
        original_path = Path(self.input_image_path)
        default_filename = f"{original_path.stem}_rembg.png"

        save_path = filedialog.asksaveasfilename(
            initialfile=default_filename,
            defaultextension=".png",
            filetypes=[("PNG Image", "*.png"), ("All Files", "*.*")]
        )
        
        if save_path:
            try:
                with open(save_path, 'wb') as f:
                    f.write(self.processed_image_data)
                messagebox.showinfo("Success", f"Image saved successfully to:\n{save_path}")
            except Exception as e:
                messagebox.showerror("Save Error", f"Could not save the image: {e}")

if __name__ == "__main__":
    app = RemBGSetupApp()
    app.focus_force()

    app.mainloop()