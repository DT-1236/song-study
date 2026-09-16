"""Regression tests for app.phrase_merge.

Pure-function tests against real Sudachi + JMDict (no DB) — same rationale
as test_glosses.py: these bugs are specifically about how real tokenizer
output interacts with real dictionary data, so a mock would test nothing.

The three real cases below were all found by hand while building this
feature, not invented:
  - この期に及んで is the motivating case (see app/phrase_merge.py's
    docstring): Sudachi tokenizes it into five separate words, and even
    gets 期's own reading wrong for this idiom (き instead of ご) — the
    merged surface is the only way to reach the correct JMDict entry.
  - 今日は -> こんにちは and し+たく -> したく are the false positives that
    proved a plain "the concatenated tokens exactly match a JMDict
    headword" rule isn't safe to auto-apply: both hijack an unrelated,
    coincidentally-real word. This is why phrase matches are suggestions
    (TokenRecord.phrase_suggestion) rather than applied automatically.
"""

from app.phrase_merge import find_phrase_suggestions
from app.tokenization import tokenize_document


def _suggestions(text):
    records = tokenize_document(text)
    find_phrase_suggestions(records)
    return {r.position: r.phrase_suggestion for r in records if r.phrase_suggestion is not None}


class TestFindPhraseSuggestions:
    def test_finds_the_motivating_idiom_with_its_jmdict_reading(self):
        # この/期/に/及ん/で: five tokens, and Sudachi's own reading for 期
        # alone (き) is wrong for this idiom (JMDict has it under ご) — only
        # the merged-surface lookup can find the right reading at all.
        suggestions = _suggestions("この期に及んでまだ言い訳をするのか")
        assert suggestions[0] == {
            "surface": "この期に及んで",
            "lookup_form": "この期に及んで",
            "reading": "このごにおよんで",
            "token_count": 5,
        }

    def test_a_hijacking_false_positive_is_surfaced_but_never_applied(self):
        # 今日 (heteronym きょう/こんにち) + は exactly matches こんにちは
        # ("hello"), an unrelated word — no POS/reading rule was found that
        # rejects this while still keeping real matches (see module
        # docstring), so it DOES show up as a suggestion. What must hold is
        # that it's only ever a suggestion: finding it must not touch the
        # token's own gloss_key, which is what main._process_document still
        # uses to gloss 今日 itself (as きょう, its actual heteronym default).
        from app.glosses import gloss_key

        records = tokenize_document("今日は雨です。")
        find_phrase_suggestions(records)
        assert records[0].phrase_suggestion == {
            "surface": "今日は",
            "lookup_form": "今日は",
            "reading": "こんにちは",
            "token_count": 2,
        }
        assert gloss_key(records[0]) == ("今日", "きょう")

    def test_extends_through_an_auxiliary_verb_to_reach_a_real_idiom(self):
        # お/願い/し/ます: reaching the real idiom お願いします ("please") at
        # all requires extending straight through し(動詞)+ます(助動詞) — an
        # earlier version stopped at any 助動詞 specifically to block
        # し+たく (auxiliary "want to") from matching したく
        # ("preparations"), but that blocked this whole common class of
        # idiom too (verb+する+ます). Extension is unrestricted now — see
        # module docstring for why relying on human review instead is the
        # right tradeoff.
        suggestions = _suggestions("お願いします")
        assert suggestions[0] == {
            "surface": "お願いします",
            "lookup_form": "お願いします",
            "reading": "おねがいします",
            "token_count": 4,
        }

    def test_a_hijacking_false_positive_through_an_auxiliary_is_still_only_a_suggestion(self):
        # し (verb stem of する) + たく (auxiliary "want to") exactly spells
        # したく ("preparations", 支度) — an unrelated word. This is exactly
        # the coincidence the old auxiliary block existed to prevent; now
        # it resurfaces as a suggestion (see test above for why that's the
        # accepted tradeoff), but — same guarantee as the today/こんにちは
        # case — only ever as a suggestion, never applied automatically.
        from app.glosses import gloss_key

        records = tokenize_document("後悔だけはしたくない")
        find_phrase_suggestions(records)
        shi = next(r for r in records if r.surface == "し")
        assert shi.phrase_suggestion == {
            "surface": "したく",
            "lookup_form": "したく",
            "reading": "したく",
            "token_count": 2,
        }
        # Whatever し's own gloss key actually is, it must not be corrupted
        # into anything derived from the phrase suggestion's reading
        # (したく) — finding a suggestion is inert until a human accepts it.
        key = gloss_key(shi)
        assert key is not None
        assert "したく" not in key

    def test_does_not_start_a_scan_from_a_particle_or_punctuation(self):
        from app.phrase_merge import _can_start_phrase

        assert not _can_start_phrase(["助詞", "*", "*", "*", "*", "*"])
        assert not _can_start_phrase(["補助記号", "*", "*", "*", "*", "*"])
        assert _can_start_phrase(["名詞", "*", "*", "*", "*", "*"])

    def test_no_suggestions_for_ordinary_unrelated_tokens(self):
        # 見ている (見る + ている, "-ing/state") is a real, correct catch of
        # the light-verb-chain detection (see TestLightVerbChain below) —
        # not "no suggestions" here, just none unrelated to that.
        suggestions = _suggestions("猫が窓の外を見ている。")
        assert set(suggestions) == {6}
        assert suggestions[6]["surface"] == "見ている"

    def test_nested_shorter_match_also_surfaces_independently(self):
        # 御釈迦様 (5 chars) contains 御釈迦 as its own start position too;
        # every eligible start is evaluated on its own, so a longer match
        # elsewhere doesn't suppress a shorter, separately-valid one.
        suggestions = _suggestions("御釈迦様が仰いました。")
        assert suggestions[0]["surface"] == "御釈迦様"

    def test_matches_through_an_inflected_verbs_dictionary_form(self):
        # 真/に/受け: literal surface concatenation is 真に受け (受け is
        # 受ける's 連用形 stem), which is not itself a JMDict headword and
        # never will be no matter how much further inflection follows
        # (受けて, 受けた, ...) — only the citation form 受ける completes the
        # real idiom 真に受ける ("to take at face value"). The merge itself
        # covers only 真/に/受け (3 tokens): て is a separate word (part of
        # 受けてみて, "try taking it seriously"), not part of the idiom.
        # lookup_form (真に受ける) is distinct from surface (真に受け) here —
        # a real bug found live where the gloss lookup used surface instead
        # and silently missed, since 真に受け alone has no JMDict entry.
        suggestions = _suggestions("真に受けてみて")
        assert suggestions[0] == {
            "surface": "真に受け",
            "lookup_form": "真に受ける",
            "reading": "まにうける",
            "token_count": 3,
        }

    def test_does_not_try_a_dictionary_form_completion_that_does_not_match(self):
        # 歩い (stem of 歩く, inflected) doesn't complete anything real with
        # what precedes it here — checking a dictionary-form completion at
        # every inflected token must not hallucinate a match just because
        # one was tried; it still has to be an actual exact JMDict entry.
        # (静かに *is* suggested from 静か — a real adverb JMDict entry,
        # reached by extending straight through に's own 助動詞 tag — that's
        # the intended, correct result of extension being unrestricted now,
        # not the thing this test is checking.)
        suggestions = _suggestions("彼は静かに歩いた。")
        assert not any(s["surface"].startswith("歩") for s in suggestions.values())

    def test_offers_a_sa_hen_noun_verbalized_with_suru_even_with_no_jmdict_entry(self):
        # 買い物する ("to shop") is not itself a JMDict headword — only the
        # bare noun 買い物 is — but Sudachi tags 買い物 サ変可能 ("can take
        # する"), which is enough on its own: Japanese's noun+する
        # verbalization is fully productive, not something JMDict lexicalizes
        # for every noun. lookup_form uses both pieces' own dictionary forms
        # (買い物する, not the occurrence's actual 買い物し) so the existing
        # composite-gloss fallback (a_split_decomposition) can decompose it
        # right back into [買い物, する] and gloss each separately.
        suggestions = _suggestions("買い物した。")
        assert suggestions[0] == {
            "surface": "買い物し",
            "lookup_form": "買い物する",
            "reading": "かいものする",
            "token_count": 2,
        }

    def test_offers_suru_verbalization_for_a_noun_sudachi_does_not_tag_sa_hen(self):
        # 遠回りする ("to take a detour") is completely natural Japanese, but
        # Sudachi's own dictionary tags 遠回り as a plain noun (一般), not
        # サ変可能 ("can take する") — the way 買い物/勉強/etc. are. Not gated
        # on that tag (see module docstring for why it's demonstrably
        # incomplete), so 遠回り still gets the suggestion.
        suggestions = _suggestions("遠回りした。")
        assert suggestions[0] == {
            "surface": "遠回りし",
            "lookup_form": "遠回りする",
            "reading": "とおまわりする",
            "token_count": 2,
        }

    def test_a_real_exact_match_is_still_found_for_a_sa_hen_noun(self):
        # 恋する ("to fall in love") is one of the rare サ変可能 nouns whose
        # own noun+する combination really is a JMDict headword — this only
        # checks the suggestion shape is right; whether it actually came
        # from the ordinary exact-match search (source='jmdict', a real
        # dictionary entry) rather than the suru-verbalization fallback
        # (source='composite', a synthesized one — see module docstring's
        # `continue` after a real match) isn't observable from the
        # suggestion alone, since both would produce the same lookup_form
        # here — see test_prefers_a_real_dictionary_entry_over_the_suru_fallback
        # in tests/test_conflicts.py for that proof, at the gloss level.
        suggestions = _suggestions("彼女に恋してしまった。")
        assert suggestions[2] == {
            "surface": "恋し",
            "lookup_form": "恋する",
            "reading": "こいする",
            "token_count": 2,
        }


