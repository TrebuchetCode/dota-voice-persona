@echo off
echo [1/3] Creating Virtual Environment...
if not exist venv (python -m venv venv)

echo [2/3] Installing RVC Core and UI Tools...
call venv\Scripts\activate
pip install rvc-python==0.1.5 customtkinter librosa

echo [3/3] Installing GPU Drivers (CUDA 11.8 for GTX 1050)...
pip install torch==2.1.1+cu118 torchaudio==2.1.1+cu118 --index-url https://download.pytorch.org/whl/cu118 --force-reinstall

echo ✅ Environment Ready!
pause