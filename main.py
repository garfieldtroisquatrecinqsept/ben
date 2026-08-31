import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / "model"
MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-fr-0.22.zip"
ARCHIVE = ROOT / "model.zip"


def diagnostic():
    print("--- environnement ---")
    print("python   :", ".".join(map(str, sys.version_info[:3])))

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        print("ffmpeg   :", ffmpeg)
    else:
        print("ffmpeg   : ABSENT -> aucun son ne pourra etre joue")

    try:
        import discord.opus as opus

        opus._load_default()
        print("libopus  :", "charge" if opus.is_loaded() else "INTROUVABLE")
    except Exception as exc:
        print("libopus  : INTROUVABLE ->", exc)


def assurer_modele(ecoute=True):
    if MODEL_DIR.is_dir():
        print("modele   : present")
        return True
    if not ecoute:
        print("modele   : ignore (ECOUTE=false)")
        return False
    print("modele   : absent, telechargement (~41 Mo)...")
    try:
        urllib.request.urlretrieve(MODEL_URL, ARCHIVE)
        with zipfile.ZipFile(ARCHIVE) as archive:
            racine = sorted({n.split("/")[0] for n in archive.namelist()})[0]
            archive.extractall(ROOT)
        (ROOT / racine).rename(MODEL_DIR)
        ARCHIVE.unlink(missing_ok=True)
        print("modele   : installe")
        return True
    except Exception as exc:
        ARCHIVE.unlink(missing_ok=True)
        shutil.rmtree(MODEL_DIR, ignore_errors=True)
        print(f"modele   : ECHEC ({type(exc).__name__}: {exc}) -> ecoute desactivee")
        return False


def main():
    diagnostic()
    import bot

    assurer_modele(bot.ECOUTE)
    print("--- demarrage ---")
    if not bot.TOKEN:
        sys.exit("DISCORD_TOKEN manquant : ajoute la variable dans le panel.")
    bot.bot.run(bot.TOKEN)


if __name__ == "__main__":
    main()
