"""
GPU inference test for PerkySue.
Runs a minimal LLM inference to verify CUDA works.

Exit codes:
  0 = GPU inference works
  1 = Python error (import, model not found, etc.)
  2 = GPU failed but CPU works
  3 = Nothing works

Usage:
  python test_gpu.py <model_path> [n_gpu_layers]
"""

import sys
import os
import time


def test_inference(model_path, n_gpu_layers=-1):
    """Try a minimal inference. Returns (success, message)."""
    try:
        from llama_cpp import Llama
    except ImportError:
        return False, "llama-cpp-python not installed"

    try:
        model = Llama(
            model_path=model_path,
            n_gpu_layers=n_gpu_layers,
            n_ctx=512,
            verbose=False,
        )
    except Exception as e:
        return False, f"Load failed: {e}"

    try:
        result = model.create_chat_completion(
            messages=[
                {"role": "system", "content": "Reply with exactly: OK"},
                {"role": "user", "content": "test"},
            ],
            temperature=0,
            max_tokens=5,
        )
        text = result["choices"][0]["message"]["content"].strip()
        return True, f"Inference OK: '{text}'"
    except Exception as e:
        return False, f"Inference failed: {e}"


def main():
    if len(sys.argv) < 2:
        print("Usage: test_gpu.py <model_path> [n_gpu_layers]")
        sys.exit(1)

    model_path = sys.argv[1]
    n_gpu_layers = int(sys.argv[2]) if len(sys.argv) > 2 else -1

    if not os.path.exists(model_path):
        print(f"FAIL: Model not found: {model_path}")
        sys.exit(1)

    # Test GPU
    if n_gpu_layers != 0:
        print(f"Testing GPU inference (n_gpu_layers={n_gpu_layers})...")
        start = time.time()
        ok, msg = test_inference(model_path, n_gpu_layers)
        elapsed = time.time() - start

        if ok:
            print(f"GPU OK ({elapsed:.1f}s): {msg}")
            sys.exit(0)
        else:
            print(f"GPU FAILED ({elapsed:.1f}s): {msg}")

    # Test CPU fallback
    print("Testing CPU inference (n_gpu_layers=0)...")
    # Hide GPU entirely — CUDA-compiled wheels crash even with n_gpu_layers=0
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    start = time.time()
    ok, msg = test_inference(model_path, 0)
    elapsed = time.time() - start

    if ok:
        print(f"CPU OK ({elapsed:.1f}s): {msg}")
        sys.exit(2)  # GPU failed, CPU works
    else:
        print(f"CPU FAILED ({elapsed:.1f}s): {msg}")
        sys.exit(3)  # Nothing works


if __name__ == "__main__":
    main()
