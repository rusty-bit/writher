"""Post-processing: replace spoken symbol names with their character equivalents.

Applied to every dictation transcription before injecting text.

Pipeline:
1. Multi-word spoken phrases → single character  ("forward slash" → "/")
2. Single-word spoken names  → single character  ("dash" → "-")
3. Number words              → digits            ("one" → "1")
4. Collapse spaces between adjacent single-character tokens
   so spelled-out "W H / F A T" → "WH/FAT".
5. Remove spaces around code-separator symbols sandwiched between non-space chars
   so "WH / FIT" (from "WH forward slash FIT") also becomes "WH/FIT".
"""

import re

# (compiled pattern, replacement) — multi-word patterns listed before single-word.
_SUBS = [
    # ── Multi-word ────────────────────────────────────────────────────────────
    (re.compile(r"\bforward slash\b",     re.IGNORECASE), "/"),
    (re.compile(r"\bback slash\b",        re.IGNORECASE), "\\\\"),
    (re.compile(r"\bbackslash\b",         re.IGNORECASE), "\\\\"),
    (re.compile(r"\bdouble colon\b",      re.IGNORECASE), "::"),
    (re.compile(r"\bdouble quote\b",      re.IGNORECASE), '"'),
    (re.compile(r"\bsingle quote\b",      re.IGNORECASE), "'"),
    (re.compile(r"\bopen bracket\b",      re.IGNORECASE), "("),
    (re.compile(r"\bclose bracket\b",     re.IGNORECASE), ")"),
    (re.compile(r"\bleft bracket\b",      re.IGNORECASE), "("),
    (re.compile(r"\bright bracket\b",     re.IGNORECASE), ")"),
    (re.compile(r"\bopen parenthesis\b",  re.IGNORECASE), "("),
    (re.compile(r"\bclose parenthesis\b", re.IGNORECASE), ")"),
    (re.compile(r"\bopen curly\b",        re.IGNORECASE), "{"),
    (re.compile(r"\bclose curly\b",       re.IGNORECASE), "}"),
    (re.compile(r"\bleft curly\b",        re.IGNORECASE), "{"),
    (re.compile(r"\bright curly\b",       re.IGNORECASE), "}"),
    (re.compile(r"\bopen square\b",       re.IGNORECASE), "["),
    (re.compile(r"\bclose square\b",      re.IGNORECASE), "]"),
    (re.compile(r"\bleft square\b",       re.IGNORECASE), "["),
    (re.compile(r"\bright square\b",      re.IGNORECASE), "]"),
    (re.compile(r"\bless than\b",         re.IGNORECASE), "<"),
    (re.compile(r"\bgreater than\b",      re.IGNORECASE), ">"),
    (re.compile(r"\bexclamation mark\b",  re.IGNORECASE), "!"),
    (re.compile(r"\bquestion mark\b",     re.IGNORECASE), "?"),
    (re.compile(r"\bat sign\b",           re.IGNORECASE), "@"),
    (re.compile(r"\bhash sign\b",         re.IGNORECASE), "#"),
    (re.compile(r"\bpound sign\b",        re.IGNORECASE), "#"),
    (re.compile(r"\bpercent sign\b",      re.IGNORECASE), "%"),
    (re.compile(r"\bdollar sign\b",       re.IGNORECASE), "$"),
    (re.compile(r"\bvertical bar\b",      re.IGNORECASE), "|"),
    (re.compile(r"\bequal sign\b",        re.IGNORECASE), "="),
    (re.compile(r"\bequals sign\b",       re.IGNORECASE), "="),
    (re.compile(r"\bplus sign\b",         re.IGNORECASE), "+"),
    (re.compile(r"\bminus sign\b",        re.IGNORECASE), "-"),
    (re.compile(r"\bnew line\b",          re.IGNORECASE), "\n"),
    (re.compile(r"\bnew paragraph\b",     re.IGNORECASE), "\n\n"),
    # ── Single-word ───────────────────────────────────────────────────────────
    (re.compile(r"\bslash\b",      re.IGNORECASE), "/"),
    (re.compile(r"\bsemicolon\b",  re.IGNORECASE), ";"),
    (re.compile(r"\bcolon\b",      re.IGNORECASE), ":"),
    (re.compile(r"\bunderscore\b", re.IGNORECASE), "_"),
    (re.compile(r"\bdash\b",       re.IGNORECASE), "-"),
    (re.compile(r"\bhyphen\b",     re.IGNORECASE), "-"),
    (re.compile(r"\bminus\b",      re.IGNORECASE), "-"),
    (re.compile(r"\bplus\b",       re.IGNORECASE), "+"),
    (re.compile(r"\basterisk\b",   re.IGNORECASE), "*"),
    (re.compile(r"\btilde\b",      re.IGNORECASE), "~"),
    (re.compile(r"\bcaret\b",      re.IGNORECASE), "^"),
    (re.compile(r"\bpercent\b",    re.IGNORECASE), "%"),
    (re.compile(r"\bampersand\b",  re.IGNORECASE), "&"),
    (re.compile(r"\bpipe\b",       re.IGNORECASE), "|"),
    (re.compile(r"\bbacktick\b",   re.IGNORECASE), "`"),
    # ── Number words → digits ─────────────────────────────────────────────────
    (re.compile(r"\bzero\b|\bnought\b", re.IGNORECASE), "0"),
    (re.compile(r"\bone\b",             re.IGNORECASE), "1"),
    (re.compile(r"\btwo\b",             re.IGNORECASE), "2"),
    (re.compile(r"\bthree\b",           re.IGNORECASE), "3"),
    (re.compile(r"\bfour\b",            re.IGNORECASE), "4"),
    (re.compile(r"\bfive\b",            re.IGNORECASE), "5"),
    (re.compile(r"\bsix\b",             re.IGNORECASE), "6"),
    (re.compile(r"\bseven\b",           re.IGNORECASE), "7"),
    (re.compile(r"\beight\b",           re.IGNORECASE), "8"),
    (re.compile(r"\bnine\b",            re.IGNORECASE), "9"),
]

