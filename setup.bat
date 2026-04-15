@echo off
setlocal

echo [1/3] Creating Venv...
if not exist venv (python -m venv venv)

venv\Scripts\python.exe -m pip install "pip<24.1"

echo [2/3] Installing Required Audio and AI components...
:: torch needs a separate index, and rvc-python needs --no-deps; everything else merges.
venv\Scripts\pip.exe install torch==2.1.1 torchaudio==2.1.1 --index-url https://download.pytorch.org/whl/cpu
venv\Scripts\pip.exe install requests urllib3 packaging "setuptools<81" darkdetect typing-extensions av tqdm colorama faiss-cpu==1.7.3 soundfile librosa==0.11.0 pyworld==0.3.5 praat-parselmouth ffmpeg-python torchcrepe fairseq==0.12.2 omegaconf==2.0.6 pydantic==2.5.2 tensorboardX fastapi uvicorn python-multipart flet httpx pygame
venv\Scripts\pip.exe install --no-deps rvc-python==0.1.5

:: Replace pyworld's deprecated pkg_resources version lookup with importlib.metadata.
venv\Scripts\python.exe -c "import pathlib;p=pathlib.Path('venv/Lib/site-packages/pyworld/__init__.py');p.exists() and p.write_text(p.read_text().replace('import pkg_resources','import importlib.metadata').replace('pkg_resources.get_distribution(\'pyworld\').version','importlib.metadata.version(\'pyworld\')'))"

echo [3/3] Downloading engine assets...
:: Hero models download inside the app on demand; this only fetches hubert + rmvpe.
venv\Scripts\python.exe -c "import downloader; downloader.ensure_base_assets(on_progress=downloader._cli_progress); print()"

echo Setup finished. Run the app with:  venv\Scripts\python.exe app.py
pause