"""Cell B: SunflowerASR (Swahili, Amharic) and IndicConformer (Hindi, Tamil) under noise, without a denoiser. T4 GPU runtime, no token.

Same clips, conditions, level fix (-23 dBFS) and scoring as colab_noise_pilot.py: FLEURS test (CC-BY-4.0), first 30 clips per language, babble from
clips 30 to 59 of the same language. Refuses to start while the HF_TOKEN secret or a token variable exists. Models load once; each condition's rows
are appended to /content/results/noise_engines_clips.csv as soon as it finishes, so a recycled runtime loses at most one condition.
"""
import os, sys, json, csv, time, random, glob, ctypes, site, shlex, subprocess, importlib.metadata as md
from google.colab import userdata
leak = False
try: userdata.get("HF_TOKEN"); leak = True
except Exception as e:
    if type(e).__name__ == "TimeoutException": print("NOTE: could not check the secret (tab in the background?). Make sure it is deleted.")
if leak: raise SystemExit("HF_TOKEN secret still exists: delete it and the token, then rerun.")
if "tok" in globals(): raise SystemExit("token still in memory: restart the session, then run this cell.")
RV = "/content/rv_cache"; SU_DIR = RV + "/models/sunflowerasr-51-african-languages/4583c9dd251c422a4325fb0a0a509a3828097be2"; IC_DIR = "/content/cand_indicconformer"
for d in (SU_DIR, IC_DIR):
    if not os.path.isdir(d): raise SystemExit(d + " missing: run cell A first")
def sh(cmd, timeout=3600):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout); return r.returncode, (r.stdout + r.stderr)
def need(ok, msg):
    if not ok: raise SystemExit(msg)
rc, o = sh("pip install -q 'datasets==3.6.0' soundfile 'git+https://github.com/ragleap/ragleap-core.git#subdirectory=packages/ragleap-voice'"); need(rc == 0, o[-500:])
rc, o = sh("%s -m ragleap_voice models verify sunflowerasr-51-african-languages --cache-dir %s" % (sys.executable, RV)); print("verify Sunflower folder:", o.strip()[-120:]); need(rc == 0, "verification failed")
import numpy as np, soundfile as sf, torch
from datasets import load_dataset
from ragleap_voice.bench.metrics import normalize
from transformers import WhisperForConditionalGeneration, WhisperFeatureExtractor, AutoTokenizer, AutoModel
need(torch.cuda.is_available(), "No GPU: Runtime > Change runtime type > T4 GPU, press Save")
libs = []
for r in site.getsitepackages() + [site.getusersitepackages()]:
    libs += sorted(glob.glob(r + "/nvidia/cublas/lib/libcublas*.so.12"), reverse=True) + sorted(glob.glob(r + "/nvidia/cudnn/lib/libcudnn*.so.9"))
for p in libs:
    try: ctypes.CDLL(p, mode=ctypes.RTLD_GLOBAL)
    except OSError: pass
main_sha = sh("git ls-remote https://github.com/ragleap/ragleap-core.git refs/heads/main")[1].split()[0]

LANGS = {"sw": "sw_ke", "am": "am_et", "hi": "hi_in", "ta": "ta_in"}
ENGINE_LANGS = {"sunflower": ["sw", "am"], "indicconformer": ["hi", "ta"]}
SUN = {"sw": 50318, "am": 50334}
N, NB = 30, 30
clips, pool = {}, {}
for code, cfg in LANGS.items():
    ds = load_dataset("google/fleurs", cfg, split="test", streaming=True, trust_remote_code=True); arr = []
    for i, ex in enumerate(ds):
        if i >= N + NB: break
        assert ex["audio"]["sampling_rate"] == 16000
        arr.append((np.asarray(ex["audio"]["array"], dtype="float32"), ex["transcription"]))
    clips[code], pool[code] = arr[:N], [a for a, _ in arr[N:]]
print({k: len(v) for k, v in clips.items()})
def rms(x): return float(np.sqrt(np.mean(x ** 2)) + 1e-12)
def crop(x, n, rng):
    if len(x) < n: x = np.tile(x, int(np.ceil(n / len(x))))
    s = int(rng.integers(0, len(x) - n + 1)); return x[s:s + n]
