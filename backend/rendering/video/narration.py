"""Offline text-to-speech engines (pluggable).

  * SAPIEngine  - Windows built-in voices via System.Speech (no install, fully offline)
  * PiperEngine - Piper neural TTS (optional: PIPER_PATH + a local .onnx voice)
Text is passed through files (never the command line) so nothing is interpreted by a shell.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path
from typing import Optional

from backend.utils.config import get_settings
from backend.utils.logging import get_logger

log = get_logger(__name__)
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class TTSError(Exception):
    pass


class TTSEngine(ABC):
    name = ""

    @abstractmethod
    def voices(self) -> list[str]: ...

    @abstractmethod
    def synthesize_many(self, items: list[tuple[str, Path]], voice: str = "", speed: float = 1.0) -> None:
        """Write one WAV per (text, path)."""


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


# ------------------------------------------------------------------ Windows SAPI
_SAPI_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$jobs = Get-Content -Raw -Encoding UTF8 -Path $args[0] | ConvertFrom-Json
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($jobs.voice) { $s.SelectVoice($jobs.voice) }
$s.Rate = [int]$jobs.rate
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(22050, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
foreach ($j in $jobs.items) {
  $text = Get-Content -Raw -Encoding UTF8 -Path $j.text
  $s.SetOutputToWaveFile($j.out, $fmt)
  $s.Speak($text)
  $s.SetOutputToNull()
}
$s.Dispose()
"""


def _powershell() -> Optional[str]:
    return shutil.which("powershell") or shutil.which("pwsh")


class SAPIEngine(TTSEngine):
    name = "sapi"

    def __init__(self):
        if sys.platform != "win32" or not _powershell():
            raise TTSError("Windows speech is not available on this system")

    @staticmethod
    @lru_cache(maxsize=1)
    def _voices() -> tuple[str, ...]:
        cmd = ("Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer)"
               ".GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo.Name }")
        try:
            r = subprocess.run([_powershell(), "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True,
                               text=True, timeout=60, creationflags=NO_WINDOW)
            return tuple(v.strip() for v in r.stdout.splitlines() if v.strip())
        except Exception:
            return ()

    def voices(self) -> list[str]:
        return list(self._voices())

    def synthesize_many(self, items: list[tuple[str, Path]], voice: str = "", speed: float = 1.0) -> None:
        if not items:
            return
        if voice and voice not in self.voices():
            voice = ""
        rate = max(-10, min(10, round(math.log2(max(0.5, min(2.0, speed))) * 10)))
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            jobs = {"voice": voice, "rate": rate, "items": []}
            for i, (text, out) in enumerate(items):
                tf = tdp / f"t{i}.txt"
                tf.write_text(text, encoding="utf-8")
                out.parent.mkdir(parents=True, exist_ok=True)
                jobs["items"].append({"text": str(tf), "out": str(out.resolve())})
            (tdp / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
            (tdp / "tts.ps1").write_text(_SAPI_SCRIPT, encoding="utf-8-sig")
            r = subprocess.run([_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                str(tdp / "tts.ps1"), str(tdp / "jobs.json")], capture_output=True, text=True,
                               timeout=120 + 30 * len(items), creationflags=NO_WINDOW)
            if r.returncode != 0:
                raise TTSError("Windows speech synthesis failed")
        for _, out in items:
            if not out.exists() or out.stat().st_size < 100:
                raise TTSError("Windows speech produced no audio")


# ------------------------------------------------------------------ Piper
class PiperEngine(TTSEngine):
    name = "piper"

    def __init__(self):
        s = get_settings()
        self.binary = s.piper_path or shutil.which("piper") or ""
        if not self.binary or not Path(self.binary).exists() and not shutil.which(self.binary):
            raise TTSError("Piper is not installed")
        self.voice_dir = s.models_path / "tts"
        self.default_voice = s.piper_voice

    def voices(self) -> list[str]:
        found = [p.stem for p in self.voice_dir.glob("*.onnx")] if self.voice_dir.exists() else []
        if self.default_voice:
            found.insert(0, Path(self.default_voice).stem)
        return list(dict.fromkeys(found))

    def _model(self, voice: str) -> Path:
        if voice and (self.voice_dir / f"{voice}.onnx").exists():
            return self.voice_dir / f"{voice}.onnx"
        if self.default_voice and Path(self.default_voice).exists():
            return Path(self.default_voice)
        onnx = sorted(self.voice_dir.glob("*.onnx")) if self.voice_dir.exists() else []
        if not onnx:
            raise TTSError("No Piper voice model found in models/tts/")
        return onnx[0]

    def synthesize_many(self, items: list[tuple[str, Path]], voice: str = "", speed: float = 1.0) -> None:
        model = self._model(voice)
        for text, out in items:
            out.parent.mkdir(parents=True, exist_ok=True)
            r = subprocess.run([self.binary, "--model", str(model), "--output_file", str(out),
                                "--length_scale", f"{1 / max(0.5, min(2.0, speed)):.2f}"],
                               input=text, capture_output=True, text=True, timeout=300, creationflags=NO_WINDOW)
            if r.returncode != 0 or not out.exists():
                raise TTSError("Piper synthesis failed")


# ------------------------------------------------------------------ selection
def available_engines() -> dict[str, TTSEngine]:
    out: dict[str, TTSEngine] = {}
    for cls in (PiperEngine, SAPIEngine):
        try:
            out[cls.name] = cls()
        except TTSError:
            continue
    return out


def get_tts_engine(preference: str = "auto") -> Optional[TTSEngine]:
    if preference == "none":
        return None
    engines = available_engines()
    if preference in engines:
        return engines[preference]
    if preference == "auto" and engines:
        return engines.get("piper") or engines.get("sapi")
    return None


def tts_status() -> dict:
    engines = available_engines()
    return {"engines": {n: e.voices() for n, e in engines.items()}, "available": bool(engines)}


def silence_wav(path: Path, seconds: float, rate: int = 22050) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return path


__all__ = ["TTSEngine", "TTSError", "get_tts_engine", "tts_status", "wav_duration", "silence_wav", "os"]
