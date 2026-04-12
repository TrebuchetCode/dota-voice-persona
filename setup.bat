@echo off
setlocal enabledelayedexpansion

echo [1/5] Creating Folder Structure...
if not exist "assets" mkdir "assets"
if not exist "models\lina" mkdir "models\lina"
if not exist "outputs" mkdir "outputs"

echo [2/5] Downloading Base Assets (Hubert/RMVPE)...
:: REPLACE THESE LINKS WITH YOUR ACTUAL DIRECT DOWNLOAD LINKS
:: Use curl.exe specifically to bypass the PowerShell alias
curl.exe -L -o "assets\hubert_base.pt" "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/hubert_base.pt"
curl.exe -L -o "assets\rmvpe.pt" "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/rmvpe.pt"
curl.exe -L -o "assets\rmvpe.onnx" "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/rmvpe.onnx"
echo [3/5] Downloading and Extracting Lina Model...

:: 1. Create the hero folder
if not exist "models\lina" mkdir "models\lina"

:: 2. Download the ZIP (Note the ?download=true for Hugging Face)
curl.exe -L -o "lina_temp.zip" "https://huggingface.co/GoodGuideGreg/LinaRVC/resolve/main/LinaRVC.zip"

:: 3. Extract the ZIP into the lina folder
echo Extracting files...
tar -xf lina_temp.zip -C models\lina

:: 4. Cleanup and Rename
:: We assume the zip contains "Lina.pth" and "Lina.index" 
:: We rename them to match your hero ID ('lina') so the code finds them.
cd models\lina
if exist "LinaRVC.pth" ren "LinaRVC.pth" "lina.pth"
if exist "LinaRVC.index" ren "LinaRVC.index" "lina.index"
cd ..\..
del lina_temp.zip

echo [4/5] Creating Virtual Environment...
if not exist venv (python -m venv venv)

echo [5/5] Installing Dependencies...
call venv\Scripts\activate
pip install rvc-python==0.1.5 customtkinter librosa tensorboardX
pip install torch==2.1.1+cu118 torchaudio==2.1.1+cu118 --index-url https://download.pytorch.org/whl/cu118 --force-reinstall

echo ✅ Setup Complete! You can now run python main.py
pause