def babble(n, lang, rng): return sum(crop(pool[lang][int(rng.integers(0, len(pool[lang])))], n, rng) / rms(pool[lang][0]) for _ in range(4)).astype("float32")
def mix(sig, noise, snr_db): return np.clip(sig + noise * (rms(sig) / rms(noise) / (10 ** (snr_db / 20))), -1, 1).astype("float32")
def telephone(x):
    os.makedirs("/tmp/ph", exist_ok=True); sf.write("/tmp/ph/a.wav", x, 16000, subtype="PCM_16")
    for cmd in ("ffmpeg -y -loglevel error -i /tmp/ph/a.wav -ar 8000 -ac 1 -c:a pcm_mulaw /tmp/ph/b.wav", "ffmpeg -y -loglevel error -i /tmp/ph/b.wav -ar 16000 -ac 1 -c:a pcm_s16le /tmp/ph/c.wav"):
        rc, o = sh(cmd); need(rc == 0, "ffmpeg failed: " + o[-200:])
    return sf.read("/tmp/ph/c.wav", dtype="float32")[0]
def level(x): return np.clip(x * min((10 ** (-23 / 20)) / rms(x), 0.95 / max(float(np.abs(x).max()), 1e-9)), -1, 1).astype("float32")
COND = ["clean", "white10", "babble10", "babble5", "phone_babble10"]
def make(lang, cond, i, a):
    rng = np.random.default_rng(1234 + i)
    if cond == "clean": x = a
    elif cond == "white10": x = mix(a, rng.standard_normal(len(a)).astype("float32"), 10)
    elif cond == "babble10": x = mix(a, babble(len(a), lang, rng), 10)
    elif cond == "babble5": x = mix(a, babble(len(a), lang, rng), 5)
    else: x = telephone(mix(a, babble(len(a), lang, rng), 10))
    return level(x)
def prep(x):
    n = normalize(x); return " ".join(n) if isinstance(n, (list, tuple)) else n
def ed(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1): cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]

def build_sunflower():
    tokz = AutoTokenizer.from_pretrained(SU_DIR, local_files_only=True)
    model = WhisperForConditionalGeneration.from_pretrained(SU_DIR, torch_dtype=torch.float16, local_files_only=True).to("cuda").train(False)
    tr, nt = tokz.convert_tokens_to_ids("<|transcribe|>"), tokz.convert_tokens_to_ids("<|notimestamps|>"); fe = WhisperFeatureExtractor(feature_size=128)
    def run(lang, audio):
        hyps = []
        for i in range(0, len(audio), 8):
            feats = fe(audio[i:i + 8], sampling_rate=16000, return_tensors="pt").input_features.to("cuda", torch.float16)
            with torch.no_grad(): out = model.generate(input_features=feats, forced_decoder_ids=[(1, SUN[lang]), (2, tr), (3, nt)], num_beams=1, do_sample=False, max_new_tokens=220)
            for row in out.tolist():
                k = row.index(nt) + 1 if nt in row[:8] else 0; hyps.append(tokz.decode(row[k:], skip_special_tokens=True).strip())
        return hyps
    def close():
        nonlocal model; del model; torch.cuda.empty_cache()
    return run, close
def build_ic():
    import huggingface_hub
    for k in [k for k in sys.modules if "model_onnx" in k]: del sys.modules[k]
    orig = huggingface_hub.snapshot_download
    huggingface_hub.snapshot_download = lambda repo_id, *a, **k: IC_DIR if repo_id == IC_DIR else orig(repo_id, *a, **k)
    try: m = AutoModel.from_pretrained(IC_DIR, trust_remote_code=True, local_files_only=True)
    finally: huggingface_hub.snapshot_download = orig
    def run(lang, audio):
        hyps = []
        for a in audio:
            parts = []
            for i in range(0, len(a), 25 * 16000):
                c = a[i:i + 25 * 16000]
                if len(c) < 1600: continue
                out = m(torch.from_numpy(c).unsqueeze(0), lang, "rnnt"); parts.append(str(out[0] if isinstance(out, (list, tuple)) else out).strip())
            hyps.append(" ".join(p for p in parts if p))
        return hyps
    return run, (lambda: None)

OUT = "/content/results/noise_engines_clips.csv"; os.makedirs("/content/results", exist_ok=True)
done = set()
if os.path.exists(OUT):
    for r in csv.DictReader(open(OUT, encoding="utf-8")): done.add((r["engine"], r["lang"], r["cond"]))
