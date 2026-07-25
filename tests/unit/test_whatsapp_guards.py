"""Unit tests for infrastructure/whatsapp/guards.py.

Cases are ported 1:1 from the Baileys adapter's
`app/whatsapp_bot/src/guards.test.ts` so both channels are held to the same
behavioral contract. `TestHashParity` additionally locks in the property the
migration depends on: a returning user must resolve to the same `chat_id`
under the Cloud API as they did under Baileys.
"""

import asyncio
import unittest
from hashlib import sha256

from habitantes.infrastructure.whatsapp.guards import (
    DedupSet,
    KeyedLock,
    RateLimiter,
    exceeds_length,
    hash_wa_id,
    is_gratitude_only,
    is_reset_command,
    normalize_text,
)

PHONE = "553199999999"


class TestHashWaId(unittest.TestCase):
    def test_deterministic_for_same_input(self):
        self.assertEqual(hash_wa_id(PHONE, "salt", 16), hash_wa_id(PHONE, "salt", 16))

    def test_changes_when_salt_changes(self):
        self.assertNotEqual(
            hash_wa_id(PHONE, "salt-a", 16), hash_wa_id(PHONE, "salt-b", 16)
        )

    def test_respects_requested_hash_length(self):
        self.assertEqual(len(hash_wa_id(PHONE, "salt", 16)), 16)
        self.assertEqual(len(hash_wa_id(PHONE, "salt", 8)), 8)

    def test_never_leaks_the_raw_phone_number(self):
        self.assertNotIn(PHONE, hash_wa_id(PHONE, "salt", 16))


class TestHashParityWithBaileys(unittest.TestCase):
    """The migration's identity-continuity guarantee: Baileys' `hashJid`
    computed `sha256(salt + phoneNumberPart(jid))` where `phoneNumberPart`
    strips everything from the first `:`/`.`/`@` onward — i.e. exactly the
    bare digits Meta's Cloud API delivers as `wa_id`. Same salt, same bare
    digits in, must produce the same `chat_id` out, or every existing user's
    conversation memory and feedback history breaks on migration.
    """

    def test_matches_baileys_hashjid_for_the_bare_digit_wa_id(self):
        def ts_style_hash_jid(jid_phone_part: str, salt: str, length: int) -> str:
            return sha256((salt + jid_phone_part).encode()).hexdigest()[:length]

        salt = "some-long-random-salt"
        self.assertEqual(
            hash_wa_id(PHONE, salt, 16), ts_style_hash_jid(PHONE, salt, 16)
        )


class TestNormalizeText(unittest.TestCase):
    def test_lowercases_strips_accents_and_collapses_punctuation(self):
        self.assertEqual(normalize_text("OBRIGADO!!!"), "obrigado")
        self.assertEqual(normalize_text("ótimo, mesmo?"), "otimo mesmo")

    def test_keeps_emoji_intact(self):
        self.assertEqual(normalize_text("🙏"), "🙏")


class TestIsGratitudeOnly(unittest.TestCase):
    keywords = [
        "obrigado",
        "muito obrigado",
        "thanks",
        "thank you",
        "merci",
        "gracias",
        "🙏",
        "👍",
    ]

    def test_true_for_pure_gratitude_in_several_languages(self):
        for msg in [
            "obrigado",
            "muito obrigado",
            "thanks",
            "thank you",
            "merci",
            "gracias",
            "🙏",
            "OBRIGADO!!!",
        ]:
            with self.subTest(msg=msg):
                self.assertTrue(is_gratitude_only(msg, self.keywords))

    def test_false_when_a_real_question_is_attached(self):
        self.assertFalse(is_gratitude_only("obrigado, mas e o visto?", self.keywords))

    def test_false_for_a_normal_question(self):
        self.assertFalse(is_gratitude_only("como faço o visto?", self.keywords))

    def test_false_for_empty_or_unmatched_text(self):
        self.assertFalse(is_gratitude_only("", self.keywords))
        self.assertFalse(is_gratitude_only("bom dia", self.keywords))


