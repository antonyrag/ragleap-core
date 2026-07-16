"""
Language Detection Service for RagLeap Core
Ported from production's multilingual/language_detector.py — single-tenant,
Django settings replaced with .env vars, dead/unreachable code removed.
"""
import os
import re
import logging

import langdetect
from langdetect import detect_langs

logger = logging.getLogger(__name__)

DEFAULT_LANGUAGE = os.environ.get("DEFAULT_LANGUAGE", "en")
CONFIDENCE_THRESHOLD = float(os.environ.get("LANGUAGE_DETECTION_CONFIDENCE_THRESHOLD", "0.7"))

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


class LanguageDetector:
    """
    Language detection service using the langdetect library, with
    script-based heuristics (CJK/Hangul/Kana) and query-specific
    overrides for short, mostly-English queries with foreign tokens.
    """

    CONFIDENCE_THRESHOLD = CONFIDENCE_THRESHOLD
    DETECTION_LANGUAGES = DETECTION_LANGUAGES

    def detect_language(self, text: str, fallback: str = None) -> tuple[str, float]:
        """
        Detect language of text with confidence score.

        Returns:
            Tuple of (language_code, confidence_score), e.g. ('ta', 0.92)
        """
        if not text or len(text.strip()) < 10:
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

        cleaned = re.sub(r"Page\s*\d+", " ", text, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b[A-Z]{2,}\d+\b", " ", cleaned)
        cleaned = re.sub(r"[^\w\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7a3\s]", " ", cleaned)
        cleaned = re.sub(r"\d+", " ", cleaned)
        cleaned = re.sub(r"_+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        try:
            lang_probs = detect_langs(cleaned) if cleaned else []
        except Exception:
            lang_probs = []

        if not lang_probs:
            default = fallback or DEFAULT_LANGUAGE
            if script_infer and script_ratio >= 0.10:
                return (script_infer, 0.95)
            return (default, 0.0)

        top_lang = lang_probs[0]
        detected_code = self._normalize_language_code(top_lang.lang)
        confidence = top_lang.prob

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

        if confidence < self.CONFIDENCE_THRESHOLD:
            logger.warning(
                f"Low confidence detection: {detected_code} ({confidence:.2f}). Using default: {fallback or DEFAULT_LANGUAGE}"
            )
            default = fallback or DEFAULT_LANGUAGE
            return (default, confidence)

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
                lang_probs = detect_langs(content_text)
                if lang_probs:
                    top_lang = lang_probs[0]
                    content_lang = self._normalize_language_code(top_lang.lang)
                    if content_lang != fallback_lang:
                        non_ascii_term = any(any(ord(c) > 127 for c in t) for t in content_terms)
                        if non_ascii_term or top_lang.prob >= CONTENT_LANG_MIN_CONFIDENCE:
                            logger.info(
                                f"Query language content override: {detected}->{content_lang} "
                                f"(content_confidence={top_lang.prob:.2f})"
                            )
                            return (content_lang, top_lang.prob)
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