# Character class of symbols that act as code separators (no surrounding spaces).
_SYM = r'[/\\:;_@#$%&|~^*+=<>!?()\[\]{}\'\"\-]'

# Remove spaces immediately BEFORE a code-separator symbol (when preceded by non-space).
_BEFORE_SYM  = re.compile(r'(?<=\S) +(?=' + _SYM + r')')
# Remove spaces immediately AFTER a code-separator symbol (when followed by non-space).
_AFTER_SYM   = re.compile(r'(?<=' + _SYM + r') +(?=\S)')
# Remove spaces between adjacent digit characters (handles digits stuck to symbols).
_DIGIT_BRIDGE = re.compile(r'(?<=\d) +(?=\d)')


def _split_embedded_symbols(text: str) -> str:
    """Expand tokens that embed a symbol so single-char collapse can handle them.

    "h/f"     → "h / f"      → collapse → "h/f"  (merges with neighbours)
    "t/01234" → "t / 0 1 2 3 4" → collapse → "t/01234"
    "WH/FIT"  → "W H / F I T"  → collapse → "WH/FIT"
    Plain words ("hello", "WH", "01274") are left unchanged (no embedded symbol).
    """
    _sym_re = re.compile(_SYM)
    parts = []
    for token in text.split(' '):
        if len(token) > 1 and _sym_re.search(token):
            parts.append(' '.join(token))
        else:
            parts.append(token)
    return ' '.join(parts)


def _collapse_single_chars(text: str) -> str:
    """Merge runs of space-separated single-character tokens.

    Each space in the text separates tokens. A token of length 1 (any character —
    letter, digit, or symbol) is a 'single char'. Consecutive single chars are
    joined without spaces; multi-char words break the run.

    Examples:
        "W H F A T"        → "WHFAT"
        "1 2 3 / 4 5"      → "123/45"   (/ is one char)
        "hello W H world"  → "hello WH world"
    """
    tokens = text.split(' ')
    result: list[str] = []
    buf: list[str] = []
    for token in tokens:
        if len(token) == 1:
            buf.append(token)
        else:
            if buf:
                result.append(''.join(buf))
                buf = []
            result.append(token)
    if buf:
        result.append(''.join(buf))
    return ' '.join(result)


def apply_symbols(text: str) -> str:
    """Replace spoken symbol/number names with character equivalents, then compact."""
    for pattern, replacement in _SUBS:
        text = pattern.sub(replacement, text)
    text = _split_embedded_symbols(text)
    text = _collapse_single_chars(text)
    # Remove spaces around code-separator symbols between non-space chars.
    # Two passes: before-symbol then after-symbol (order matters for "A / B" → "A/B").
    text = _BEFORE_SYM.sub('', text)
    text = _AFTER_SYM.sub('', text)
    text = _DIGIT_BRIDGE.sub('', text)
    return text.strip()
