import torch

# This tells PyTorch to trust the specific fairseq objects in your assets
try:
    import fairseq
    torch.serialization.add_safe_globals([fairseq.data.dictionary.Dictionary])
except:
    pass

# This is the "Brute Force" safety bypass for PyTorch 2.6+
# It restores the old behavior where it didn't block files
import functools
torch.load = functools.partial(torch.load, weights_only=False)
import customtkinter as ctk
from tkinter import filedialog
import os
import json
import threading
import shutil
from rvc_python.infer import RVCInference

# UI Settings
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class DotaVoiceApp(ctk.CTk):
    def __init__(self):
        
        super().__init__()
        self.title("Dota 2 Voice Persona")
        self.geometry("700x500")

        # 1. Initialize Variables
        self.selected_hero = None
        self.input_path = None
        self.hero_data = {}

        self.patch_assets()

        # 2. Initialize RVC Engine
        try:
            # Just pass the device. The library will look for assets 
            # in the 'rvc_python' folder by default.
            self.rvc = RVCInference(device="cuda:0")
            print("GPU Engine Initialized.")
        except:
            self.rvc = RVCInference(device="cpu")
            print("Falling back to CPU.")

        # 3. Setup UI and Load Heroes
        self.setup_ui()


    def patch_assets(self):
        # This path is where the library is looking
        target_dir = os.path.join("venv", "Lib", "site-packages", "rvc_python", "base_model")
        source_dir = "assets"
        
        if os.path.exists(source_dir):
            if not os.path.exists(target_dir):
                os.makedirs(target_dir)
            
            for file in os.listdir(source_dir):
                target_file = os.path.join(target_dir, file)
                if not os.path.exists(target_file):
                    print(f"Patching {file} into venv...")
                    shutil.copy(os.path.join(source_dir, file), target_file)
    def load_hero_manifest(self):
        """Reads heroes.json and maps names to data blocks"""
        try:
            with open('heroes.json', 'r') as f:
                data = json.load(f)
                # This fixes the TypeError by creating a dictionary mapping
                self.hero_data = {h['name']: h for h in data['heroes']}
                return list(self.hero_data.keys())
        except Exception as e:
            print(f"JSON Error: {e}")
            return []

    def setup_ui(self):
        # Sidebar
        self.sidebar_frame = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, rowspan=4, sticky="nsew")
        
        ctk.CTkLabel(self.sidebar_frame, text="HERO LIST", font=("Bold", 18)).grid(row=0, column=0, pady=20)

        # Load hero buttons from JSON
        hero_names = self.load_hero_manifest()
        for i, name in enumerate(hero_names):
            ctk.CTkButton(self.sidebar_frame, text=name, 
                          command=lambda n=name: self.select_hero(n)).grid(row=i+1, column=0, padx=20, pady=10)

        # Main Area
        self.main_label = ctk.CTkLabel(self, text="Select a Hero to Begin", font=("Arial", 20))
        self.main_label.grid(row=0, column=1, padx=40, pady=30)

        self.upload_btn = ctk.CTkButton(self, text="📁 Upload Voice Clip", command=self.upload_file)
        self.upload_btn.grid(row=1, column=1, pady=10)

        self.status_label = ctk.CTkLabel(self, text="Status: Waiting...", text_color="gray")
        self.status_label.grid(row=2, column=1, pady=10)

        self.cast_btn = ctk.CTkButton(self, text="✨ CAST SPELL", state="disabled", 
                                     command=self.run_inference_thread)
        self.cast_btn.grid(row=3, column=1, pady=30)

    def select_hero(self, name):
        self.selected_hero = name
        self.main_label.configure(text=f"Ready to cast as: {name}")
        self.check_ready()

    def upload_file(self):
        path = filedialog.askopenfilename(filetypes=[("Audio", "*.mp3 *.wav")])
        if path:
            self.input_path = path
            self.status_label.configure(text=f"Loaded: {os.path.basename(path)}", text_color="green")
            self.check_ready()

    def check_ready(self):
        if self.selected_hero and self.input_path:
            self.cast_btn.configure(state="normal", fg_color="#FF4500")

    def run_inference_thread(self):
        threading.Thread(target=self.start_conversion, daemon=True).start()

    def start_conversion(self):
        self.cast_btn.configure(state="disabled")
        self.status_label.configure(text="🔥 Channeling Spell...", text_color="orange")
        
        hero_info = self.hero_data[self.selected_hero]
        hero_id = hero_info['id']
        
        pth_path = f"models/{hero_id}/{hero_id}.pth"
        output_path = f"outputs/{hero_id}_output.wav"

        if not os.path.exists("outputs"): os.makedirs("outputs")

        try:
            # 1. Load the model
            self.rvc.load_model(pth_path)
            
            # 2. Set the conversion parameters directly on the object
            # In rvc-python 0.1.5, these attributes control the next infer_file call
            self.rvc.f0_up_key = hero_info['transpose']
            self.rvc.f0_method = "rmvpe"
            
            # 3. Call the function with only the paths it expects
            self.rvc.infer_file(
                self.input_path, 
                output_path
            )
            
            self.status_label.configure(text=f"✅ Success! Saved in outputs/", text_color="cyan")
        except Exception as e:
            print(f"CRITICAL DEBUG: {e}")
            self.status_label.configure(text="❌ Conversion Failed", text_color="red")
        
        self.cast_btn.configure(state="normal")
if __name__ == "__main__":
    app = DotaVoiceApp()
    app.mainloop()