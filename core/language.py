"""
Language Detection Service for RagLeap Core
Ported from production's multilingual/language_detector.py — single-tenant,
Django settings replaced with .env vars, dead/unreachable code removed.
"""
import os
import re
import logging
import math
from collections import Counter
from fast_langdetect import detect
logger = logging.getLogger(__name__)
DEFAULT_LANGUAGE = os.environ.get("DEFAULT_LANGUAGE", "en")
CONFIDENCE_THRESHOLD = float(os.environ.get("LANGUAGE_DETECTION_CONFIDENCE_THRESHOLD", "0.7"))
NGRAM_CONFIDENCE_THRESHOLD = float(os.environ.get("LANGUAGE_DETECTION_NGRAM_CONFIDENCE_THRESHOLD", "0.55"))

_detection_langs_raw = os.environ.get("LANGUAGE_DETECTION_SUPPORTED_LANGUAGES", "")
DETECTION_LANGUAGES = (
    {lang.strip() for lang in _detection_langs_raw.split(",") if lang.strip()}
    if _detection_langs_raw
    else None
)

_stop_words_raw = os.environ.get("RAG_CONTENT_LANG_STOP_WORDS", "")
CONTENT_LANG_STOP_WORDS = {w.strip() for w in _stop_words_raw.split(",") if w.strip()}
CONTENT_LANG_MIN_TERMS = int(os.environ.get("RAG_CONTENT_LANG_MIN_TERMS", "2"))
CONTENT_LANG_MIN_TERM_LEN = int(os.environ.get("RAG_CONTENT_LANG_MIN_TERM_LEN", "4"))
CONTENT_LANG_MIN_CONFIDENCE = float(os.environ.get("RAG_CONTENT_LANG_MIN_CONFIDENCE", "0.85"))
ENABLE_CONTENT_LANG_DETECTION = os.environ.get("RAG_ENABLE_CONTENT_LANG_DETECTION", "true").lower() == "true"

NGRAM_MIN = 2
NGRAM_MAX = 5
NGRAM_ALPHA = 0.1

