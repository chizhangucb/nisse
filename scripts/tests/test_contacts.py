"""Tests for scripts/contacts.py, the JSONL contact store.

Ported from the upstream (issue #28). No network; every test runs against a
throwaway root seeded from the fixture store, except the last class, which
checks the store this repo actually ships.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS)

import contacts as C  # noqa: E402

FIXTURES = os.path.join(SCRIPTS, "tests", "fixtures")
FIXTURE_STORE = os.path.join(FIXTURES, "contacts_store")


class Sandbox(unittest.TestCase):
    """Throwaway root with the fixture JSONL store copied into contacts/."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        shutil.copytree(FIXTURE_STORE, os.path.join(self.root, "contacts"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, relpath, text):
        path = os.path.join(self.root, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def add_raw(self, obj):
        """Append one raw JSON object to contacts.jsonl, bypassing the API so a
        malformed record (missing keys, bad status) can be tested."""
        with open(os.path.join(self.root, "contacts", C.CONTACTS_FILE), "a",
                  encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def add_contact(self, slug, name, status="confirmed", aliases=(), wiki="",
                    affiliation="", role=""):
        """Save a well-formed contact through the API."""
        c = C.blank_contact(slug, name, status, affiliation, role)
        c["aliases"] = list(aliases)
        c["wiki"] = wiki
        C.save_contact(c, self.root)


class TestSlugify(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(C.slugify("Sam Rivera"), "sam_rivera")
        self.assertEqual(C.slugify("Ian (Acme, surname not captured)"), "ian")
        self.assertEqual(C.slugify("戴宇森"), "")


class TestLoadAndResolve(Sandbox):

    def test_load(self):
        store = C.load_contacts(self.root)
        self.assertEqual(sorted(store), ["priya_patel", "sam_rivera"])
        self.assertEqual(store["priya_patel"]["status"], "best_read")
        self.assertIn("Preya", store["priya_patel"]["aliases"])

    def test_resolve_canonical_and_alias_case_insensitive(self):
        hit = C.resolve("sam rivera", self.root)
        self.assertEqual(hit["status"], "hit")
        self.assertEqual(hit["contact"]["slug"], "sam_rivera")
        alias = C.resolve("PREYA", self.root)
        self.assertEqual(alias["status"], "hit")
        self.assertEqual(alias["contact"]["name"], "Priya Patel")

    def test_not_name_is_a_hard_miss(self):
        res = C.resolve("the stat", self.root)
        self.assertEqual(res["status"], "not_name")
        self.assertIn("staff", res["reason"])
        self.assertIsNone(res["contact"])
        self.assertEqual(C.resolve("crawl code", self.root)["status"], "not_name")

    def test_unknown_name_misses(self):
        self.assertEqual(C.resolve("Nobody Here", self.root)["status"], "miss")

    def test_query_is_loose(self):
        hits = C.query("riv", self.root)
        self.assertEqual([c["slug"] for c in hits], ["sam_rivera"])
        self.assertEqual(C.query("zzz", self.root), [])

    def test_no_store_degrades_to_a_miss(self):
        empty = tempfile.mkdtemp()
        try:
            self.assertEqual(C.load_contacts(empty), {})
            self.assertEqual(C.resolve("Preya", empty)["status"], "miss")
        finally:
            shutil.rmtree(empty, ignore_errors=True)


class TestValidate(Sandbox):

    def test_clean_store_passes(self):
        violations, _warnings = C.validate(self.root)
        self.assertEqual(violations, [])

    def test_missing_store_is_a_violation(self):
        empty = tempfile.mkdtemp()
        try:
            violations, _ = C.validate(empty)
            self.assertTrue(any("does not exist" in v for v in violations))
        finally:
            shutil.rmtree(empty, ignore_errors=True)

    def test_missing_key_and_bad_status(self):
        self.add_raw({"slug": "partial", "name": "Partial", "status": "maybe"})
        violations, _ = C.validate(self.root)
        self.assertTrue(any("missing key" in v for v in violations))
        self.assertTrue(any("is not one of" in v for v in violations))

    def test_alias_claimed_twice(self):
        self.add_contact("other", "Other Person", aliases=["Preya"])
        violations, _ = C.validate(self.root)
        self.assertTrue(any("claimed by both" in v for v in violations))

    def test_alias_that_is_another_canonical_name(self):
        self.add_contact("other", "Other Person", aliases=["Sam Rivera"])
        violations, _ = C.validate(self.root)
        self.assertTrue(any("is the canonical name of" in v for v in violations))

    def test_missing_wiki_target(self):
        self.add_contact("sam_rivera", "Sam Rivera", wiki="entities/sam_rivera.md")
        violations, _ = C.validate(self.root)
        self.assertTrue(any("does not exist" in v for v in violations))
        self.write("wiki/entities/sam_rivera.md", "# Sam\n")
        violations, _ = C.validate(self.root)
        self.assertEqual(violations, [])

    def test_internal_contact_without_a_role_warns(self):
        self.add_contact("new_hire", "New Hire", affiliation="internal")
        violations, warnings = C.validate(self.root)
        self.assertEqual(violations, [])
        self.assertTrue(any("no role" in w for w in warnings))

    def test_not_name_overlap_is_a_warning_not_a_violation(self):
        self.add_contact("stat_person", "Stat Person", aliases=["the stat"])
        violations, warnings = C.validate(self.root)
        self.assertEqual(violations, [])
        self.assertTrue(any("never resolve" in w for w in warnings))


class TestAdd(Sandbox):

    def test_add_writes_a_contact_and_refuses_a_duplicate(self):
        args = C.build_parser().parse_args(
            ["--root", self.root, "add", "--slug", "new_person",
             "--name", "New Person", "--status", "confirmed"])
        self.assertEqual(C.cmd_add(args), 0)
        store = C.load_contacts(self.root)
        self.assertEqual(store["new_person"]["name"], "New Person")
        self.assertEqual(store["new_person"]["status"], "confirmed")
        self.assertEqual(C.cmd_add(args), 1)

    def test_add_refuses_a_slug_the_store_cannot_hold(self):
        # slugify() returns "" for a pure-Han name, so this is the documented
        # path, not a typo: a blank slug would be written and never seen again.
        args = C.build_parser().parse_args(
            ["--root", self.root, "add", "--slug", C.slugify("戴宇森"),
             "--name", "戴宇森"])
        self.assertEqual(C.cmd_add(args), 1)
        self.assertEqual(sorted(C.load_contacts(self.root)),
                         ["priya_patel", "sam_rivera"])


class TestDamagedRowsAreNeverSilentlyDropped(Sandbox):
    """Every writer rewrites the whole file, so a row the reader drops would be
    deleted from disk. Damage is a violation, and it blocks writes."""

    def test_unparseable_line_is_a_violation(self):
        with open(os.path.join(self.root, "contacts", C.CONTACTS_FILE), "a",
                  encoding="utf-8") as f:
            f.write("{not json\n")
        violations, _ = C.validate(self.root)
        self.assertTrue(any("not valid JSON" in v for v in violations))

    def test_slugless_row_is_a_violation(self):
        self.add_raw({"name": "No Slug", "status": "confirmed"})
        violations, _ = C.validate(self.root)
        self.assertTrue(any("has no slug" in v for v in violations))

    def test_duplicate_slug_is_a_violation(self):
        self.add_raw({"slug": "sam_rivera", "name": "Sam Rivera Again",
                      "status": "confirmed", "affiliation": "", "role": "",
                      "aliases": [], "channels": {}, "links": {}, "wiki": "",
                      "source": "", "notes": ""})
        violations, _ = C.validate(self.root)
        self.assertTrue(any("duplicate slug" in v for v in violations))

    def test_a_write_refuses_while_damage_stands(self):
        self.add_raw({"name": "No Slug", "status": "confirmed"})
        with self.assertRaises(C.ContactError):
            C.set_channel("sam_rivera", "email", "sam@example.com", self.root)
        # and the damaged row is still on disk, not silently rewritten away
        with open(os.path.join(self.root, "contacts", C.CONTACTS_FILE),
                  encoding="utf-8") as f:
            self.assertIn("No Slug", f.read())

    def test_a_null_field_is_absent_not_the_string_none(self):
        self.add_raw({"slug": "n1", "name": None, "status": "confirmed",
                      "affiliation": None, "role": None, "aliases": [],
                      "channels": {}, "links": {}, "wiki": None,
                      "source": None, "notes": None})
        store = C.load_contacts(self.root)
        self.assertEqual(store["n1"]["name"], "")
        self.assertEqual(store["n1"]["wiki"], "")
        self.assertEqual(C.resolve("None", self.root)["status"], "miss")
        # a null name is an empty name, which validate already calls a violation
        violations, _ = C.validate(self.root)
        self.assertTrue(any("empty name" in v for v in violations))
        self.assertFalse(any("wiki/None" in v for v in violations))

    def test_an_empty_name_is_a_violation(self):
        self.add_raw({"slug": "n2", "name": "", "status": "confirmed",
                      "affiliation": "", "role": "", "aliases": [],
                      "channels": {}, "links": {}, "wiki": "", "source": "",
                      "notes": ""})
        violations, _ = C.validate(self.root)
        self.assertTrue(any("empty name" in v for v in violations))


class TestNamesakes(Sandbox):
    def test_two_contacts_with_the_same_name_warn(self):
        self.add_contact("daniel_chen", "Daniel Chen")
        self.add_contact("daniel_chen_acme", "Daniel Chen")
        violations, warnings = C.validate(self.root)
        self.assertEqual(violations, [])
        self.assertTrue(any("is claimed by" in w for w in warnings))


class TestAddAlias(Sandbox):

    def test_alias_lands_and_then_resolves(self):
        C.add_alias("sam_rivera", "Sam Riviera", self.root)
        self.assertEqual(C.resolve("sam riviera", self.root)["contact"]["slug"],
                         "sam_rivera")

    def test_duplicate_alias_and_unknown_contact_are_refused(self):
        C.add_alias("sam_rivera", "Sam Riviera", self.root)
        with self.assertRaises(C.ContactError):
            C.add_alias("sam_rivera", "SAM RIVIERA", self.root)
        with self.assertRaises(C.ContactError):
            C.add_alias("nobody", "Whoever", self.root)


class TestAddNotName(Sandbox):

    def test_entry_lands_and_then_blocks_resolution(self):
        C.add_not_name('"term share" -> term sheet', self.root)
        res = C.resolve("term share", self.root)
        self.assertEqual(res["status"], "not_name")

    def test_an_entry_without_a_meaning_is_refused(self):
        with self.assertRaises(C.ContactError):
            C.add_not_name("just some words", self.root)

    def test_a_duplicate_entry_is_refused(self):
        C.add_not_name('"term share" -> term sheet', self.root)
        with self.assertRaises(C.ContactError):
            C.add_not_name('"term share" -> term sheet', self.root)


class TestAliasInflationGuard(Sandbox):
    """A one-word alias that is another person's real name earns a warning."""

    def warnings(self):
        _violations, warnings = C.validate(self.root)
        return [w for w in warnings if "is also a name word of" in w]

    def test_flags_alias_equal_to_another_persons_given_name(self):
        self.add_contact("daniel_cho", "Daniel Cho", aliases=["Daniel"])
        self.add_contact("daniel_wu", "Daniel Wu")
        msgs = self.warnings()
        self.assertEqual(len(msgs), 1)
        self.assertIn("alias 'daniel' of daniel_cho", msgs[0])
        self.assertIn("daniel_wu", msgs[0])

    def test_case_insensitive_and_surname_tokens_count(self):
        self.add_contact("lowes_yang", "Lowes Yang", aliases=["LUIS"])
        self.add_contact("maria_luis", "Maria Luis")
        self.assertEqual(len(self.warnings()), 1)

    def test_silent_when_no_other_contact_carries_the_name(self):
        self.add_contact("lowes_yang", "Lowes Yang", aliases=["Luis"])
        self.assertEqual(self.warnings(), [])

    def test_multi_word_aliases_are_not_flagged(self):
        self.add_contact("daniel_cho", "Daniel Cho", aliases=["Daniel from Acme"])
        self.add_contact("daniel_wu", "Daniel Wu")
        self.assertEqual(self.warnings(), [])

    def test_a_contacts_own_name_word_is_not_a_collision(self):
        self.add_contact("daniel_cho", "Daniel Cho", aliases=["Cho"])
        self.assertEqual(self.warnings(), [])

    def test_exact_alias_collision_is_already_a_violation(self):
        self.add_contact("daniel_cho", "Daniel Cho", aliases=["Danny"])
        self.add_contact("daniel_wu", "Daniel Wu", aliases=["DANNY"])
        violations, _warnings = C.validate(self.root)
        self.assertTrue(any("claimed by both" in v for v in violations))

    def test_flags_unspaced_han_given_name_from_another_identity_form(self):
        self.add_contact("ruimin_shi", "Ruimin Shi", aliases=["瑞敏"])
        self.add_contact("li_ruimin", "Li Ruimin", aliases=["李瑞敏"])
        msgs = self.warnings()
        self.assertEqual(len(msgs), 1)
        self.assertIn("alias '瑞敏' of ruimin_shi", msgs[0])
        self.assertIn("li_ruimin", msgs[0])

    def test_single_character_han_alias_is_always_risky(self):
        self.add_contact("he_yi", "He Yi", aliases=["一"])
        _violations, warnings = C.validate(self.root)
        self.assertTrue(any("single-character Han name fragment" in w
                            for w in warnings))

    def test_uncontested_han_alias_is_silent(self):
        self.add_contact("ruimin_shi", "Ruimin Shi", aliases=["瑞敏"])
        self.assertEqual(self.warnings(), [])


class TestChannelsLinks(Sandbox):

    def test_set_channel_persists_and_reloads(self):
        C.set_channel("sam_rivera", "telegram", "@sam", self.root)
        store = C.load_contacts(self.root)
        self.assertEqual(store["sam_rivera"]["channels"]["telegram"], "@sam")

    def test_set_channel_rejects_unknown_key(self):
        with self.assertRaises(C.ContactError):
            C.set_channel("sam_rivera", "signal", "x", self.root)

    def test_set_channel_rejects_unknown_contact(self):
        with self.assertRaises(C.ContactError):
            C.set_channel("nobody", "email", "x@example.com", self.root)

    def test_set_link_persists(self):
        C.set_link("sam_rivera", "linkedin", "https://example.com/in/sam",
                   self.root)
        store = C.load_contacts(self.root)
        self.assertEqual(store["sam_rivera"]["links"]["linkedin"],
                         "https://example.com/in/sam")

    def test_validate_flags_unknown_channel_key(self):
        # a raw record with a channel key past the CLI guard
        self.add_raw({"slug": "bad_chan", "name": "Bad Chan", "status": "confirmed",
                      "affiliation": "", "role": "", "aliases": [],
                      "channels": {"myspace": "x"}, "links": {}, "wiki": "",
                      "source": "", "notes": ""})
        violations, _warnings = C.validate(self.root)
        self.assertTrue(any("unknown channel 'myspace'" in v for v in violations))

    def test_validate_clean_when_channels_valid(self):
        C.set_channel("sam_rivera", "email", "sam@example.com", self.root)
        violations, _ = C.validate(self.root)
        self.assertEqual(violations, [])


class TestShippedStore(unittest.TestCase):
    """The store this repo ships is the starter kit's example: it must validate,
    and the names in it must resolve."""

    @classmethod
    def setUpClass(cls):
        cls.repo = os.path.dirname(SCRIPTS)

    def test_shipped_store_validates(self):
        violations, _warnings = C.validate(self.repo)
        self.assertEqual(violations, [])

    def test_shipped_store_resolves_its_own_names(self):
        for slug, c in C.load_contacts(self.repo).items():
            self.assertEqual(C.resolve(c["name"], self.repo)["status"], "hit", slug)

    def test_legacy_yaml_store_is_gone(self):
        self.assertFalse(
            os.path.exists(os.path.join(self.repo, "contacts", "_not_names.yml")),
            "the YAML anti-registry was replaced by contacts/not_names.jsonl")


if __name__ == "__main__":
    unittest.main()
