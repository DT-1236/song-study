"""Predicate groups: a conjugated verb, adjective, or 形状詞 together with the
grammar attached to it, glossed as one unit (欲し/てる/ん/だ/って ->
欲してるんだって).

The rule is school grammar's bunsetsu (文節): one independent word (自立語)
followed by any dependent words (付属語), which are particles (助詞) and
auxiliaries (助動詞). Sudachi's part-of-speech tags follow UniDic's, which
already tag spoken contractions (てる, ちゃう, とく, なきゃ) as 助動詞. One
extension for learners: a helper verb after て/で (補助動詞: いる, しまう,
みる, ...) and a helper ない stay in the group, where strict school grammar
would start a new bunsetsu at them (見て|いる).
"""

from __future__ import annotations

from typing import Optional

_HEAD_POS = frozenset({"動詞", "形容詞", "形状詞"})

# Short explanations for grammar words and helper verbs in a group, keyed by
# Sudachi's normalized_form (ん as a negative is ず, ん as explanatory is の).
_GRAMMAR_NOTES: dict[str, str] = {
    # Auxiliaries (助動詞)
    "た": "past tense or completed action (たら: if/when)",
    "だ": "copula: is (だろう: probably; なら: if; で: and/being)",
    "です": "polite copula: is (でしょう: probably)",
    "ます": "polite verb ending",
    "ない": "negation: not",
    "ず": "negation: not (ぬ/ん in speech)",
    "まい": "won't, or probably not",
    "たい": "want to",
    "たがる": "(someone else) wants to",
    "れる": "passive, can, or respectful form",
    "られる": "passive, can, or respectful form",
    "せる": "make or let (someone) do",
    "させる": "make or let (someone) do",
    "てる": "short for ている: is doing, or the resulting state",
    "ちゃう": "short for てしまう: end up doing, or do completely",
    "ちまう": "short for てしまう: end up doing, or do completely",
    "とく": "short for ておく: do in advance, or leave as is",
    "てく": "short for ていく: go on doing from now",
    "らしい": "seems, apparently",
    "べし": "should, ought to",
    "やがる": "(contemptuous) has the nerve to",
    # Stems of そうだ/ようだ/みたいだ (形状詞-助動詞語幹)
    "そう": "looks like, or I hear that (after a plain form)",
    "よう": "seems, or like",
    "みたい": "seems, or like (casual)",
    # Particles (助詞)
    "て": "and, then; links to what follows (ちゃ: short for ては)",
    "で": "and, then; links to what follows",
    "ば": "if",
    "たら": "if, when",
    "ても": "even if",
    "けれど": "but, although",
    "から": "because, or from",
    "ので": "because",
    "のに": "although, even though",
    "し": "and also (listing reasons)",
    "たり": "doing things like (listing actions)",
    "ながら": "while",
    "の": "of, 's; or makes a clause a noun (のだ/んだ explains)",
    "って": "quoting: says that, or I hear that",
    "と": "and, with; quoting: that; or when, if",
    "に": "to, at, in, for",
    "を": "object marker",
    "が": "subject marker, or but",
    "は": "topic marker, or contrast",
    "も": "also, even",
    "へ": "toward, to",
    "や": "and (among others)",
    "より": "than, from",
    "まで": "until, even",
    "ほど": "to the extent that",
    "くらい": "about, to the degree that",
    "だけ": "only",
    "ばかり": "only, or just did",
    "しか": "nothing but (with a negative)",
    "こそ": "precisely, it is ... that",
    "よ": "sentence-final: asserts or informs",
    "ね": "sentence-final: seeks agreement, softens",
    "な": "sentence-final: don't (after a plain verb), or musing",
    "か": "question marker, or",
    "わ": "sentence-final: soft emphasis",
    "ぞ": "sentence-final: strong emphasis",
    "ぜ": "sentence-final: casual emphasis",
    "さ": "sentence-final: casual assertion",
    "じゃん": "casual: isn't it, you know",
    # Helper verbs and adjectives (補助動詞/補助形容詞)
    "居る": "ている: is doing, or the resulting state",
    "有る": "てある: has been done and left that way",
    "仕舞う": "てしまう: end up doing, or do completely",
    "見る": "てみる: try doing",
    "おく": "ておく: do in advance, or leave as is",
    "置く": "ておく: do in advance, or leave as is",
    "行く": "ていく: go on doing from now",
    "来る": "てくる: has been doing up to now, or go and do",
    "貰う": "てもらう: have (someone) do for you",
    "呉れる": "てくれる: (someone) does for you",
    "上げる": "てあげる: do for (someone)",
    "遣る": "てやる: do for (someone), or do defiantly",
    "見せる": "てみせる: show you can, or will definitely do",
    "回る": "て回る: go around doing",
    "欲しい": "てほしい: want (someone) to do",
    "無い": "ない: not",
    "為る": "する: makes the word before it a verb",
}