TRAINING_DATA = {
    "en": [
        "what framework does RagLeap use",
        "which API does RagLeap use",
        "how does RagLeap work",
        "what is RagLeap Core",
        "explain the application architecture",
        "how do I configure the application",
        "where is the configuration file",
        "what database does the application use",
        "how can I run the application",
        "what does this function do",
        "show me the API documentation",
        "how does retrieval work",
        "what is the default language",
        "which model is being used",
        "how do I install the package",
        "why is the application failing",
        "how can I debug this error",
        "what framework is used",
        "how does the system work",
        "explain this implementation",
        "what dependencies are required",
        "where can I find the tests",
        "how do I run the tests",
        "what is the purpose of this module",
        "RagLeap framework",
    ],
    "fr": [
        "quel framework utilise RagLeap",
        "quelle API utilise RagLeap",
        "comment fonctionne RagLeap",
        "qu'est-ce que RagLeap Core",
        "expliquez l'architecture de l'application",
        "comment configurer l'application",
        "où se trouve le fichier de configuration",
        "quelle base de données utilise l'application",
        "comment exécuter l'application",
        "que fait cette fonction",
        "montrez-moi la documentation API",
        "comment fonctionne la recherche",
        "quelle est la langue par défaut",
        "quel modèle est utilisé",
        "comment installer le paquet",
        "pourquoi l'application échoue",
        "comment déboguer cette erreur",
        "quel framework est utilisé",
        "comment fonctionne le système",
        "expliquez cette implémentation",
        "quelles dépendances sont requises",
        "où trouver les tests",
        "comment exécuter les tests",
        "quel est le but de ce module",
        "quel framework utilise RagLeap Core",
    ],
    "it": [
        "quale framework usa RagLeap",
        "quale API usa RagLeap",
        "come funziona RagLeap",
        "che cos'è RagLeap Core",
        "spiega l'architettura dell'applicazione",
        "come configurare l'applicazione",
        "dove si trova il file di configurazione",
        "quale database usa l'applicazione",
        "come eseguire l'applicazione",
        "cosa fa questa funzione",
        "mostrami la documentazione API",
        "come funziona la ricerca",
        "qual è la lingua predefinita",
        "quale modello viene utilizzato",
        "come installare il pacchetto",
        "perché l'applicazione non funziona",
        "come eseguire il debug di questo errore",
        "quale framework viene utilizzato",
        "come funziona il sistema",
        "spiega questa implementazione",
        "quali dipendenze sono necessarie",
        "dove posso trovare i test",
        "come eseguire i test",
        "qual è lo scopo di questo modulo",
        "RagLeap quale framework usa",
    ],
    "es": [
        "qué framework usa RagLeap",
        "qué API usa RagLeap",
        "cómo funciona RagLeap",
        "qué es RagLeap Core",
        "explica la arquitectura de la aplicación",
        "cómo configurar la aplicación",
        "dónde está el archivo de configuración",
        "qué base de datos usa la aplicación",
        "cómo ejecutar la aplicación",
        "qué hace esta función",
        "muéstrame la documentación de la API",
        "cómo funciona la búsqueda",
        "cuál es el idioma predeterminado",
        "qué modelo se está utilizando",
        "cómo instalar el paquete",
        "por qué falla la aplicación",
        "cómo depurar este error",
        "qué framework se utiliza",
        "cómo funciona el sistema",
        "explica esta implementación",
        "qué dependencias se necesitan",
        "dónde puedo encontrar las pruebas",
        "cómo ejecutar las pruebas",
        "cuál es el propósito de este módulo",
        "qué framework utiliza RagLeap Core",
    ],
    "pt": [
        "qual framework o RagLeap usa",
        "qual API o RagLeap usa",
        "como funciona o RagLeap",
        "o que é o RagLeap Core",
        "explique a arquitetura da aplicação",
        "como configurar a aplicação",
        "onde está o arquivo de configuração",
        "qual banco de dados a aplicação usa",
        "como executar a aplicação",
        "o que essa função faz",
        "mostre a documentação da API",
        "como funciona a pesquisa",
        "qual é o idioma padrão",
        "qual modelo está sendo usado",
        "como instalar o pacote",
        "por que a aplicação falha",
        "como depurar esse erro",
        "qual framework é usado",
        "como funciona o sistema",
        "explique essa implementação",
        "quais dependências são necessárias",
        "onde encontrar os testes",
        "como executar os testes",
        "qual é o objetivo deste módulo",
        "qual framework o RagLeap usa",
    ],
    "de": [
        "welches Framework verwendet RagLeap",
        "welche API verwendet RagLeap",
        "wie funktioniert RagLeap",
        "was ist RagLeap Core",
        "erkläre die Anwendungsarchitektur",
        "wie konfiguriere ich die Anwendung",
        "wo befindet sich die Konfigurationsdatei",
        "welche Datenbank verwendet die Anwendung",
        "wie führe ich die Anwendung aus",
        "was macht diese Funktion",
        "zeige mir die API-Dokumentation",
        "wie funktioniert die Suche",
        "was ist die Standardsprache",
        "welches Modell wird verwendet",
        "wie installiere ich das Paket",
        "warum schlägt die Anwendung fehl",
        "wie kann ich diesen Fehler debuggen",
        "welches Framework wird verwendet",
        "wie funktioniert das System",
        "erkläre diese Implementierung",
        "welche Abhängigkeiten werden benötigt",
        "wo finde ich die Tests",
        "wie führe ich die Tests aus",
        "was ist der Zweck dieses Moduls",
        "wie funktioniert die Anwendung",
    ],
    "ja": [
        "RagLeapはどのフレームワークを使いますか",
        "RagLeapはどのAPIを使いますか",
        "RagLeapはどのように動作しますか",
        "RagLeap Coreとは何ですか",
        "アプリケーションのアーキテクチャを説明してください",
        "アプリケーションをどのように設定しますか",
        "設定ファイルはどこにありますか",
        "アプリケーションはどのデータベースを使いますか",
        "アプリケーションをどう実行しますか",
        "この関数は何をしますか",
        "APIドキュメントを見せてください",
        "検索はどのように動作しますか",
        "デフォルトの言語は何ですか",
        "どのモデルが使われていますか",
        "パッケージをどうインストールしますか",
        "なぜアプリケーションが失敗しますか",
        "このエラーをどうデバッグしますか",
        "どのフレームワークを使っていますか",
        "システムはどのように動作しますか",
        "この実装を説明してください",
        "必要な依存関係は何ですか",
        "テストはどこにありますか",
        "テストをどう実行しますか",
        "このモジュールの目的は何ですか",
        "RagLeapのフレームワークは何ですか",
    ],
    "ko": [
        "RagLeap은 어떤 프레임워크를 사용하나요",
        "RagLeap은 어떤 API를 사용하나요",
        "RagLeap은 어떻게 작동하나요",
        "RagLeap Core가 무엇인가요",
        "애플리케이션 아키텍처를 설명해주세요",
        "애플리케이션을 어떻게 설정하나요",
        "설정 파일은 어디에 있나요",
        "애플리케이션은 어떤 데이터베이스를 사용하나요",
        "애플리케이션을 어떻게 실행하나요",
        "이 함수는 무엇을 하나요",
        "API 문서를 보여주세요",
        "검색은 어떻게 작동하나요",
        "기본 언어가 무엇인가요",
        "어떤 모델을 사용하나요",
        "패키지를 어떻게 설치하나요",
        "애플리케이션이 왜 실패하나요",
        "이 오류를 어떻게 디버깅하나요",
        "어떤 프레임워크를 사용하나요",
        "시스템은 어떻게 작동하나요",
        "이 구현을 설명해주세요",
        "필요한 의존성은 무엇인가요",
        "테스트는 어디에 있나요",
        "테스트를 어떻게 실행하나요",
        "이 모듈의 목적은 무엇인가요",
        "RagLeap 프레임워크는 무엇인가요",
    ],
    "zh": [
        "RagLeap使用什么框架",
        "RagLeap使用什么API",
        "RagLeap如何工作",
        "什么是RagLeap Core",
        "解释应用程序架构",
        "如何配置应用程序",
        "配置文件在哪里",
        "应用程序使用什么数据库",
        "如何运行应用程序",
        "这个函数做什么",
        "给我看看API文档",
        "搜索如何工作",
        "默认语言是什么",
        "使用什么模型",
        "如何安装软件包",
        "为什么应用程序失败",
        "如何调试这个错误",
        "使用什么框架",
        "系统如何工作",
        "解释这个实现",
        "需要哪些依赖",
        "测试在哪里",
        "如何运行测试",
        "这个模块的目的是什么",
        "RagLeap是什么框架",
    ],
}

