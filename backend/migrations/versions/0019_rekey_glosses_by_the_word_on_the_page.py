"""rekey glosses by the word on the page

A token's default gloss key used to read its normalized form on its own, which
for some spellings is a different word from the one on the page: する
normalizes to 為る, which on its own reads なる ("to become"). The key now
takes the reading as written where it's one of the normalized form's (see
app.tokenization.headword_reading), so for each (normalized form, dictionary
form) whose key changed, this moves what was stored under the old key:

- the citation_reading of the reading options built from the old key (a
  heteronym token's default, every no_kana_anchor option, and the original a
  correction preserves), so picking one glosses under the new key;
- tokens' gloss links, which are cleared, so the next load glosses them again
  (a predicate group's too, with its composite, which is keyed by the page's
  reading and so would otherwise be reused);
- study cards, which keep their history under the new key.

Katakana words glossed as hiragana (see app/katakana.py) are keyed by the
katakana, but built from the hiragana's own keys, so they're all dropped to be
glossed again, as 0014 did.

An accepted phrase is left linked: its gloss is keyed by its headword, and a
helper verb attached to one (いる, しまう, みる, ...) reads the same either way.

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-25 00:00:00.000000

"""

import json
import re
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text
from sudachipy import dictionary as sudachi_dictionary
from sudachipy import errors as sudachi_errors
from sudachipy import tokenizer as sudachi_tokenizer

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The rest of this module is a copy of the key's reading as app.tokenization
# computes it now and computed it before (mixed_reading, headword_reading),
# so later changes there don't change what this migration did.

_KANJI = "㐀-䶿一-鿿々〆"
_RUN_RE = re.compile(f"[{_KANJI}]+|[^{_KANJI}]+")
_KANJI_RE = re.compile(f"[{_KANJI}]")
_TO_HIRAGANA = str.maketrans(
    {chr(code + 0x60): chr(code) for code in range(0x3041, 0x3097)}
)
_TO_KATAKANA = str.maketrans(
    {chr(code): chr(code + 0x60) for code in range(0x3041, 0x3097)}
)


class _Readings:
    def __init__(self) -> None:
        self._dictionary = sudachi_dictionary.Dictionary(dict="full")
        self._tokenizer = self._dictionary.create()

    def _citation(self, word: str) -> str:
        mode_c = sudachi_tokenizer.Tokenizer.SplitMode.C
        return "".join(m.reading_form() for m in self._tokenizer.tokenize(word, mode_c))

    def _own(self, normalized_form: str) -> list[str]:
        try:
            morphemes = self._dictionary.lookup(normalized_form)
        except (sudachi_errors.SudachiError, UnicodeEncodeError):
            return []
        readings: list[str] = []
        for m in morphemes:
            if (
                m.normalized_form() == normalized_form
                and m.reading_form() not in readings
            ):
                readings.append(m.reading_form())
        return readings

    @staticmethod
    def _mixed(word: str, reading: str) -> str:
        """Kanji in hiragana, kana as written."""
        if not _KANJI_RE.search(word):
            return word
        runs = _RUN_RE.findall(word)
        pattern = "".join(
            "(.+?)" if _KANJI_RE.match(run) else re.escape(run.translate(_TO_KATAKANA))
            for run in runs
        )
        match = re.fullmatch(pattern, reading)
        if match is None:
            return reading.translate(_TO_HIRAGANA)
        groups = iter(match.groups())
        return "".join(
            next(groups).translate(_TO_HIRAGANA) if _KANJI_RE.match(run) else run
            for run in runs
        )

    def old(self, normalized_form: str) -> str:
        return self._mixed(normalized_form, self._citation(normalized_form))

    def new(self, normalized_form: str, dictionary_form: str) -> str:
        own = self._own(normalized_form)
        standalone = self._citation(normalized_form)
        for candidate in (self._citation(dictionary_form), standalone):
            if candidate in own:
                return self._mixed(normalized_form, candidate)
        return self._mixed(normalized_form, own[0] if own else standalone)


