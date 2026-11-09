"""Conservative suggestions: combine only disjoint edits to a common ancestor."""

from difflib import SequenceMatcher


def simple_merge(base, left, right):
    # Avoid ambiguous repeated text and expensive character matching on large blocks.
    if max(map(len, (base, left, right))) > 4000:
        return None
    if left == right:
        return left
    if left == base:
        return right
    if right == base:
        return left
    changes = []
    for text in (left, right):
        edits = [(a0, a1, text[b0:b1]) for tag, a0, a1, b0, b1 in SequenceMatcher(None, base, text, autojunk=False).get_opcodes() if tag != "equal"]
        for start, end, value in edits:
            duplicate = False
            for old_start, old_end, old_value in changes:
                if (start, end, value) == (old_start, old_end, old_value):
                    duplicate = True
                    break
                if max(start, old_start) < min(end, old_end) or (start == end and old_start <= start <= old_end) or (old_start == old_end and start <= old_start <= end):
                    return None
            if not duplicate:
                changes.append((start, end, value))
    result = base
    for start, end, value in sorted(changes, reverse=True):
        result = result[:start] + value + result[end:]
    return result
