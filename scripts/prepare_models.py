"""One-time, offline preparation of local models.

Exports the configured sentence-transformers embedding model (already present in the
local HuggingFace cache) to ONNX so the backend can embed text with onnxruntime and
start in about a second instead of importing torch.

    python scripts/prepare_models.py [--model sentence-transformers/all-MiniLM-L6-v2]

By default nothing is downloaded (HF_HUB_OFFLINE=1). On a fresh machine, pass
--allow-download once to fetch the model from the Hugging Face hub during setup.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_ALLOW = "--allow-download" in sys.argv
os.environ["HF_HUB_OFFLINE"] = "0" if _ALLOW else "1"
os.environ["TRANSFORMERS_OFFLINE"] = "0" if _ALLOW else "1"

from backend.intelligence.embeddings import onnx_dir_for  # noqa: E402
from backend.utils.config import get_settings  # noqa: E402


def export(model_name: str) -> Path:
    import numpy as np
    import torch
    from transformers import AutoModel, AutoTokenizer

    out = onnx_dir_for(model_name)
    out.mkdir(parents=True, exist_ok=True)
    print(f"Loading {model_name} from local cache ...")
    tok = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name).eval()
    enc = tok(["a sample sentence for export"], return_tensors="pt")
    inputs = (enc["input_ids"], enc["attention_mask"], enc.get("token_type_ids", torch.zeros_like(enc["input_ids"])))
    print("Exporting to ONNX ...")
    torch.onnx.export(
        model, inputs, str(out / "model.onnx"),
        input_names=["input_ids", "attention_mask", "token_type_ids"], output_names=["last_hidden_state"],
        dynamic_axes={n: {0: "batch", 1: "seq"} for n in ("input_ids", "attention_mask", "token_type_ids", "last_hidden_state")},
        opset_version=14, do_constant_folding=True,
    )
    tok.save_pretrained(str(out / "tokenizer"))
    shutil.copy(out / "tokenizer" / "tokenizer.json", out / "tokenizer.json")

    # verify parity with the PyTorch model
    import onnxruntime as ort

    sess = ort.InferenceSession(str(out / "model.onnx"), providers=["CPUExecutionProvider"])
    feed = {k: v.numpy() for k, v in zip(("input_ids", "attention_mask", "token_type_ids"), inputs)}
    onnx_out = sess.run(None, feed)[0]
    with torch.no_grad():
        torch_out = model(*inputs)[0].numpy()
    diff = float(np.abs(onnx_out - torch_out).max())
    print(f"Max abs difference vs PyTorch: {diff:.2e}")
    if diff > 1e-3:
        raise SystemExit("ONNX export mismatch - not using it")
    print(f"Saved to {out}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=get_settings().embedding_model)
    ap.add_argument("--allow-download", action="store_true", help="fetch the model if it is not in the local cache (setup only)")
    export(ap.parse_args().model)
