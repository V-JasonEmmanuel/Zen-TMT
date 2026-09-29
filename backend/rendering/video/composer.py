"""Timeline composer: renders a Timeline to MP4 with motion graphics, edited clips, narration,
music and subtitles.

Per clip a normalised segment is produced (same size / fps / codec) and cached by content hash,
so editing one clip re-renders only that clip (and the next one, whose transition depends on it).
Segments are joined losslessly, then the mixed audio track and subtitles are muxed in.
"""
from __future__ import annotations

import hashlib
import json

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PIL import Image, ImageOps

from backend.branding.theme import Theme, hex_to_rgb
from backend.planning.script import distribute
from backend.planning.video_planner import reading_seconds
from backend.rendering.scene import Scene
from backend.rendering.video import audio as A
from backend.rendering.video.ffmpeg import NO_WINDOW, FFmpegError, find_ffmpeg, media_duration
from backend.rendering.video.motion import TRANSITION_SECONDS, intro_frames, slide_frames, transition_frame
from backend.rendering.video.timeline import Clip, Timeline, clip_output_seconds
from backend.schemas import ContentPlan
from backend.utils.logging import get_logger

log = get_logger(__name__)
ENGINE_VERSION = "composer-3"
LEAD, TAIL = 0.4, 0.8


@dataclass
class ComposeResult:
    video: Optional[Path] = None
    subtitles_vtt: Optional[Path] = None
    subtitles_srt: Optional[Path] = None
    duration: float = 0.0
    narrated: bool = False
    clips: list[dict] = field(default_factory=list)  # rendered start/end per clip (for the editor)
    warnings: list[str] = field(default_factory=list)


class FrameWriter:
    """Pipe raw RGB frames into ffmpeg (libx264, yuv420p)."""

    def __init__(self, ff: str, out: Path, w: int, h: int, fps: int, quality: str):
        self.w, self.h, self.n, self.out = w, h, 0, out
        preset, crf = ("ultrafast", "30") if quality == "preview" else ("veryfast", "20")
        self.p = subprocess.Popen([ff, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                                   "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", preset,
                                   "-crf", crf, "-pix_fmt", "yuv420p", "-r", str(fps), str(out)],
                                  stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)

    def write(self, img: Image.Image, repeat: int = 1) -> None:
        if img.size != (self.w, self.h):
            img = img.resize((self.w, self.h), Image.LANCZOS)
        data = img.convert("RGB").tobytes()
        for _ in range(max(0, repeat)):
            self.p.stdin.write(data)
            self.n += 1

    def close(self) -> None:
        self.p.stdin.close()
        err = self.p.stderr.read().decode(errors="ignore")
        if self.p.wait() != 0 or not self.out.exists():
            raise FFmpegError(f"Encoding failed: {err[-200:]}")


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    return ImageOps.fit(img.convert("RGB"), (w, h), Image.LANCZOS)


def _vf(c: Clip, w: int, h: int, fps: int, bg: str) -> str:
    f = []
    if c.crop and (c.crop.w < 0.999 or c.crop.h < 0.999 or c.crop.x > 0 or c.crop.y > 0):
        f.append(f"crop=iw*{c.crop.w:.4f}:ih*{c.crop.h:.4f}:iw*{c.crop.x:.4f}:ih*{c.crop.y:.4f}")
    if abs(c.speed - 1) > 1e-3:
        f.append(f"setpts=PTS/{c.speed:.4f}")
    f += [f"scale={w}:{h}:force_original_aspect_ratio=decrease", f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x{bg.lstrip('#')}",
          "setsar=1", f"fps={fps}", "format=yuv420p"]
    return ",".join(f)


