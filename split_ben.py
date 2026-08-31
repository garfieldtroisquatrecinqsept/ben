"""Decoupe un MP3 en clips individuels via la detection de silence de ffmpeg.

Usage :
    python split_ben.py                      # utilise les reglages par defaut
    python split_ben.py --noise -45 --gap 0.4 --min-dur 0.15
Les clips sont ecrits dans sounds/ sous la forme ben_01.mp3, ben_02.mp3, ...
Renomme-les ensuite comme tu veux : le bot lit le nom du fichier comme nom du son.
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_SRC = next(iter(sorted(ROOT.glob("*.mp3"))), None)
OUT_DIR = ROOT / "sounds"


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def duration_of(src: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", str(src)]).stdout.strip()
    return float(out)


def detect_segments(src: Path, noise_db: float, gap: float, min_dur: float, pad: float):
    """Retourne une liste de (start, end) des passages non silencieux, fusionnes."""
    total = duration_of(src)
    proc = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src),
                "-af", f"silencedetect=noise={noise_db}dB:d=0.15", "-f", "null", "-"])
    log = proc.stderr

    silences = []
    start = None
    for m in re.finditer(r"silence_(start|end):\s*(-?[\d.]+)", log):
        kind, value = m.group(1), float(m.group(2))
        if kind == "start":
            start = value
        elif start is not None:
            silences.append((start, value))
            start = None
    if start is not None:
        silences.append((start, total))

    segments = []
    cursor = 0.0
    for s_start, s_end in silences:
        if s_start > cursor:
            segments.append([cursor, s_start])
        cursor = s_end
    if cursor < total:
        segments.append([cursor, total])

    merged = []
    for seg in segments:
        if merged and seg[0] - merged[-1][1] < gap:
            merged[-1][1] = seg[1]
        else:
            merged.append(seg)

    keep = []
    for seg_start, seg_end in merged:
        if seg_end - seg_start < min_dur:
            continue
        keep.append((max(0.0, seg_start - pad), min(total, seg_end + pad)))
    return keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC, help="MP3 source")
    ap.add_argument("--noise", type=float, default=-40, help="seuil de silence en dB")
    ap.add_argument("--gap", type=float, default=0.5, help="blanc mini entre deux sons (s)")
    ap.add_argument("--min-dur", type=float, default=0.15, help="duree mini d'un clip (s)")
    ap.add_argument("--pad", type=float, default=0.06, help="marge ajoutee autour d'un clip (s)")
    ap.add_argument("--dry-run", action="store_true", help="affiche le decoupage sans ecrire")
    args = ap.parse_args()

    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg est introuvable dans le PATH.")
    if args.src is None or not args.src.exists():
        sys.exit("Aucun MP3 source trouve.")

    segments = detect_segments(args.src, args.noise, args.gap, args.min_dur, args.pad)
    if not segments:
        sys.exit("Aucun son detecte : baisse --noise ou --min-dur.")

    print(f"{len(segments)} son(s) detecte(s) dans {args.src.name}")
    if not args.dry_run:
        OUT_DIR.mkdir(exist_ok=True)
        for old in OUT_DIR.glob("ben_*.mp3"):
            old.unlink()

    for i, (start, end) in enumerate(segments, 1):
        dest = OUT_DIR / f"ben_{i:02d}.mp3"
        print(f"  {dest.name:>12}  {start:6.2f}s -> {end:6.2f}s  ({end - start:.2f}s)")
        if args.dry_run:
            continue
        proc = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(args.src),
                    "-af", f"afade=t=in:st=0:d=0.02,afade=t=out:st={max(0, end - start - 0.03):.3f}:d=0.03,"
                           "loudnorm=I=-16:TP=-1.5:LRA=11",
                    "-ar", "48000", "-ac", "2", "-b:a", "192k", str(dest)])
        if proc.returncode != 0:
            print(proc.stderr, file=sys.stderr)
            sys.exit(f"Echec du decoupage sur {dest.name}")

    if not args.dry_run:
        print(f"\nEcrit dans {OUT_DIR}")


if __name__ == "__main__":
    main()
