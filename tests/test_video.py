"""Video: MP4 produced, correct duration, audio/subtitle sync, graceful degradation."""
import wave

import pytest

from backend.planning.video_planner import TRANSITION, plan_storyboard
from backend.rendering.images.raster import RasterRenderer
from backend.rendering.layouts import RenderContext, build_slide_scene
from backend.rendering.video.ffmpeg import find_ffmpeg, media_duration, media_streams
from backend.rendering.video.narration import get_tts_engine
from backend.rendering.video.storyboard import render_video
from backend.branding.brand_profile import BrandStore, ensure_default_brands
from backend.branding.theme import build_theme

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def short_plan(extractive_plan):
    plan = extractive_plan.model_copy(deep=True)
    plan.slides = plan.slides[:3]
    return plan


@pytest.fixture(scope="module")
def frames(short_plan, tmp_path_factory):
    ensure_default_brands()
    theme = build_theme(BrandStore().load("zensar"))
    d = tmp_path_factory.mktemp("frames")
    ctx = RenderContext(short_plan)
    rr = RasterRenderer(1280)
    return {s.slide_number: rr.save(build_slide_scene(s, theme, ctx), d / f"s{s.slide_number}.png") for s in short_plan.slides}


def test_storyboard_timing(short_plan):
    sb = plan_storyboard(short_plan, {1: 4.0, 2: 6.0, 3: 5.0})
    assert sb[1].start == pytest.approx(sb[0].duration - TRANSITION)
    for sc in sb:
        assert sc.duration >= sc.audio_seconds + TRANSITION


@pytest.mark.skipif(not find_ffmpeg(), reason="FFmpeg not available")
def test_silent_video(short_plan, frames, tmp_path):
    res = render_video(short_plan, frames, tmp_path / "out", tmp_path / "work", narration=False)
    assert res.video and res.video.exists()
    expected = sum(sc.duration for sc in plan_storyboard(short_plan)) - TRANSITION * 2
    assert media_duration(find_ffmpeg(), res.video) == pytest.approx(expected, abs=0.5)
    assert media_streams(find_ffmpeg(), res.video)["Audio"] == 0


@pytest.mark.skipif(not find_ffmpeg() or get_tts_engine("auto") is None, reason="FFmpeg or offline TTS not available")
def test_narrated_video_audio_sync(short_plan, frames, tmp_path):
    res = render_video(short_plan, frames, tmp_path / "out", tmp_path / "work", narration=True, subtitles=True)
    assert res.narrated
    ff = find_ffmpeg()
    streams = media_streams(ff, res.video)
    assert streams["Video"] == 1 and streams["Audio"] == 1 and streams["Subtitle"] == 1
    video_len = media_duration(ff, res.video)
    with wave.open(str(tmp_path / "work" / "narration.wav")) as w:
        audio_len = w.getnframes() / w.getframerate()
    assert abs(audio_len - video_len) < 1.5  # narration track spans the whole video
    vtt = res.subtitles_vtt.read_text(encoding="utf-8")
    assert vtt.startswith("WEBVTT") and "-->" in vtt


def test_missing_ffmpeg_degrades_gracefully(short_plan, frames, tmp_path, monkeypatch):
    import backend.rendering.video.storyboard as sb

    monkeypatch.setattr(sb, "find_ffmpeg", lambda *_: None)
    res = sb.render_video(short_plan, frames, tmp_path / "o", tmp_path / "w")
    assert res.video is None and "FFmpeg" in res.warnings[0]