class Composer:
    def __init__(self, tl: Timeline, *, plan: ContentPlan, theme: Theme, scenes: dict[int, Scene], media_path: Callable[[str], Optional[Path]],
                 out_dir: Path, work_dir: Path, ffmpeg_path: str = "", quality: str = "final", tts_engine: str = "auto",
                 on_progress: Optional[Callable[[str], None]] = None):
        self.tl, self.plan, self.theme, self.scenes = tl, plan, theme, scenes
        self.media_path = media_path
        self.out_dir, self.work = out_dir, work_dir
        self.ff = find_ffmpeg(ffmpeg_path)
        self.quality = quality
        self.W, self.H = (tl.width, tl.height) if quality == "final" else (960, 540)
        self.fps = tl.fps
        self.tts_engine = tts_engine
        self.progress = on_progress or (lambda m: None)
        self.cache = work_dir / "video_cache" / quality
        self.cache.mkdir(parents=True, exist_ok=True)
        self.bg = theme.c("background")

    # ------------------------------------------------------------------ narration
    def _narration_texts(self) -> dict[str, str]:
        texts = {c.id: c.narration_text for c in self.tl.clips if c.type in ("slide", "image")}
        if self.tl.narration.script.strip():
            keyed = [c for c in self.tl.clips if c.type in ("slide", "image")]
            keys = [c.slide_number if c.slide_number is not None else 1000 + i for i, c in enumerate(keyed)]
            mapped = distribute(self.tl.narration.script, keys, [float(len(c.narration_text) or 1) for c in keyed])
            for c, k in zip(keyed, keys):
                if k in mapped:
                    texts[c.id] = mapped[k]
        return texts

    def _audio_for_clips(self, texts: dict[str, str]) -> tuple[dict[str, np.ndarray], dict[tuple[str, int], np.ndarray], list[str]]:
        n = self.tl.narration
        per_clip: dict[str, np.ndarray] = {}
        per_seg: dict[tuple[str, int], np.ndarray] = {}
        warnings: list[str] = []
        if n.mode == "none":
            return per_clip, per_seg, warnings
        # user-recorded narration per clip always wins
        for c in self.tl.clips:
            if c.narration_asset_id:
                p = self.media_path(c.narration_asset_id)
                if p:
                    per_clip[c.id] = A.decode(self.ff, p)
        if n.mode == "upload":
            return per_clip, per_seg, warnings
        want = [t for cid, t in texts.items() if t and cid not in per_clip]
        for c in self.tl.clips:
            if c.type == "video" and not c.narration_asset_id:
                want += [s.text for s in c.narration_segments]
        cache = self.work / "audio_cache"
        audio, w = A.tts_batch(want, cache, engine=self.tts_engine, voice=n.voice, speed=n.speed, ff=self.ff)
        warnings += w
        for cid, t in texts.items():
            if cid not in per_clip and t and t.strip() in audio:
                per_clip[cid] = audio[t.strip()]
        for c in self.tl.clips:
            if c.type == "video" and not c.narration_asset_id:
                for i, s in enumerate(c.narration_segments):
                    if s.text.strip() in audio:
                        per_seg[(c.id, i)] = audio[s.text.strip()]
        return per_clip, per_seg, warnings

    # ------------------------------------------------------------------ durations
    def _durations(self, per_clip: dict[str, np.ndarray], whole: Optional[np.ndarray]) -> list[float]:
        durs: list[Optional[float]] = []
        for i, c in enumerate(self.tl.clips):
            trans = TRANSITION_SECONDS.get(c.transition, 0.0) if i > 0 else 0.0
            if c.type in ("intro", "outro"):
                durs.append(c.duration or (2.6 if c.type == "intro" else 3.0))
            elif c.type == "video":
                durs.append((clip_output_seconds(c) or 5.0) + trans)
            elif c.duration > 0:
                durs.append(c.duration + trans)
            elif c.id in per_clip and len(per_clip[c.id]):
                durs.append(max(3.5, LEAD + A.seconds(per_clip[c.id]) + TAIL) + trans)
            elif whole is not None:
                durs.append(None)  # filled below from the uploaded narration length
            else:
                slide = next((s for s in self.plan.slides if s.slide_number == c.slide_number), None)
                durs.append((reading_seconds(slide) if slide else 5.0) + trans)
        if whole is not None and any(d is None for d in durs):
            fixed = sum(d for d in durs if d is not None)
            auto = [i for i, d in enumerate(durs) if d is None]
            remaining = max(len(auto) * 3.5, A.seconds(whole) + 1.0 - fixed)
            weights = [max(1.0, float(len(self.tl.clips[i].narration_text))) for i in auto]
            for i, w in zip(auto, weights):
                durs[i] = max(3.5, remaining * w / sum(weights))
        return [float(d) for d in durs]  # type: ignore[arg-type]

    # ------------------------------------------------------------------ segments
    def _key(self, c: Clip, dur: float, prev_key: str) -> str:
        slide = next((s for s in self.plan.slides if s.slide_number == c.slide_number), None) if c.slide_number else None
        payload = json.dumps({"v": ENGINE_VERSION, "clip": c.model_dump(exclude={"narration_text", "narration_asset_id",
                                                                               "narration_segments", "label", "id"}),
                              "slide": slide.model_dump() if slide else None, "dur": round(dur, 3), "W": self.W, "fps": self.fps,
                              "theme": sorted((k, str(v)) for k, v in vars(self.theme).items() if k != "shapes"),
                              "prev": prev_key if c.transition != "none" else ""}, sort_keys=True, default=str)
        return hashlib.sha1(payload.encode()).hexdigest()[:20]

    def _render_clip(self, c: Clip, dur: float, prev: Optional[Image.Image], out: Path) -> Image.Image:
        W, H, fps = self.W, self.H, self.fps
        total_frames = max(1, int(round(dur * fps)))
        tr = c.transition if prev is not None else "none"
        n_tr = int(round(TRANSITION_SECONDS.get(tr, 0.0) * fps))
        if c.type in ("intro", "outro"):
            fw = FrameWriter(self.ff, out, W, H, fps, self.quality)
            logo = str(self.theme.logo_path) if self.theme.logo_path else None
            last = None
            frames = list(intro_frames(self.theme, W, H, fps, logo))
            if c.type == "outro" and prev is not None:
                n_fade = min(len(frames), int(0.5 * fps))
                for i in range(n_fade):
                    fw.write(Image.blend(prev.resize((W, H)), frames[-1], (i + 1) / n_fade))
                frames = frames[-1:] * 1
            for f in frames[: total_frames]:
                fw.write(f)
                last = f
            fw.write(last, total_frames - fw.n)
            fw.close()
            return last
        if c.type == "slide":
            scene = self.scenes.get(c.slide_number or -1)
            if scene is None:
                raise FFmpegError(f"Slide {c.slide_number} is missing")
            fw = FrameWriter(self.ff, out, W, H, fps, self.quality)
            gen = slide_frames(scene, self.theme, W, fps, c.motion if c.motion != "ken_burns" else "subtle", tr, prev)
            final = None
            try:
                while True:
                    f = next(gen)
                    if fw.n < total_frames:
                        fw.write(f)
            except StopIteration as e:
                final = e.value
            fw.write(final, total_frames - fw.n)
            fw.close()
            return final
        if c.type == "image":
            p = self.media_path(c.asset_id or "")
            if not p:
                raise FFmpegError("Image asset is missing")
            with Image.open(p) as im:
                src = im.convert("RGB")
            if c.crop:
                cw, ch = src.size
                src = src.crop((int(c.crop.x * cw), int(c.crop.y * ch), int((c.crop.x + c.crop.w) * cw), int((c.crop.y + c.crop.h) * ch)))
            big = _cover(src, int(W * 1.08), int(H * 1.08))
            fw = FrameWriter(self.ff, out, W, H, fps, self.quality)
            first = big.resize((W, H), Image.LANCZOS) if c.motion != "ken_burns" else big.crop(self._kb_box(big, 0, W, H)).resize((W, H))
            for i in range(n_tr):
                fw.write(transition_frame(tr, prev.resize((W, H)), first, (i + 1) / n_tr, self.theme))
            last = first
            for i in range(total_frames - fw.n):
                if c.motion == "ken_burns":
                    last = big.crop(self._kb_box(big, i / max(1, total_frames - n_tr), W, H)).resize((W, H), Image.BILINEAR)
                fw.write(last)
            fw.close()
            return last
        # ---- video clip: python transition frames + ffmpeg-processed body, joined losslessly
        src = self.media_path(c.asset_id or "")
        if not src:
            raise FFmpegError("Video asset is missing")
        vf = _vf(c, W, H, fps, self.bg)
        end = c.trim_end if c.trim_end is not None else (c.source_duration or None)
        body = out.with_suffix(".body.mp4")
        args = [self.ff, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{c.trim_start:.3f}"]
        if end:
            args += ["-to", f"{end:.3f}"]
        preset, crf = ("ultrafast", "30") if self.quality == "preview" else ("veryfast", "20")
        args += ["-i", str(src), "-vf", vf, "-an", "-c:v", "libx264", "-preset", preset, "-crf", crf, "-pix_fmt", "yuv420p",
                 "-r", str(fps), str(body)]
        r = subprocess.run(args, capture_output=True, text=True, creationflags=NO_WINDOW)
        if r.returncode != 0 or not body.exists():
            raise FFmpegError(f"Video clip could not be processed: {r.stderr[-200:]}")
        first = self._grab(body, 0.0)
        last = self._grab(body, None)
        parts = []
        if n_tr and prev is not None and first is not None:
            tr_file = out.with_suffix(".tr.mp4")
            fw = FrameWriter(self.ff, tr_file, W, H, fps, self.quality)
            for i in range(n_tr):
                fw.write(transition_frame(tr, prev.resize((W, H)), first, (i + 1) / n_tr, self.theme))
            fw.close()
            parts.append(tr_file)
        parts.append(body)
        self._concat(parts, out)
        for p in parts:
            p.unlink(missing_ok=True)
        return last or first or Image.new("RGB", (W, H), hex_to_rgb(self.bg))

    @staticmethod
    def _kb_box(big: Image.Image, t: float, W: int, H: int) -> tuple[int, int, int, int]:
        """Slow push-in centred on the image (Ken Burns), 8% over the clip."""
        z = 1.08 - 0.08 * min(1.0, max(0.0, t))
        bw, bh = big.width / 1.08 * z, big.height / 1.08 * z
        x0, y0 = (big.width - bw) / 2, (big.height - bh) / 2
        return (int(x0), int(y0), int(x0 + bw), int(y0 + bh))

    def _grab(self, video: Path, at: Optional[float]) -> Optional[Image.Image]:
        tmp = video.with_suffix(".grab.png")
        args = [self.ff, "-hide_banner", "-loglevel", "error", "-y"]
        args += ["-sseof", "-0.12"] if at is None else ["-ss", f"{at:.3f}"]
        args += ["-i", str(video), "-frames:v", "1", str(tmp)]
        subprocess.run(args, capture_output=True, creationflags=NO_WINDOW)
        if not tmp.exists():
            return None
        with Image.open(tmp) as im:
            img = im.convert("RGB")
        tmp.unlink(missing_ok=True)
        return img

    def _concat(self, parts: list[Path], out: Path) -> None:
        lst = out.with_suffix(".txt")
        lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
        r = subprocess.run([self.ff, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                            "-c", "copy", str(out)], capture_output=True, text=True, creationflags=NO_WINDOW)
        lst.unlink(missing_ok=True)
        if r.returncode != 0 or not out.exists():
            raise FFmpegError(f"Joining segments failed: {r.stderr[-200:]}")

    # ------------------------------------------------------------------ main
    def render(self) -> ComposeResult:
        res = ComposeResult()
        if not self.ff:
            res.warnings.append("FFmpeg is not available, so the video was not generated.")
            return res
        if not self.tl.clips:
            res.warnings.append("The timeline is empty.")
            return res
        texts = self._narration_texts()
        per_clip, per_seg, w = self._audio_for_clips(texts)
        res.warnings += w
        whole = None
        n = self.tl.narration
        if n.mode == "upload":
            p = self.media_path(n.asset_id or "")
            if p:
                whole = A.decode(self.ff, p)
            else:
                res.warnings.append("Narration mode is 'upload' but no narration audio was provided.")
        durs = self._durations(per_clip, whole)

        segs, starts, prev, prev_key, t = [], [], None, "", 0.0
        for i, (c, d) in enumerate(zip(self.tl.clips, durs)):
            self.progress(f"Rendering clip {i + 1} of {len(self.tl.clips)}: {c.label or c.type}")
            key = self._key(c, d, prev_key)
            seg, last_png = self.cache / f"{key}.mp4", self.cache / f"{key}_last.png"
            if not (seg.exists() and last_png.exists()):
                try:
                    last = self._render_clip(c, d, prev, seg)
                except FFmpegError as exc:
                    res.warnings.append(f"Clip {i + 1} ({c.label or c.type}) skipped: {exc}")
                    continue
                last.save(last_png)
            with Image.open(last_png) as im:
                prev = im.convert("RGB")
            real = media_duration(self.ff, seg)
            trans = TRANSITION_SECONDS.get(c.transition, 0.0) if segs else 0.0
            segs.append(seg)
            starts.append((c, t, real, trans))
            res.clips.append({"id": c.id, "type": c.type, "label": c.label, "start": round(t, 2), "end": round(t + real, 2)})
            t += real
            prev_key = key
        if not segs:
            res.warnings.append("No clip could be rendered.")
            return res
        total = t
        self.progress("Mixing narration, music and clip audio")
        video_only = self.work / f"video_only_{self.quality}.mp4"
        self._concat(segs, video_only)

        track = np.zeros(int((total + 0.5) * A.RATE), np.float32)
        narr = np.zeros_like(track)
        cues: list[tuple[float, float, str]] = []
        tmp = self.work / "fit_tmp.wav"
        for idx, (c, start, real, trans) in enumerate(starts):
            end = start + real
            if c.id in per_clip and c.type != "video":
                a = A.fit(per_clip[c.id], end - start - trans - LEAD - 0.2, self.ff, tmp)
                A.place(narr, a, start + trans + LEAD)
                cues += _cues(texts.get(c.id, ""), start + trans + LEAD, A.seconds(a))
            if c.type == "video":
                segs_sorted = sorted(enumerate(c.narration_segments), key=lambda x: x[1].start)
                for j, (si, s) in enumerate(segs_sorted):
                    a = per_seg.get((c.id, si))
                    if a is None:
                        continue
                    at = start + trans + max(0.0, (s.start - c.trim_start) / c.speed)
                    nxt = segs_sorted[j + 1][1].start if j + 1 < len(segs_sorted) else (c.trim_end or c.source_duration or s.end)
                    window = min(end, start + trans + (nxt - c.trim_start) / c.speed) - at - 0.15
                    if at >= end - 0.3 or window <= 0.3:
                        continue
                    a = A.fit(a, window, self.ff, tmp, max_speedup=1.25)
                    A.place(narr, a, at)
                    cues += _cues(s.text, at, A.seconds(a))
                if c.id in per_clip:
                    A.place(narr, per_clip[c.id], start + trans)
                src = self.media_path(c.asset_id or "")
                if c.keep_audio and src:
                    body_len = real - trans
                    ca = A.decode(self.ff, src, c.trim_start, body_len * c.speed, c.speed)
                    gain = c.audio_volume * (0.25 if c.narration_segments else 1.0)
                    A.place(track, ca, start + trans, gain)
        if whole is not None:
            first = next((s for (c, s, _, tr) in starts if c.type not in ("intro",)), 0.0)
            A.place(narr, whole, first + 0.3)
            if n.script.strip():
                cues += _cues(n.script, first + 0.3, A.seconds(whole))
        track += narr
        res.narrated = bool(np.abs(narr).max() > 0.001) if len(narr) else False
        m = self.tl.music
        if m.asset_id:
            mp = self.media_path(m.asset_id)
            if mp:
                track += A.music_track(self.ff, mp, total + 0.5, m.volume, m.fade_in, m.fade_out,
                                       A.envelope(narr) if m.duck else None)
            else:
                res.warnings.append("The selected music track is missing.")
        peak = float(np.abs(track).max()) if len(track) else 0
        if peak > 0.97:
            track *= 0.97 / peak
        mix = A.write_wav(self.work / f"mix_{self.quality}.wav", track)

        self.out_dir.mkdir(parents=True, exist_ok=True)
        name = "presentation" if self.quality == "final" else "preview"
        out = self.out_dir / f"{name}.mp4"
        srt = None
        if self.tl.subtitles and cues:
            res.subtitles_srt = self.out_dir / f"{name}.srt"
            res.subtitles_vtt = self.out_dir / f"{name}.vtt"
            res.subtitles_srt.write_text(_srt(cues), encoding="utf-8")
            res.subtitles_vtt.write_text(_vtt(cues), encoding="utf-8")
            srt = res.subtitles_srt
        args = [self.ff, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video_only), "-i", str(mix)]
        if srt:
            args += ["-i", str(srt), "-map", "0:v", "-map", "1:a", "-map", "2:s", "-c:s", "mov_text", "-metadata:s:s:0", "language=eng"]
        else:
            args += ["-map", "0:v", "-map", "1:a"]
        args += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart", str(out)]
        r = subprocess.run(args, capture_output=True, text=True, creationflags=NO_WINDOW)
        if r.returncode != 0 or not out.exists():
            raise FFmpegError(f"Final mux failed: {r.stderr[-200:]}")
        res.video, res.duration = out, round(media_duration(self.ff, out), 2)
        log.info("Timeline rendered", clips=len(segs), seconds=res.duration, quality=self.quality)
        return res


def _cues(text: str, start: float, length: float) -> list[tuple[float, float, str]]:
    from backend.intelligence.chunking import split_sentences

    sents = split_sentences(text or "") or ([text] if text else [])
    total = sum(len(s) for s in sents) or 1
    out, t = [], start
    for s in sents:
        d = length * len(s) / total
        out.append((round(t, 3), round(t + d, 3), s))
        t += d
    return out


def _ts(sec: float, sep: str) -> str:
    h, rem = divmod(max(0.0, sec), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d}{sep}{int(round((s % 1) * 1000)) % 1000:03d}"


def _srt(cues) -> str:
    return "\n".join(f"{i}\n{_ts(a, ',')} --> {_ts(b, ',')}\n{t}\n" for i, (a, b, t) in enumerate(cues, 1))


def _vtt(cues) -> str:
    return "WEBVTT\n\n" + "\n".join(f"{_ts(a, '.')} --> {_ts(b, '.')}\n{t}\n" for a, b, t in cues)