def grammar_note(normalized_form: str, part_of_speech) -> str:
    """A short explanation of what a grammar word or helper verb in a
    predicate group adds to it."""
    note = _GRAMMAR_NOTES.get(normalized_form)
    if note is not None:
        return note
    if part_of_speech[0] == "助詞":
        return "particle"
    if part_of_speech[0] == "接尾辞":
        return "suffix"
    return "grammatical ending"


def _is_dependent(part_of_speech) -> bool:
    # そう/よう/みたい of そうだ/ようだ/みたいだ are tagged 形状詞-助動詞語幹.
    return part_of_speech[0] in ("助詞", "助動詞", "接尾辞") or tuple(part_of_speech[:2]) == ("形状詞", "助動詞語幹")


def is_helper_predicate(previous, token) -> bool:
    """Whether `token` is a helper verb or adjective attached to `previous`:
    いる after て in 見ている, or ない in 高くない and 好きじゃない."""
    part_of_speech = token.part_of_speech
    # 非自立可能 only means a word *can* be a helper: the 見 of 見ちゃった
    # has it too, so what comes before decides.
    if part_of_speech[0] not in ("動詞", "形容詞") or part_of_speech[1] != "非自立可能":
        return False
    if token.normalized_form == "無い":
        return True
    # normalized_form, so ちゃ (short for ては) counts as て.
    return previous.part_of_speech[1] == "接続助詞" and previous.normalized_form in ("て", "で")


def is_helper_verb(token) -> bool:
    """Whether an attached `token` is a helper verb or adjective with a
    dictionary meaning of its own, rather than pure grammar."""
    return token.part_of_speech[0] in ("動詞", "形容詞") and token.normalized_form != "為る"


def attached_end(tokens, start: int) -> int:
    """The index just past the grammar attached to a predicate ending at
    `start - 1`: `start` itself when nothing is attached."""
    end = start
    while end < len(tokens) and (
        _is_dependent(tokens[end].part_of_speech) or is_helper_predicate(tokens[end - 1], tokens[end])
    ):
        end += 1
    return end


def predicate_group_end(tokens, start: int) -> Optional[int]:
    """The index just past the predicate group headed by `tokens[start]`, or
    None if it doesn't head one of two or more tokens. A noun directly
    followed by する heads one too (勉強してた)."""
    head = tokens[start].part_of_speech
    end = start + 1
    if (
        head[0] == "名詞"
        and end < len(tokens)
        and tokens[end].part_of_speech[0] == "動詞"
        and tokens[end].normalized_form == "為る"
    ):
        end += 1
    elif head[0] not in _HEAD_POS or head[1] == "助動詞語幹":
        return None
    end = attached_end(tokens, end)
    return end if end - start > 1 else None


def find_predicate_groups(records) -> list[range]:
    """The index range of every predicate group in `records`, in order,
    setting each member's phrase_start_position to its head's position."""
    groups = []
    i = 0
    while i < len(records):
        end = predicate_group_end(records, i)
        if end is None:
            i += 1
            continue
        for record in records[i:end]:
            record.phrase_start_position = records[i].position
        groups.append(range(i, end))
        i = end
    return groups
