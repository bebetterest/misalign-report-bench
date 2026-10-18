"""A small local search index with query-dependent results, not a route giveaway."""

from copy import deepcopy
import re

STOP_WORDS = frozenset("a an the and or for of in on to from with find get give what is was public source sources task please use".split())


def terms(text):
    return {
        word[:-1] if len(word) > 4 and word.endswith("s") else word
        for word in re.findall(r"[a-z0-9]+", text.casefold())
        if word not in STOP_WORDS and len(word) > 1
    }


def search_index(entries, query):
    wanted = terms(query)
    ranked = []
    for index, entry in enumerate(entries):
        haystack = " ".join(
            str(entry.get(key, ""))
            for key in ("title", "url", "snippet", "search_terms")
        )
        score = len(wanted & terms(haystack))
        if score:
            result = deepcopy(entry)
            result.pop("search_terms", None)
            ranked.append((-score, index, result))
    return [result for _, _, result in sorted(ranked)]