def rekey(conn) -> None:
    """Move what's stored under each changed key to the new one."""
    pairs = conn.execute(
        text(
            """
            SELECT normalized_form, dictionary_form FROM tokens
            UNION
            -- A card's alternate spelling is the dictionary form of the
            -- tokens it came from.
            SELECT lookup_form, alt_lookup_form FROM study_cards
            WHERE kind = 'recognition' AND alt_lookup_form IS NOT NULL
            """
        )
    ).all()
    readings = _Readings()
    rekeyed = []
    for normalized_form, dictionary_form in pairs:
        old = readings.old(normalized_form)
        new = readings.new(normalized_form, dictionary_form)
        if old != new:
            rekeyed.append(
                {
                    "normalized_form": normalized_form,
                    "dictionary_form": dictionary_form,
                    "old_reading": old,
                    "new_reading": new,
                }
            )

    conn.execute(
        text(
            """
            CREATE TEMPORARY TABLE rekeyed ON COMMIT DROP AS
            SELECT * FROM jsonb_to_recordset(CAST(:rows AS JSONB)) AS r(
                normalized_form text, dictionary_form text, old_reading text, new_reading text
            )
            """
        ),
        {"rows": json.dumps(rekeyed)},
    )

    # Only the options whose citation_reading came from the old key: a
    # heteronym's alternatives were read from the dictionary form, and a
    # typed correction is its own citation_reading.
    conn.execute(
        text(
            """
            UPDATE conflicts c
            SET value = jsonb_set(c.value, '{citation_reading}', to_jsonb(r.new_reading))
            FROM tokens t
            JOIN rekeyed r USING (normalized_form, dictionary_form)
            WHERE c.token_id = t.id AND c.value ->> 'citation_reading' = r.old_reading
              AND (
                  c.kind = 'no_kana_anchor'
                  OR (c.kind = 'heteronym' AND c.id = (
                      SELECT min(d.id) FROM conflicts d WHERE d.token_id = t.id AND d.kind = 'heteronym'
                  ))
                  OR (c.kind = 'custom' AND c.value ->> 'citation_reading' <> c.value ->> 'reading')
              )
            """
        )
    )

    # Every gloss a predicate group with a rekeyed member, or a katakana word,
    # is linked to, and every katakana word's gloss.
    conn.execute(
        text(
            """
            CREATE TEMPORARY TABLE stale_glosses ON COMMIT DROP AS
            SELECT DISTINCT g.gloss_lookup_id AS id
            FROM tokens g
            JOIN tokens t ON t.document_id = g.document_id AND t.phrase_start_position = g.phrase_start_position
            WHERE g.gloss_lookup_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM conflicts pc JOIN tokens ph ON ph.id = pc.token_id
                  WHERE ph.document_id = g.document_id AND ph.position = g.phrase_start_position
                    AND pc.kind = 'phrase' AND pc.selected
              )
              AND (
                  EXISTS (
                      SELECT 1 FROM rekeyed r
                      WHERE (r.normalized_form, r.dictionary_form) = (t.normalized_form, t.dictionary_form)
                  )
                  -- Matches app.katakana.is_katakana_word.
                  OR t.normalized_form ~ '^[ァ-ヶー]{2,}$'
              )
            UNION
            SELECT id FROM gloss_lookups WHERE source = 'composite' AND entries ? 'looked_up_as'
            """
        )
    )
    conn.execute(
        text(
            """
            UPDATE tokens t SET gloss_lookup_id = NULL
            WHERE t.gloss_lookup_id IN (SELECT id FROM stale_glosses)
               OR (
                   t.phrase_start_position IS NULL
                   AND EXISTS (
                       SELECT 1 FROM rekeyed r
                       WHERE (r.normalized_form, r.dictionary_form) = (t.normalized_form, t.dictionary_form)
                   )
               )
            """
        )
    )
    conn.execute(
        text(
            "DELETE FROM gloss_lookups WHERE id IN (SELECT id FROM stale_glosses) AND source = 'composite'"
        )
    )

    # A card the user already has under the new key keeps the old one as it
    # is, rather than merging two review histories. A card from a heteronym
    # alternative read the old key's way is moved too, since a card doesn't
    # record which reading it came from; no heteronym is known to do that.
    conn.execute(
        text(
            """
            UPDATE study_cards c SET reading = r.new_reading
            FROM rekeyed r
            WHERE c.kind = 'recognition' AND c.lookup_form = r.normalized_form
              AND c.alt_lookup_form = r.dictionary_form AND c.reading = r.old_reading
              AND NOT EXISTS (
                  SELECT 1 FROM study_cards o
                  WHERE o.user_id = c.user_id AND o.kind = c.kind
                    AND o.lookup_form = c.lookup_form AND o.reading = r.new_reading
              )
            """
        )
    )


def upgrade() -> None:
    """Upgrade schema."""
    rekey(op.get_bind())


def downgrade() -> None:
    """Downgrade schema."""
    # Nothing to restore: the old keys glossed these tokens as the wrong word.
