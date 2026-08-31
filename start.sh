#!/bin/bash
set -u

MODEL_URL="https://alphacephei.com/vosk/models/vosk-model-small-fr-0.22.zip"
cd "$(dirname "$0")"

echo "--- verification de l'environnement ---"
python3 -c "import sys; print('python', '.'.join(map(str, sys.version_info[:3])))"

if command -v ffmpeg >/dev/null 2>&1; then
    echo "ffmpeg   : $(ffmpeg -version 2>&1 | head -1 | cut -d' ' -f1-3)"
else
    echo "ffmpeg   : ABSENT -> aucun son ne pourra etre joue."
    echo "           Choisis une image qui embarque ffmpeg dans le panel."
fi

python3 - <<'PY'
import discord.opus as o
try:
    o._load_default()
    print("libopus  :", "charge" if o.is_loaded() else "INTROUVABLE")
except Exception as exc:
    print("libopus  : INTROUVABLE ->", exc)
    print("           Sans lui, impossible d'encoder la voix.")
PY

if [ ! -d model ]; then
    if [ "${ECOUTE:-true}" = "false" ]; then
        echo "modele   : ignore (ECOUTE=false)"
    else
        echo "modele   : absent, telechargement (~41 Mo)..."
        if curl -sSL -o model.zip "$MODEL_URL" && unzip -q -o model.zip; then
            mv vosk-model-small-* model && rm -f model.zip
            echo "modele   : installe"
        else
            rm -f model.zip
            echo "modele   : ECHEC du telechargement -> l'ecoute restera desactivee"
        fi
    fi
else
    echo "modele   : present"
fi

echo "--- demarrage ---"
exec python3 bot.py