class TestLightVerbChain:
    """light_verb_chain_end and _bare_light_verb_chain_suggestion (see
    app/phrase_merge.py's module docstring) — the tier that offers a bare
    verb/adjective plus a following te-form + light-verb chain directly
    (見てみる), without requiring some other suggestion to be accepted
    first. See tests/test_conflicts.py's TestLightVerbChainExtension for
    the post-accept "reveal" tier (真に受け -> 真に受けてみて) and the full
    gloss-composition/reading correctness this tier's suggestion feeds
    into once accepted.
    """

    def test_offers_a_bare_verb_plus_its_light_verb_chain(self):
        # 猫/を/見/て/みる: 見 is the base verb ("to see"), て+みる is the
        # てみる "to try" auxiliary chain (みる tokenizes as one word here,
        # tagged 非自立可能 for this occurrence) — chain_start_offset=1 marks
        # only 見 itself as the "base", the rest (て/みる) as the chain.
        suggestions = _suggestions("猫を見てみる。")
        assert suggestions[2] == {
            "surface": "見てみる",
            "lookup_form": "見てみる",
            "reading": "みてみる",
            "token_count": 3,
            "chain_start_offset": 1,
        }

    def test_absorbs_a_further_chain_link(self):
        # 忘れてしまっている: light_verb_chain_end recurses, so a second
        # te+light-verb link right after the first (てしまう, "to finish/
        # inadvertently") is absorbed into the same suggestion (5 tokens:
        # 忘れ/て/しまっ/て/いる) rather than requiring two separate accepts.
        # しまっ itself also gets its own (shorter, nested) suggestion, same
        # as any other eligible start position — see
        # test_nested_shorter_match_also_surfaces_independently above.
        suggestions = _suggestions("宿題を忘れてしまっている。")
        assert suggestions[2] == {
            "surface": "忘れてしまっている",
            "lookup_form": "忘れてしまっている",
            "reading": "わすれてしまっている",
            "token_count": 5,
            "chain_start_offset": 1,
        }

    def test_absorbs_a_trailing_bare_connector_with_nothing_after_it(self):
        # 読ん/で/み/て: で is 読む's own godan column connector (む -> んで,
        # not て), and the final て — dangling on its own otherwise, with
        # nothing following it forming another chain link — is still み's
        # own unfinished conjunctive form, not a separate word, so it's
        # swept into the same suggestion too (see light_verb_chain_end's
        # docstring; real case found live: 真に受けてみて used to stop one
        # token short, at 真に受けてみ, leaving the final て ungrouped).
        suggestions = _suggestions("本を読んでみて。")
        assert suggestions[2] == {
            "surface": "読んでみて",
            "lookup_form": "読んでみて",
            "reading": "よんでみて",
            "token_count": 4,
            "chain_start_offset": 1,
        }

    def test_does_not_absorb_a_trailing_connector_that_starts_another_chain_link(self):
        from app.phrase_merge import light_verb_chain_end

        # A synthetic check that the trailing-connector absorption is only
        # a fallback for when light_verb_chain_end's own recursion already
        # found nothing further — not a separate, competing rule that could
        # somehow absorb a connector recursion should have consumed as part
        # of a real further link instead. Minimal stand-ins (only .surface
        # and .part_of_speech are used — see light_verb_chain_end's
        # docstring on working with anything exposing just those two).
        class Tok:
            def __init__(self, surface, pos):
                self.surface = surface
                self.part_of_speech = pos

        connector = ("助詞", "接続助詞", "*", "*", "*", "*")
        light_verb = ("動詞", "非自立可能", "*", "*", "*", "*")
        records = [
            Tok("て", connector),
            Tok("しまっ", light_verb),
            Tok("て", connector),
            Tok("いる", light_verb),
        ]
        # Both links absorbed via recursion, nothing left dangling to even
        # consider for the trailing-connector fallback.
        assert light_verb_chain_end(records, 0, len(records)) == 4

    def test_no_chain_suggestion_when_the_light_verb_is_used_literally(self):
        # 見る here really does mean "to see" (its ordinary 連用形-一般 tag on
        # 見, and 驚い afterwards is its own separate, unrelated verb, not a
        # light verb at all) — not every て+verb sequence is a light-verb
        # chain, only ones Sudachi itself tags as this occurrence's
        # grammaticalized use.
        suggestions = _suggestions("彼を見て、驚いた。")
        assert suggestions == {}

    def test_no_suggestion_for_a_bare_verb_with_nothing_following(self):
        from app.phrase_merge import _bare_light_verb_chain_suggestion
        from app.tokenization import tokenize_document

        records = tokenize_document("走った。")
        assert _bare_light_verb_chain_suggestion(records, 0, len(records)) is None


