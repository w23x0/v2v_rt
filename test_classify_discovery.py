import unittest

from classify_discovery import classify_video
from dedupe import unique_videos, video_key


class DiscoveryClassificationTests(unittest.TestCase):
    def test_accepts_long_video_with_team_comms(self):
        result = classify_video(
            {"id": "a", "title": "Valorant ranked full match comms", "duration": 2400},
            "valorant",
        )
        self.assertEqual(result["decision"], "accept")

    def test_rejects_no_commentary_and_short_content(self):
        result = classify_video(
            {"id": "b", "title": "Valorant highlights no commentary", "duration": 600},
            "valorant",
        )
        self.assertEqual(result["decision"], "reject")
        self.assertTrue(any(reason.startswith("reject_term:") for reason in result["reasons"]))

    def test_reviews_uncertain_long_video(self):
        result = classify_video(
            {"id": "c", "title": "Valorant full game VOD", "duration": 1500},
            "valorant",
        )
        self.assertEqual(result["decision"], "review")

    def test_rejects_esports_broadcast(self):
        result = classify_video(
            {"id": "d", "title": "VCT playoffs official broadcast full match", "duration": 3600},
            "valorant",
        )
        self.assertEqual(result["decision"], "reject")

    def test_rejects_pro_player_or_team_comms(self):
        result = classify_video(
            {"id": "e", "title": "NRG VALORANT FULL Voice Comms of the greatest team", "duration": 2400},
            "valorant",
        )
        self.assertEqual(result["decision"], "reject")
        self.assertTrue(any(reason.startswith("pro_term:") for reason in result["reasons"]))

    def test_accepts_ordinary_player_voice(self):
        result = classify_video(
            {"id": "f", "title": "valorant 5 stack with friends team voice full game", "duration": 2200},
            "valorant",
        )
        self.assertEqual(result["decision"], "accept")

    def test_deduplicates_video_ids_within_batch(self):
        videos, duplicates = unique_videos(
            [{"id": "same", "title": "first"}, {"id": "same", "title": "second"}],
            "youtube",
        )
        self.assertEqual(len(videos), 1)
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(video_key(videos[0], "youtube"), "youtube:same")


if __name__ == "__main__":
    unittest.main()
