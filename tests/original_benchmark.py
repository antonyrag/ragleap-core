
from core.language import language_detector

TEST_CASES = [
    # French
    ("Quel framework utilise RagLeap Core?", "fr"),
    ("Comment fonctionne RagLeap Core?", "fr"),
    ("Quel framework", "fr"),
    ("Comment ça va", "fr"),
    ("Quelle API utilise RagLeap?", "fr"),

    # Italian
    ("Quale framework usa RagLeap Core?", "it"),
    ("Come funziona RagLeap Core?", "it"),
    ("Quale framework", "it"),
    ("Come stai", "it"),
    ("Quale API usa RagLeap?", "it"),

    # Spanish
    ("¿Qué framework utiliza RagLeap Core?", "es"),
    ("¿Cómo funciona RagLeap?", "es"),
    ("Qué framework", "es"),
    ("¿Cómo estás?", "es"),
    ("¿Qué API utiliza RagLeap?", "es"),

    # Portuguese
    ("Qual framework o RagLeap usa?", "pt"),
    ("Como funciona o RagLeap?", "pt"),
    ("Qual API o RagLeap usa?", "pt"),

    # English
    ("How does RagLeap Core work?", "en"),
    ("Which framework uses RagLeap?", "en"),
    ("How are you", "en"),
    ("RagLeap framework", "en"),
    ("RAG pipeline", "en"),

    # German
    ("Welches Framework nutzt RagLeap?", "de"),
    ("Wie funktioniert RagLeap?", "de"),
    ("Wie geht's", "de"),

    # Japanese
    ("こんにちは", "ja"),
    ("元気ですか", "ja"),

    # Korean
    ("안녕하세요", "ko"),
    ("어떻게 작동하나요", "ko"),

    # Chinese
    ("你好", "zh"),
    ("你好吗", "zh"),
]

correct = 0

print("Original langdetect benchmark")
print("=" * 80)

for text, expected in TEST_CASES:
    predicted, confidence = language_detector.detect_query_language(text)

    status = "PASS" if predicted == expected else "FAIL"

    if predicted == expected:
        correct += 1

    print(
        f"{text:<45} "
        f"{predicted:<4} "
        f"expected={expected:<4} "
        f"conf={confidence:.3f} "
        f"{status}"
    )

print("=" * 80)
print(f"Accuracy: {correct}/{len(TEST_CASES)} = {correct / len(TEST_CASES) * 100:.2f}%")