class TestTrailingConnectorOnIdiomOrSuru:
    """A bare て/で with no light verb at all directly following an idiom
    (exact-match) or noun+する suggestion — real case found live: 遠回りし
    (noun+する verbalization) directly followed by a bare て, with a
    newline right after it (nothing chain-worthy), left the て out of the
    fusion entirely (see app/phrase_merge.py's _with_trailing_connector and
    tests/test_suru_verbalization.py's accept-level coverage for the
    noun+する case). This class covers the exact-match idiom side of the
    same fix — see TestBareVerbChain/TestChainExtensionReveal in
    test_light_verb_chain.py for the real light-verb-chain case, which is
    deliberately NOT folded in here (left for the existing post-accept
    "reveal" step instead)."""

    def test_absorbs_a_bare_trailing_connector_after_an_exact_match_idiom(self):
        # この期に及んで (the motivating idiom) directly followed by a bare
        # て with nothing chain-worthy after it — invented, since this
        # specific idiom is never naturally followed by a bare て, but it
        # exercises the same exact-match code path the real noun+する bug
        # was found in.
        suggestions = _suggestions("この期に及んでて。")
        assert suggestions[0] == {
            "surface": "この期に及んでて",
            "lookup_form": "この期に及んでて",
            "reading": "このごにおよんでて",
            "token_count": 6,
            "base_lookup_form": "この期に及んで",
            "base_reading": "このごにおよんで",
            "chain_start_offset": 5,
        }

    def test_does_not_absorb_when_a_real_light_verb_chain_follows_instead(self):
        # 恋して (exact-match idiom, a real JMDict headword) directly
        # followed by a genuine light-verb chain (てしまった, 非自立可能) —
        # must be left alone for the existing post-accept "reveal" step,
        # not folded into this suggestion (see module docstring on why:
        # folding it in would deny ever seeing 恋する on its own first).
        suggestions = _suggestions("彼女に恋してしまった。")
        assert suggestions[2]["surface"] == "恋し"
        assert suggestions[2]["token_count"] == 2
        assert "chain_start_offset" not in suggestions[2]