else:
    with open(OUT, "w", encoding="utf-8", newline="") as f: csv.writer(f, lineterminator="\n").writerow(["engine", "lang", "cond", "clip", "ref", "hyp", "we", "wn", "ce", "cn"])
FILLER = {"thank you", "thank you.", "thanks for watching", "you", "."}
t0 = time.time()
for eng, langs in ENGINE_LANGS.items():
    run, close = build_sunflower() if eng == "sunflower" else build_ic(); print("loaded", eng, "(%.0f s)" % (time.time() - t0))
    for lang in langs:
        for cond in COND:
            if (eng, lang, cond) in done: print("skip (done):", eng, lang, cond); continue
            audio = [make(lang, cond, i, a) for i, (a, _) in enumerate(clips[lang])]; hyps = run(lang, audio); rows, we, wn = [], 0, 0
            for k, ((_, ref), hyp) in enumerate(zip(clips[lang], hyps)):
                r, h = prep(ref), prep(hyp); e = (ed(r.split(), h.split()), len(r.split()), ed(list(r), list(h)), len(r)); we += e[0]; wn += e[1]; rows.append([eng, lang, cond, k, ref, hyp, *e])
            with open(OUT, "a", encoding="utf-8", newline="") as f: csv.writer(f, lineterminator="\n").writerows(rows)
            print("%s %s %-15s WER %5.1f%%  empty %d  filler %d  (%.0f s)" % (eng, lang, cond, 100 * we / max(1, wn), sum(1 for h in hyps if not h.strip()), sum(1 for h in hyps if h.strip().lower() in FILLER), time.time() - t0))
    close()

res = {}
for r in csv.DictReader(open(OUT, encoding="utf-8")): res.setdefault((r["engine"], r["lang"], r["cond"]), []).append((int(r["we"]), int(r["wn"]), int(r["ce"]), int(r["cn"])))
rnd = random.Random(1234)
def wer(pc, idx=None):
    idx = idx if idx is not None else range(len(pc)); return sum(pc[i][0] for i in idx) / max(1, sum(pc[i][1] for i in idx))
def ci(pc, B=2000):
    n = len(pc); v = sorted(wer(pc, [rnd.randrange(n) for _ in range(n)]) for _ in range(B)); return v[int(0.025 * B)], v[int(0.975 * B)]
def boot(a, b, B=2000):
    n = len(a); d = []
    for _ in range(B):
        idx = [rnd.randrange(n) for _ in range(n)]; d.append(wer(a, idx) - wer(b, idx))
    d.sort(); return d[int(0.025 * B)], d[int(0.975 * B)]
print("\nWER %, 30 clips, no denoiser, every clip at -23 dBFS. 'vs clean' = condition minus clean on the same clips, 95% interval.")
for eng, langs in ENGINE_LANGS.items():
    for lang in langs:
        c = res.get((eng, lang, "clean"))
        if not c: continue
        print("\n== %s / %s ==" % (eng, lang)); lo, hi = ci(c); print("%-15s %5.1f (%4.1f-%4.1f)" % ("clean", 100 * wer(c), 100 * lo, 100 * hi))
        for cond in COND[1:]:
            p = res.get((eng, lang, cond))
            if not p: continue
            lo, hi = ci(p); dl, dh = boot(p, c); print("%-15s %5.1f (%4.1f-%4.1f)   vs clean %+5.1f [%+5.1f, %+5.1f]" % (cond, 100 * wer(p), 100 * lo, 100 * hi, 100 * (wer(p) - wer(c)), 100 * dl, 100 * dh))
print("\nMETA:", json.dumps(dict(gpu=sh("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader")[1].strip(), transformers=md.version("transformers"), torch=torch.__version__,
      sunflower="from the ragleap-voice lock, revision 4583c9dd251c, folder verified before use", indicconformer_rev="2a77d305038dfc502fd9464e7d028b90381976cb", decoding_sunflower="greedy, forced language token, max_new_tokens 220, fp16, batch 8",
      decoding_indicconformer="RNNT, 25 s chunks", level_fix="-23 dBFS RMS, peak limit 0.95", harness_main=main_sha, normalizer_version="1"), indent=1))
