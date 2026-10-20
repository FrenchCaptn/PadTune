"""Traduction de l'interface : tr("texte français", **valeurs) -> texte dans la langue choisie.

Les textes sources sont en français ; les traductions sont dans translations.py.
"""
from __future__ import annotations

LANGS = {
    "fr": "Français",
    "en": "English",
    "es": "Español",
    "de": "Deutsch",
    "it": "Italiano",
    "pt": "Português",
}
DEFAULT = "en"          # langue de repli si celle du système n'est pas disponible

_lang = "fr"
_table: dict = {}


def set_language(code: str) -> str:
    global _lang, _table
    code = (code or "").lower()[:2]
    if code not in LANGS:
        code = DEFAULT
    _lang = code
    if code == "fr":
        _table = {}
    else:
        from translations import TRANSLATIONS
        _table = TRANSLATIONS.get(code, {})
    return code


def language() -> str:
    return _lang


def tr(text: str, **values) -> str:
    out = _table.get(text, text)
    if values:
        try:
            return out.format(**values)
        except (KeyError, IndexError, ValueError):
            return text.format(**values)
    return out


def system_language() -> str:
    try:
        from PySide6.QtCore import QLocale
        code = QLocale.system().name()[:2].lower()
    except Exception:  # noqa: BLE001
        import locale
        code = (locale.getlocale()[0] or "")[:2].lower()
    return code if code in LANGS else DEFAULT
