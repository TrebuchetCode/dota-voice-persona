@echo off
setlocal

echo [1/3] Creating Venv...
if not exist venv (python -m venv venv)

venv\Scripts\python.exe -m pip install "pip<24.1"

echo [2/3] Installing Required Audio and AI components...
venv\Scripts\pip.exe install torch==2.1.1 torchaudio==2.1.1 --index-url https://download.pytorch.org/whl/cpu
venv\Scripts\pip.exe install requests urllib3 packaging setuptools darkdetect typing-extensions av tqdm colorama
venv\Scripts\pip.exe install faiss-cpu==1.7.3 soundfile librosa==0.11.0 pyworld==0.3.5 praat-parselmouth ffmpeg-python torchcrepe
venv\Scripts\pip.exe install rvc-python==0.1.5 customtkinter --no-deps
venv\Scripts\pip.exe install fairseq==0.12.2 omegaconf==2.0.6 pydantic==2.5.2

echo [3/3] Running Hero Selector...
:: Using the venv python ensures urllib3 is seen
venv\Scripts\python.exe downloader.py

echo ✅ Setup Finished!
pause