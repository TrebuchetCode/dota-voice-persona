#!/bin/bash

# Ensure script stops on errors
set -e

PYTHON_BIN=""
for candidate in /opt/homebrew/bin/python3.10 /opt/homebrew/bin/python3.11 \
                 /usr/local/bin/python3.10 /usr/local/bin/python3.11 \
                 python3.10 python3.11; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v "$candidate")"
        break
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "No Homebrew Python 3.10/3.11 found. Installing python@3.10 via Homebrew..."
    if ! command -v brew >/dev/null 2>&1; then
        echo "❌ Homebrew is not installed. Install it from https://brew.sh and re-run."
        exit 1
    fi
    brew install python@3.10
    PYTHON_BIN="$(brew --prefix)/bin/python3.10"
fi

PYTHON_VER=$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Using Python $PYTHON_VER at $PYTHON_BIN"


if ! "$PYTHON_BIN" -c 'import _tkinter' >/dev/null 2>&1; then
    if [[ "$PYTHON_BIN" == /opt/homebrew/* || "$PYTHON_BIN" == /usr/local/* ]]; then
        if command -v brew >/dev/null 2>&1; then
            echo "Installing python-tk@$PYTHON_VER for Tk support..."
            brew install "python-tk@$PYTHON_VER"
        else
            echo "⚠️ _tkinter is missing and Homebrew is unavailable to install python-tk@$PYTHON_VER."
        fi
    else
        echo "⚠️ _tkinter is missing for $PYTHON_BIN — install Tk support manually."
    fi
fi

echo "[1/4] Creating Venv..."
if [ -d "venv" ]; then
    EXISTING_VER=$(venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "")
    if [ "$EXISTING_VER" != "$PYTHON_VER" ]; then
        echo "Existing venv uses Python '$EXISTING_VER' — rebuilding with $PYTHON_VER..."
        rm -rf venv
    fi
fi
if [ ! -d "venv" ]; then
    "$PYTHON_BIN" -m venv venv
fi

# Activate venv
source venv/bin/activate

echo "[2/4] Installing Pinned Dependencies..."
# Ensure pip is up to date but below 24.1 to avoid common build issues
pip install --upgrade "pip<24.1"

# Pinning versions known to be compatible with RVC
pip install "numpy<1.26" "scipy==1.11.1" "librosa==0.10.0"

echo "[3/4] Installing AI Components..."
# torch needs a separate index, and rvc-python needs --no-deps; everything else merges.
pip install torch==2.1.1 torchaudio==2.1.1 --index-url https://download.pytorch.org/whl/cpu
pip install requests urllib3 packaging "setuptools<81" darkdetect typing-extensions av tqdm colorama \
    faiss-cpu==1.7.3 soundfile pyworld==0.3.5 praat-parselmouth ffmpeg-python torchcrepe \
    fairseq==0.12.2 omegaconf==2.0.6 pydantic==2.5.2 tensorboardX \
    fastapi uvicorn python-multipart flet httpx pygame

# Replace pyworld's deprecated pkg_resources version lookup with importlib.metadata.
"$PYTHON_BIN" -c "import pathlib;p=pathlib.Path('venv/lib/python${PYTHON_VER}/site-packages/pyworld/__init__.py');p.exists() and p.write_text(p.read_text().replace('import pkg_resources','import importlib.metadata').replace(\"pkg_resources.get_distribution('pyworld').version\",\"importlib.metadata.version('pyworld')\"))"

echo "[4/4] Installing RVC Controller..."
pip install --no-deps rvc-python==0.1.5

echo "[5/5] Downloading engine assets..."
# Hero models are downloaded inside the app on demand. This step only fetches
# the always-required hubert + rmvpe engine files (~250MB).
python -c "import downloader; downloader.ensure_base_assets(on_progress=downloader._cli_progress); print()"

echo "✅ Setup finished. Run the app with:  source venv/bin/activate && python app.py"