class TestIsResetCommand(unittest.TestCase):
    def test_matches_slash_command_and_bare_word_case_accent_insensitive(self):
        for msg in ["/reset", "reset", "Reset", "RESET", "/RESET", " /reset "]:
            with self.subTest(msg=msg):
                self.assertTrue(is_reset_command(msg))

    def test_does_not_match_a_real_question_or_longer_message(self):
        self.assertFalse(is_reset_command("como faço reset da senha?"))
        self.assertFalse(is_reset_command("reset por favor"))
        self.assertFalse(is_reset_command(""))
        self.assertFalse(is_reset_command("resetar"))


class TestExceedsLength(unittest.TestCase):
    def test_true_only_when_longer_than_max(self):
        self.assertFalse(exceeds_length("abc", 3))
        self.assertTrue(exceeds_length("abcd", 3))


class TestRateLimiter(unittest.TestCase):
    def test_allows_up_to_n_then_blocks_n_plus_1_within_window(self):
        limiter = RateLimiter(3, 60.0)
        self.assertTrue(limiter.allow("k"))
        self.assertTrue(limiter.allow("k"))
        self.assertTrue(limiter.allow("k"))
        self.assertFalse(limiter.allow("k"))

    def test_does_not_consume_budget_on_a_rejected_call(self):
        limiter = RateLimiter(1, 60.0)
        self.assertTrue(limiter.allow("k"))
        self.assertFalse(limiter.allow("k"))
        self.assertFalse(limiter.allow("k"))

    def test_tracks_keys_independently(self):
        limiter = RateLimiter(1, 60.0)
        self.assertTrue(limiter.allow("a"))
        self.assertTrue(limiter.allow("b"))
        self.assertFalse(limiter.allow("a"))

    def test_cleanup_drops_keys_that_have_aged_out(self):
        limiter = RateLimiter(2, -1)  # window in the past -> all expired
        limiter.allow("k")
        limiter.cleanup()
        self.assertTrue(limiter.allow("k"))  # fresh budget after cleanup


class TestDedupSet(unittest.TestCase):
    def test_has_reports_false_before_add_and_true_after(self):
        dedup = DedupSet()
        self.assertFalse(dedup.has("id1"))
        dedup.add("id1")
        self.assertTrue(dedup.has("id1"))

    def test_clear_empties_the_set(self):
        dedup = DedupSet()
        dedup.add("a")
        dedup.add("b")
        self.assertEqual(len(dedup), 2)
        dedup.clear()
        self.assertEqual(len(dedup), 0)
        self.assertFalse(dedup.has("a"))


class TestKeyedLock(unittest.IsolatedAsyncioTestCase):
    async def test_serializes_jobs_on_the_same_key(self):
        lock = KeyedLock()
        order: list[str] = []

        async def job(label: str, delay: float) -> None:
            async def _run() -> None:
                order.append(f"{label}:start")
                await asyncio.sleep(delay)
                order.append(f"{label}:end")

            await lock.run("same", _run)

        await asyncio.gather(job("A", 0.03), job("B", 0.001))

        self.assertEqual(order, ["A:start", "A:end", "B:start", "B:end"])

    async def test_lets_jobs_on_different_keys_interleave(self):
        lock = KeyedLock()
        order: list[str] = []

        async def job(key: str, label: str, delay: float) -> None:
            async def _run() -> None:
                order.append(f"{label}:start")
                await asyncio.sleep(delay)
                order.append(f"{label}:end")

            await lock.run(key, _run)

        await asyncio.gather(job("k1", "A", 0.03), job("k2", "B", 0.001))

        self.assertLess(order.index("B:start"), order.index("A:end"))

    async def test_returns_the_job_result(self):
        lock = KeyedLock()

        async def _run() -> int:
            return 42

        self.assertEqual(await lock.run("k", _run), 42)


if __name__ == "__main__":
    unittest.main()
