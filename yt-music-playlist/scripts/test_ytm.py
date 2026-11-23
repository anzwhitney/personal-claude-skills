"""Tests for ytm's track identity (run: python3 -m unittest discover scripts)."""
import unittest

from ytm import UsedTracks, label_key, same_length, track_key


class TrackKeyTest(unittest.TestCase):
    def same(self, a, b):
        self.assertEqual(label_key(a), label_key(b), f"{a!r} vs {b!r}")

    def different(self, a, b):
        self.assertNotEqual(label_key(a), label_key(b), f"{a!r} vs {b!r}")

    def test_release_labels_are_ignored(self):
        self.same("Kiasmos - Flown", "Kiasmos - Flown - Remastered 2021")
        self.same("Kiasmos - Flown", "Kiasmos - Flown (2021 Remaster)")
        self.same("Max Cooper - Wasp", "Max Cooper - Wasp (Original Mix)")
        self.same("Max Cooper - Wasp", "Max Cooper - Wasp [Official Audio]")
        self.same("Tycho - Coastal Brake", "Tycho - Coastal Brake (Album Version)")

    def test_case_accents_and_guest_artists_are_ignored(self):
        self.same("Hermanos Gutiérrez - Low Sun", "Hermanos Gutierrez - low sun")
        self.same("Max Cooper, Tom Hodge - Symmetry", "Max Cooper - Symmetry")
        self.same("Max Cooper & Tom Hodge - Symmetry", "Max Cooper - Symmetry")

    def test_versions_are_different_tracks(self):
        self.different("Max Cooper - Origins", "Max Cooper - Origins (Extended)")
        self.different("Max Cooper - Ascent", "Max Cooper - Ascent (Elysian Fields Mix)")
        self.different("Max Cooper - Penrose Tiling", "Max Cooper - Penrose Tiling (Max Cooper Remix)")
        self.different("Max Cooper - Penrose Tiling",
                       "Max Cooper - Penrose Tiling (Max Cooper Remix, Live at the Acropolis)")
        self.different("Max Cooper - Penrose Tiling",
                       "Max Cooper - Penrose Tiling 3D (Binaural Version - Headphones Only)")
        self.different("Max Cooper - Hope", "Max Cooper - Hope (Edit)")
        self.different("Max Cooper - Waves", "Max Cooper - Waves (Live at the Acropolis)")
        self.different("Max Cooper - Stars", "Yosi Horikawa - Stars")

    def test_feat_is_a_version(self):
        self.different("Max Cooper - Repetition", "Max Cooper - Repetition (feat. James Yorkston)")
        self.different("Max Cooper - Repetition", "Max Cooper - Repetition feat. James Yorkston")
        self.same("Max Cooper - Repetition (feat. James Yorkston)",
                  "Max Cooper - Repetition feat. James Yorkston")

    def test_key_shape(self):
        self.assertEqual(track_key("Max Cooper", "Origins (Extended)"), "max cooper|origins|extended")


class UsedTracksTest(unittest.TestCase):
    def setUp(self):
        self.used = UsedTracks()
        self.used.add("WTEk8floVOE", "Kiasmos", "Flown", 236, "Slipstream")
        self.used.add("m7XUWf5BBt4", "Max Cooper", "Repetition", None, "exclude-tracks")

    def test_same_videoid(self):
        self.assertEqual(self.used.match("WTEk8floVOE", "x", "y")[0], "same")

    def test_other_videoid_same_recording(self):
        kind, entry = self.used.match("W5iBcJqudtw", "Kiasmos", "Flown", 236)
        self.assertEqual((kind, entry["source"]), ("same", "Slipstream"))

    def test_other_length_is_a_possible_version(self):
        self.assertEqual(self.used.match("zzzzzzzzzzz", "Kiasmos", "Flown", 300)[0], "version")

    def test_unknown_length_matches(self):
        self.assertEqual(self.used.match("zzzzzzzzzzz", "Max Cooper", "Repetition", 351)[0], "same")

    def test_remix_does_not_match(self):
        self.assertIsNone(self.used.match("zzzzzzzzzzz", "Max Cooper", "Repetition (Non Square Remix)", 235))

    def test_any_version_of_a_banned_track_is_a_version(self):
        self.used.add("m7XUWf5BBt4", "Max Cooper", "Repetition", None, "track exclude-list", any_version=True)
        self.assertEqual(self.used.match("m7XUWf5BBt4", "x", "y")[0], "same")
        self.assertEqual(self.used.match("TcOmno-7DaY", "Max Cooper", "Repetition", 351)[0], "same")
        kind, entry = self.used.match("TcOmno-7DaY", "Max Cooper", "Repetition (Edit)", 237)
        self.assertEqual((kind, entry["source"]), ("version", "track exclude-list"))
        self.assertIsNone(self.used.match("zzzzzzzzzzz", "Max Cooper", "Repetitions", 351))
        self.assertIsNone(self.used.without({"m7XUWf5BBt4"}).match(None, "Max Cooper", "Repetition (Edit)"))

    def test_playlist_and_resolved_track_shapes(self):
        used = UsedTracks()
        used.add_track({"videoId": "a" * 11, "title": "Low Sun", "duration_seconds": 189,
                        "artists": [{"name": "Hermanos Gutiérrez"}]})
        self.assertEqual(used.match("b" * 11, "Hermanos Gutierrez", "Low Sun", 190)[0], "same")
        used.add_track({"videoId": "c" * 11, "title": "Tono", "artist": "Yosi Horikawa", "duration_seconds": 322})
        self.assertEqual(used.match(None, "Yosi Horikawa", "Tono", 322)[0], "same")

    def test_without_drops_a_playlists_own_tracks(self):
        rest = self.used.without({"WTEk8floVOE"})
        self.assertIsNone(rest.match("WTEk8floVOE", "Kiasmos", "Flown", 236))
        self.assertIsNotNone(rest.match("m7XUWf5BBt4", "Max Cooper", "Repetition"))

    def test_same_length(self):
        self.assertTrue(same_length(236, 241))
        self.assertFalse(same_length(236, 242))
        self.assertTrue(same_length(None, 242))


if __name__ == "__main__":
    unittest.main()
