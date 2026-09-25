"""Tests for audio's voice verdicts (run: python3 -m unittest discover scripts)."""
import unittest
from unittest import mock

import audio


class VoiceVerdictFallbackTest(unittest.TestCase):
    def verdict(self, *args):
        verdicts = {"WTEk8floVOE": {"verdict": "ok", "label": "Kiasmos - Flown"}}
        features = {"WTEk8floVOE": {"duration": 236}}
        with mock.patch.object(audio, "load_voice_verdicts", return_value=verdicts), \
             mock.patch.object(audio, "load_features_cache", return_value=features):
            return audio.voice_verdict(*args)

    def test_own_verdict(self):
        self.assertEqual(self.verdict("WTEk8floVOE"), "ok")

    def test_other_upload_inherits_verdict(self):
        self.assertEqual(self.verdict("W5iBcJqudtw", "Kiasmos - Flown", 237), "ok")

    def test_other_length_or_version_does_not(self):
        self.assertIsNone(self.verdict("W5iBcJqudtw", "Kiasmos - Flown", 300))
        self.assertIsNone(self.verdict("W5iBcJqudtw", "Kiasmos - Flown (Edit)", 236))
        self.assertIsNone(self.verdict("W5iBcJqudtw"))


if __name__ == "__main__":
    unittest.main()