def _extract_ngrams(text: str) -> list[str]:
    text = f" {text.lower()} "
    return [
        text[i:i + n]
        for n in range(NGRAM_MIN, NGRAM_MAX + 1)
        for i in range(len(text) - n + 1)
    ]

_LANGUAGE_PROFILES = {}
for language, examples in TRAINING_DATA.items():
    counts = Counter()
    for example in examples:
        counts.update(_extract_ngrams(example))
    _LANGUAGE_PROFILES[language] = counts

_VOCABULARY = set()
for profile in _LANGUAGE_PROFILES.values():
    _VOCABULARY.update(profile.keys())

_VOCAB_SIZE = max(len(_VOCABULARY), 1)

class LanguageDetector:
    """
    Language detection service using FastText with a lightweight
    character n-gram fallback for short queries.
    """

    CONFIDENCE_THRESHOLD = CONFIDENCE_THRESHOLD
    DETECTION_LANGUAGES = DETECTION_LANGUAGES
    NGRAM_CONFIDENCE_THRESHOLD = NGRAM_CONFIDENCE_THRESHOLD

    def _ngram_detect(self, text: str) -> tuple[str, float]:
        grams = _extract_ngrams(text)

        if not grams:
            return (DEFAULT_LANGUAGE, 0.0)

        scores = {}

        for language, counts in _LANGUAGE_PROFILES.items():
            total = sum(counts.values())
            score = 0.0

            for gram in grams:
                probability = (
                    counts.get(gram, 0) + NGRAM_ALPHA
                ) / (
                    total + NGRAM_ALPHA * _VOCAB_SIZE
                )
                score += math.log(probability)

            score /= len(grams)
            scores[language] = score

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)

        best_language, best_score = ranked[0]

        if len(ranked) > 1:
            second_score = ranked[1][1]
            margin = best_score - second_score
        else:
            margin = 0.0

        confidence = max(0.0, min(1.0, margin / 2.0 + 0.5))

        return (best_language, confidence)

    def _fasttext_detect(self, text: str) -> tuple[str, float]:
        try:
            result = detect(text)

            if isinstance(result, list):
                result = result[0]

            if isinstance(result, dict):
                language = result.get("lang") or result.get("label")
                confidence = result.get("score", 0.0)
            else:
                language = getattr(result, "lang", None)
                confidence = getattr(result, "score", 0.0)

            language = self._normalize_language_code(language)

            return (language, float(confidence))
        except Exception:
            return (DEFAULT_LANGUAGE, 0.0)

    def detect_language(self, text: str, fallback: str = None) -> tuple[str, float]:
        """
        Detect language of text with confidence score.

        Returns:
            Tuple of (language_code, confidence_score), e.g. ('ta', 0.92)
        """
        if not text:
            default = fallback or DEFAULT_LANGUAGE
            logger.warning(f"Text too short for detection, using default: {default}")
            return (default, 0.0)

        total_chars = max(len(text), 1)
        ascii_letters = sum(1 for c in text if ord(c) < 128 and c.isalpha())
        cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        hiragana_count = sum(1 for c in text if '\u3040' <= c <= '\u309f')
        katakana_count = sum(1 for c in text if '\u30a0' <= c <= '\u30ff')
        hangul_count = sum(1 for c in text if '\uac00' <= c <= '\ud7a3')

        script_chars = cjk_count + hiragana_count + katakana_count + hangul_count
        script_ratio = script_chars / total_chars

        script_infer = None
        if hangul_count > max(cjk_count, hiragana_count + katakana_count) and hangul_count > 0:
            script_infer = 'ko'
        elif (hiragana_count + katakana_count) > 0 and (hiragana_count + katakana_count) > cjk_count:
            script_infer = 'ja'
        elif cjk_count > 0 and (cjk_count / max(ascii_letters + cjk_count, 1)) > 0.25:
            script_infer = 'zh'

        if len(text.strip()) < 10:
            if script_infer:
                return (script_infer, 0.95)
            default = fallback or DEFAULT_LANGUAGE
            logger.warning(f"Text too short for detection, using default: {default}")
            return (default, 0.0)

        cleaned = re.sub(r"Page\s*\d+", " ", text, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b[A-Z]{2,}\d+\b", " ", cleaned)
        cleaned = re.sub(r"[^\w\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7a3\s]", " ", cleaned)
        cleaned = re.sub(r"\d+", " ", cleaned)
        cleaned = re.sub(r"_+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        fast_language, fast_confidence = self._fasttext_detect(cleaned)
        ngram_language, ngram_confidence = self._ngram_detect(cleaned)

        if fast_language == ngram_language:
            detected_code = fast_language
            confidence = fast_confidence
        elif ngram_confidence >= self.NGRAM_CONFIDENCE_THRESHOLD:
            detected_code = ngram_language
            confidence = ngram_confidence
        else:
            detected_code = fast_language
            confidence = fast_confidence

        if self.DETECTION_LANGUAGES and detected_code not in self.DETECTION_LANGUAGES:
            logger.warning(
                f"Detected unsupported language '{detected_code}' with confidence {confidence:.2f}. Falling back to default."
            )
            default = fallback or DEFAULT_LANGUAGE
            return (default, 0.0)

        if script_infer:
            if confidence < self.CONFIDENCE_THRESHOLD or script_ratio >= 0.20:
                logger.info(
                    f"Script-based inference ({script_infer}) preferred over statistical detection "
                    f"({detected_code}) due to script_ratio={script_ratio:.2f} or low confidence={confidence:.2f}"
                )
                return (script_infer, 0.95)

        logger.info(f"Detected language: {detected_code} (confidence: {confidence:.2f})")
        return (detected_code, confidence)

    def detect_query_language(
        self,
        text: str,
        fallback: str = None,
        min_confidence: float = 0.85,
        ascii_ratio_threshold: float = 0.9,
    ) -> tuple[str, float]:
        """Detect language for short user queries with an ASCII heuristic.

        Helps avoid misclassifying mostly-English queries that contain a
        few foreign tokens.
        """
        detected, confidence = self.detect_language(text, fallback=fallback)

        if not text:
            return (detected, confidence)

        text_lower = text.lower()
        context_lang = None
        context_conf = 0.0
        if 'context:' in text_lower:
            try:
                start = text_lower.index('context:') + len('context:')
                end = text_lower.find(')', start)
                snippet = text[start:end].strip() if end != -1 else text[start:].strip()
                if snippet:
                    context_lang, context_conf = self.detect_language(snippet, fallback=fallback)
            except Exception:
                context_lang, context_conf = None, 0.0

        letters = [c for c in text if c.isalpha()]
        if letters:
            ascii_letters = sum(1 for c in letters if ord(c) < 128)
            ascii_ratio = ascii_letters / max(len(letters), 1)
            non_ascii_ratio = 1.0 - ascii_ratio
        else:
            ascii_ratio = 1.0
            non_ascii_ratio = 0.0

        fallback_lang = fallback or DEFAULT_LANGUAGE

        content_terms = re.findall(r"\b\w+\b", text_lower)
        if ENABLE_CONTENT_LANG_DETECTION:
            content_terms = [
                t for t in content_terms
                if t not in CONTENT_LANG_STOP_WORDS and len(t) >= CONTENT_LANG_MIN_TERM_LEN
            ]
        else:
            content_terms = []

        if len(content_terms) >= CONTENT_LANG_MIN_TERMS:
            content_text = " ".join(content_terms)
            try:
                content_lang, content_conf = self._fasttext_detect(content_text)

                if content_lang != fallback_lang:
                    non_ascii_term = any(
                        any(ord(c) > 127 for c in t)
                        for t in content_terms
                    )

                    if non_ascii_term or content_conf >= CONTENT_LANG_MIN_CONFIDENCE:
                        logger.info(
                            f"Query language content override: {detected}->{content_lang} "
                            f"(content_confidence={content_conf:.2f})"
                        )
                        return (content_lang, content_conf)
            except Exception:
                pass

        if context_lang and context_conf >= 0.85:
            logger.info(
                f"Query language context override: {detected}->{context_lang} "
                f"(context_confidence={context_conf:.2f}, non_ascii_ratio={non_ascii_ratio:.2f})"
            )
            return (context_lang, context_conf)

        if context_lang and context_conf >= 0.7 and non_ascii_ratio >= 0.1:
            logger.info(
                f"Query language context override: {detected}->{context_lang} "
                f"(context_confidence={context_conf:.2f}, non_ascii_ratio={non_ascii_ratio:.2f})"
            )
            return (context_lang, context_conf)

        if ascii_ratio >= ascii_ratio_threshold and non_ascii_ratio < 0.1:
            english_markers = (
                'what', 'who', 'when', 'where', 'which', 'how', 'why',
                'is', 'are', 'do', 'does', 'did', 'can', 'could', 'would',
                'should', 'summarize', 'summary', 'explain', 'describe',
                'provide', 'details', 'mention', 'context'
            )
            has_english_marker = any(f" {m} " in f" {text_lower} " for m in english_markers)

            if detected != fallback_lang and has_english_marker and confidence < min_confidence:
                logger.info(
                    f"Query language heuristic override: {detected}->{fallback_lang} "
                    f"(confidence={confidence:.2f}, ascii_ratio={ascii_ratio:.2f}, english_markers={has_english_marker})"
                )
                return (fallback_lang, confidence)

        return (detected, confidence)

    def detect_language_simple(self, text: str, fallback: str = None) -> str:
        """Simplified detection returning only the language code."""
        language, _ = self.detect_language(text, fallback)
        return language

    def is_supported_language(self, lang_code: str) -> bool:
        """Check if language code is supported."""
        return (not self.DETECTION_LANGUAGES) or (lang_code in self.DETECTION_LANGUAGES)

    def _normalize_language_code(self, lang_code: str) -> str:
        """Normalize language codes like zh-cn -> zh, pt-br -> pt."""
        if not lang_code:
            return lang_code
        code = lang_code.strip().lower().replace('_', '-')
        aliases = {
            'zh-cn': 'zh',
            'zh-tw': 'zh',
            'zh-hk': 'zh',
            'pt-br': 'pt',
            'pt-pt': 'pt',
        }
        if code in aliases:
            return aliases[code]
        if '-' in code:
            return code.split('-')[0]
        return code

    def detect_with_manual_override(self, text: str, user_specified_lang: str = None) -> tuple[str, float]:
        """Detect language with an optional user-provided override, which
        takes precedence with full confidence if supported."""
        if user_specified_lang:
            if self.is_supported_language(user_specified_lang):
                logger.info(f"Using user-specified language: {user_specified_lang}")
                return (user_specified_lang, 1.0)
            else:
                logger.warning(
                    f"User specified unsupported language: {user_specified_lang}. Falling back to detection."
                )
        return self.detect_language(text)


# Singleton instance, matching production's pattern
language_detector = LanguageDetector()