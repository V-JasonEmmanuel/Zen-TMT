"""Image generation worker (runs in its own Python process so the app never holds the model in memory).

    python -m backend.branddocs.imagegen_worker job.json

job.json: {"model_dir": ..., "checkpoint": ..., "jobs": [{"prompt", "negative", "w", "h", "seed", "steps", "guidance", "out"}]}
Prints one JSON object per line: {"event": "loaded"|"image"|"error"|"done", ...}. Fully offline (local files only).
"""
from __future__ import annotations

import json
import os
import sys
import time


def emit(**kw) -> None:
    print(json.dumps(kw), flush=True)


def main(path: str) -> int:
    job = json.loads(open(path, encoding="utf-8").read())
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["DIFFUSERS_OFFLINE"] = "1"
    # optional quantisation libraries in newer builds need a newer torch; they are never used here
    for m in ("bitsandbytes", "torchao"):
        sys.modules[m] = None  # type: ignore[assignment]
    t0 = time.time()
    try:
        import torch
        from diffusers import LCMScheduler, StableDiffusionPipeline
    except Exception as exc:  # pragma: no cover - environment specific
        emit(event="error", message=f"Image generation libraries are not installed: {exc}")
        return 2
    cuda = torch.cuda.is_available()
    dtype = torch.float16 if cuda else torch.float32
    try:
        pipe = StableDiffusionPipeline.from_single_file(job["checkpoint"], config=job["model_dir"], local_files_only=True,
                                                        torch_dtype=dtype, safety_checker=None, requires_safety_checker=False)
        pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
        pipe.set_progress_bar_config(disable=True)
        if cuda:
            pipe = pipe.to("cuda")
            pipe.enable_attention_slicing()
        else:
            torch.set_num_threads(max(1, (os.cpu_count() or 4) - 1))
    except Exception as exc:
        emit(event="error", message=f"The image model could not be loaded: {str(exc)[:300]}")
        return 3
    emit(event="loaded", device="cuda" if cuda else "cpu", seconds=round(time.time() - t0, 1))
    for i, j in enumerate(job["jobs"]):
        t = time.time()
        try:
            g = torch.Generator(device="cuda" if cuda else "cpu").manual_seed(int(j.get("seed", 7)))
            img = pipe(j["prompt"], negative_prompt=j.get("negative") or None, num_inference_steps=int(j.get("steps", 5)),
                       guidance_scale=float(j.get("guidance", 1.5)), width=int(j["w"]), height=int(j["h"]), generator=g).images[0]
            img.save(j["out"])
            emit(event="image", i=i, path=j["out"], seconds=round(time.time() - t, 1))
        except Exception as exc:
            emit(event="error", i=i, message=str(exc)[:300])
    emit(event="done", seconds=round(time.time() - t0, 1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
