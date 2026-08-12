# Neutral STT Benchmark WAV

Created for [issue #12](https://github.com/antonyrag/ragleap-core/issues/12) — a neutral, vendor-agnostic test file for comparing STT provider cost/accuracy/latency (Deepgram, OpenAI, ElevenLabs).

## File

- **`benchmark.wav`**
- **Duration:** 9.62 seconds
- **Format:** 16kHz mono WAV, 16-bit PCM
- **Size:** 308,046 bytes
- **SHA-256:** `eade9f6eed5cd05f69f614d01ded53520d2a3c6d8ba43dcfccfeea1ac1890c43`

## Ground-truth transcript

> Please schedule a callback for tomorrow at three fifteen. Order number four seven two nine, total due one hundred twenty dollars.

## Generation

Generated via Google TTS (gTTS), converted to WAV via ffmpeg. Fully neutral — no vendor-specific tuning, no brand names, no proper nouns. Contains spoken numbers (a common STT stress point) and everyday business vocabulary.

```bash
pip install gTTS
python3 -c "
from gtts import gTTS
text = 'Please schedule a callback for tomorrow at three fifteen. Order number four seven two nine, total due one hundred twenty dollars.'
gTTS(text=text, lang='en', slow=False).save('raw.mp3')
"
ffmpeg -i raw.mp3 -ar 16000 -ac 1 benchmark.wav
```
