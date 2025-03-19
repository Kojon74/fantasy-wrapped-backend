import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta
from collections import defaultdict
from metrics import Metrics


class TestMetrics(unittest.TestCase):
    def setUp(self):
        # Mock the query object
        self.query = MagicMock()
        self.query.league_id = "97108"
        self.query.game_id = 427
        self.query.league_key = f"{game_id}.l.{league_id}"

        self.query.league_start_date_str = "2023-01-01"
        self.query.league_end_date_str = "2023-12-31"
        self.query.get_players_points_by_date = AsyncMock()
        self.query.get_team_name_from_key = MagicMock(return_value="Team Name")
        self.query.get_response = AsyncMock()

        # Create an instance of Metrics with the mocked query
        self.metrics = Metrics(self.query)

    @patch("metrics.datetime")
    @patch("metrics.defaultdict")
    async def test_get_worst_drops(self, mock_defaultdict, mock_datetime):
        # Mock datetime
        mock_datetime.strptime.side_effect = lambda *args, **kw: datetime.strptime(
            *args, **kw
        )
        mock_datetime.fromtimestamp.side_effect = (
            lambda *args, **kw: datetime.fromtimestamp(*args, **kw)
        )

        # Mock defaultdict
        mock_defaultdict.side_effect = lambda *args, **kw: defaultdict(*args, **kw)

        # Mock transactions response
        self.query.get_response.return_value = {
            "league": {
                "transactions": [
                    {
                        "timestamp": "1672531199",
                        "players": [
                            {
                                "player_key": "player1",
                                "transaction_data": {
                                    "type": "drop",
                                    "source_team_key": "team1",
                                },
                            },
                            {
                                "player_key": "player2",
                                "transaction_data": {
                                    "type": "add",
                                    "destination_team_key": "team2",
                                },
                            },
                        ],
                    }
                ]
            }
        }

        # Mock get_players_points_by_date response
        self.query.get_players_points_by_date.return_value = {
            "player1team1": {
                "name": "Player 1",
                "image_url": "http://example.com/player1.png",
                "team_keys": ["team1"],
                "points": 10.0,
            }
        }

        # Call the function
        result = await self.metrics.get_worst_drops()

        # Assertions
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "the_one_that_got_away")
        self.assertEqual(len(result[0]["data"]), 1)
        self.assertEqual(result[0]["data"][0]["main_text"], "Player 1")
        self.assertEqual(result[0]["data"][0]["sub_text"], "Team Name")
        self.assertEqual(result[0]["data"][0]["stat"], "10.0 pts")


if __name__ == "__main__":
    unittest.main()
