"""Application translations, defaulting to English."""

from . import en, es, ja, ko, zh_tw
from .messages import ROWS


LANGUAGES = {
    "en": "English",
    "zh_CN": "简体中文",
    "zh_TW": "繁體中文",
    "ja": "日本語",
    "ko": "한국어",
    "es": "Español",
}
_CATALOGS = {
    "en": en.MESSAGES,
    "zh_CN": {},
    "zh_TW": zh_tw.MESSAGES,
    "ja": ja.MESSAGES,
    "ko": ko.MESSAGES,
    "es": es.MESSAGES,
}
_language = "en"

for index, language in enumerate(("en", "zh_TW", "ja", "ko", "es"), 1):
    _CATALOGS[language].update({row[0]: row[index] for row in ROWS})


def initialize(saved_language: object = None) -> str:
    global _language
    _language = (
        saved_language
        if isinstance(saved_language, str) and saved_language in LANGUAGES
        else "en"
    )
    return _language


def current_language() -> str:
    return _language


def register_messages(language: str, messages: dict[str, str]) -> None:
    _CATALOGS[language].update(messages)


class TranslatedText(str):
    """A displayed string retaining its source rather than user text."""

    def __new__(cls, source: str, args: tuple[object, ...] = (), parts: tuple[object, ...] = ()):
        instance = super().__new__(cls, cls._render(source, args, parts))
        instance.source = source
        instance.args = args
        instance.parts = parts
        return instance

    @staticmethod
    def _render(source: str, args: tuple[object, ...], parts: tuple[object, ...]) -> str:
        if parts:
            return "".join(render_text(part) for part in parts)
        value = (
            source if _language == "zh_CN"
            else _CATALOGS[_language].get(source, en.MESSAGES.get(source, source))
        )
        values = tuple(render_text(value) if isinstance(value, TranslatedText) else value for value in args)
        return value.format(*values) if args else value

    def render(self) -> str:
        return self._render(self.source, self.args, self.parts)

    def __add__(self, other: str) -> str:
        if not isinstance(other, str):
            return NotImplemented
        return TranslatedText("", parts=(self, other))

    def __radd__(self, other: str) -> str:
        if not isinstance(other, str):
            return NotImplemented
        return TranslatedText("", parts=(other, self))


def render_text(value: object) -> str:
    return value.render() if isinstance(value, TranslatedText) else str(value)


def tr(source: str, *args: object) -> str:
    return TranslatedText(source, args)
