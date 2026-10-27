"""Split order text into lines and pull the quantity and unit out of each line."""
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

UNITS = {
    "lb": "LB", "lbs": "LB", "pound": "LB", "pounds": "LB", "#": "LB",
    "cs": "CS", "case": "CS", "cases": "CS", "cse": "CS",
    "ea": "EA", "each": "EA", "bunch": "EA", "bunches": "EA", "bu": "EA",
    "pint": "EA", "pints": "EA", "pt": "EA",
}
NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "ten": 10, "twelve": 12, "dozen": 12}
FILLER = {"of", "x", "a", "an", "please", "pls", "plz"}
STOPWORDS = {"on", "the", "and", "with"}  # ignored when comparing a line with a catalog name
TOKEN = re.compile(r"\d+(?:\.\d+)?|[^\W\d_]+|#")


@dataclass(frozen=True)
class OrderLine:
    text: str         # the line as the chef wrote it
    qty: float
    unit: str | None  # CS, LB or EA if the chef named one
    item: str         # what's left once quantity, unit and filler words are removed


def split_order(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[\n,;]+", text) if part.strip()]


def tokens(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in plain if not unicodedata.combining(c))  # jalapeño -> jalapeno
    return TOKEN.findall(plain)


def parse_line(text: str) -> OrderLine:
    qty, unit, rest = None, None, []
    for i, word in enumerate(tokens(text)):
        if qty is None and word[0].isdigit():
            qty = float(word)
        elif qty is None and i == 0 and word in NUMBER_WORDS:
            qty = float(NUMBER_WORDS[word])
        elif unit is None and word in UNITS:
            unit = UNITS[word]
        elif word not in FILLER:
            rest.append(word)
    return OrderLine(text.strip(), qty if qty is not None else 1.0, unit, " ".join(rest))


def similarity(item: str, name: str) -> float:
    """How closely the words of an order line match a catalog name, from 0 to 1.

    Mostly asks whether each word in the line has a close match in the name, so
    "romas" matches "Tomatoes, roma". A smaller share asks the reverse, so plain
    "kale" prefers "Kale, green" over "Kale, lacinato (dino)".
    """
    a, b = _content_words(item), _content_words(name)
    if not a or not b:
        return 0.0

    def best(word: str, pool: list[str]) -> float:
        return max(SequenceMatcher(None, word, other).ratio() for other in pool)

    covered = sum(best(w, b) for w in a) / len(a)
    reverse = sum(best(w, a) for w in b) / len(b)
    return 0.8 * covered + 0.2 * reverse


def shares_keyword(item: str, name: str, cutoff: float = 0.8) -> bool:
    """Whether any word in the line closely matches any word in the catalog name."""
    names = _content_words(name)
    return any(SequenceMatcher(None, word, other).ratio() >= cutoff
               for word in _content_words(item) for other in names)


def _content_words(text: str) -> list[str]:
    return [w for w in tokens(text) if w not in STOPWORDS]
