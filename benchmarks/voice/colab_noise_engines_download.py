"""Cell A: get SunflowerASR (through ragleap-voice, hash-checked) and IndicConformer (pinned revision). T4 GPU runtime.

Needs a short-lived Hugging Face Read token as the Colab secret HF_TOKEN (Notebook access on) only if the folders do not exist yet.
Delete the secret and the token afterwards, restart the session (files stay), then run colab_noise_engines_measure.py:
IndicConformer runs its own repository code (trust_remote_code), so it must not be able to reach a token.
"""
import subprocess, sys, os
def sh(cmd, env=None):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, env=env); return r.returncode, (r.stdout + r.stderr)
rc, o = sh("pip install -q huggingface_hub 'datasets==3.6.0' soundfile accelerate transformers==5.18.0 onnxruntime-gpu==1.31.0 onnx==1.20.1 torchaudio && pip install -q --force-reinstall --no-deps --no-cache-dir 'git+https://github.com/ragleap/ragleap-core.git#subdirectory=packages/ragleap-voice'")
assert rc == 0, o[-500:]
SU, SU_REV = "sunflowerasr-51-african-languages", "4583c9dd251c422a4325fb0a0a509a3828097be2"
IC, IC_REV = "ai4bharat/indic-conformer-600m-multilingual", "2a77d305038dfc502fd9464e7d028b90381976cb"
RV = "/content/rv_cache"; SU_DIR = "%s/models/%s/%s" % (RV, SU, SU_REV); IC_DIR = "/content/cand_indicconformer"
if os.path.isdir(SU_DIR) and os.path.isdir(IC_DIR):
    print("Both folders already exist: no token needed. Run cell B.")
else:
    from huggingface_hub import snapshot_download, HfApi
    from google.colab import userdata
    try: tok = userdata.get("HF_TOKEN")
    except Exception: raise SystemExit("Secret fetch failed: keep this tab in the foreground, check HF_TOKEN (Notebook access on), rerun")
    if not tok: raise SystemExit("HF_TOKEN is empty")
    base_env = {k: v for k, v in os.environ.items() if "TOKEN" not in k.upper()}
    if not os.path.isdir(SU_DIR):
        r = subprocess.run([sys.executable, "-m", "ragleap_voice", "models", "pull", SU, "--cache-dir", RV, "--allow-unverified"], capture_output=True, text=True, env=dict(base_env, HF_TOKEN=tok))
        print("pull", SU, "rc =", r.returncode, "|", (r.stdout + r.stderr).strip()[-200:]); assert r.returncode == 0
    if not os.path.isdir(IC_DIR):
        v = HfApi().model_info(IC, revision=IC_REV, token=tok).card_data.license
        assert (v if isinstance(v, str) else (v or [""])[0]).lower() == "mit", "IndicConformer licence changed: STOP"
        snapshot_download(IC, revision=IC_REV, token=tok, local_dir=IC_DIR)
    del tok
    print("\nDOWNLOADS DONE. Delete the HF_TOKEN secret (key icon) and the token on huggingface.co, then Runtime > Restart session (files stay), then run cell B.")
