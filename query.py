import requests
from collections import defaultdict
from datetime import datetime, timedelta
import unicodedata
import asyncio
import json
import aiohttp

from auth import authenticate
from utils import xml_to_dict
from metrics import Metrics

BASE_URL = "https://fantasysports.yahooapis.com/fantasy/v2"


class Query:
    def __init__(self, league_key, token, doc_ref):
        self.num_requests = 0
        self.league_key = league_key
        self.game_id, _, self.league_id = league_key.split(".")
        self.game_logs_cache = {}
        self.doc_ref = doc_ref

        self.oauth = authenticate(token)
        self.oauth.refresh_access_token()  # Initialize self.token_time
        self.session = (
            aiohttp.ClientSession()
        )  # Need to use Peresistent session rather that "with" which automatically closes session TODO: handle retry

    @classmethod
    async def create(cls, league_key, token=None, doc_ref=None):
        # Handles async opereations on initialization
        instance = cls(league_key, token, doc_ref)

        await instance.get_league()
        instance.matchups = await instance.get_matchups()
        instance.game_weeks = await instance.get_game_weeks()

        return instance

    async def get_response(self, url):
        self.num_requests += 1
        if not self.oauth.token_is_valid():
            self.oauth.refresh_access_token()

        headers = {
            "Authorization": f"Bearer {self.oauth.access_token}",
            "Content-Type": "application/json",  # TODO: remove
        }
        async with self.session.get(BASE_URL + url, headers=headers) as response:
            xml = await response.text()
            if response.status != 200:
                print(response)
                print(xml)
                response.raise_for_status()
            data = xml_to_dict(xml)
            return data

    async def get_league(self):
        url = f"/league/{self.league_key};out=standings,settings"
        response = await self.get_response(url)
        league = response["league"]
        self.league_start_date_str = league["start_date"]
        self.league_end_date_str = league["end_date"]
        self.league_start_week = int(league["start_week"])
        self.league_end_week = int(league["end_week"])
        self.playoff_start_week = int(
            league["settings"].get("playoff_start_week", None)
        )
        self.league_season = int(league["season"])
        self.teams = league["standings"]["teams"]

    async def get_game_weeks(self):
        url = f"/game/{self.game_id}/game_weeks"
        response = await self.get_response(url)
        game_weeks = response["game"]["game_weeks"]
        game_weeks[self.league_start_week - 1][
            "start"
        ] = self.league_start_date_str  # Should it be -1 or -league_start_week?
        game_weeks[self.league_end_week - 1]["end"] = self.league_end_date_str
        return game_weeks

    def get_dates_by_week(
        self, week
    ):  # TODO: This shouldn't be making a request every time its called
        start_date_str = self.game_weeks[week - 1]["start"]
        end_date_str = self.game_weeks[week - 1]["end"]
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        dates = [
            (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range((end_date - start_date).days + 1)
        ]
        return dates

    def get_teams(self):
        """
        Returns:
        {[team_key: string]: {team_image: string, team_name: string, team_nickname: string}}
        """
        teams_dict = {
            team["team_key"]: {
                "image": team["managers"]["manager"]["image_url"],
                "name": team["name"],
                "nickname": team["managers"]["manager"]["nickname"],
            }
            for team in self.teams
        }
        return teams_dict

    def get_team_name_from_key(self, team_key):
        team_name = next(
            team["name"] for team in self.teams if team["team_key"] == team_key
        )
        return team_name

    async def get_players(self, player_keys):
        return [
            player
            for i in range(int(len(player_keys) / 25) + 1)
            for player in (
                await self.get_response(
                    f"/league/{self.league_key}/players;player_keys={','.join(player_keys[i*25:min((i+1)*25, len(player_keys))])};start={i*25}/stats"
                )
            )["league"]["players"]
        ]

    async def get_top_n_players_by_position(self, n, position):
        if position == "F":
            position = "C,LW,RW"
        return [
            player
            for i in range(int(n / 25) + 1)
            for player in (
                await self.get_response(
                    f"/league/{self.league_key}/players;sort=PTS;sort_type=season;position={position};count={n};start={i*25}/stats"
                )
            )["league"]["players"]
        ]

    def get_player_game_log_nhl(self, player_id):
        season = f"{self.league_season}{self.league_season+1}"
        return requests.get(
            f"https://api-web.nhle.com/v1/player/{player_id}/game-log/{season}/2"
        ).json()[
            "gameLog"
        ]  # 2 inndicates regular season games

    def get_game_log_by_player(self, player_key, player_name, player_position):
        if player_key in self.game_logs_cache:
            return self.game_logs_cache[player_key]
        player_name_url = player_name.replace(" ", "%20").replace("-", "%20")
        players_resp = requests.get(
            f"https://search.d3.nhle.com/api/v1/search/player?culture=en-us&limit=20&q={player_name_url}%2A"
        ).json()
        players = [
            player
            for player in players_resp
            if self.normalize_name(player["name"]) == player_name
        ]  # Matching names
        # If there are multiple players matching name, filter by other attributes
        if len(players) > 1:
            players = [
                player
                for player in players
                if player["lastSeasonId"]
                and int(player["lastSeasonId"][:4]) >= self.league_season
            ]
            if len(players) > 1:
                players = [
                    player
                    for player in players
                    if player["positionCode"] in player_position.split(",")
                ]
        if len(players) != 1:
            print(len(players), player_name, players)
        player = players[0]
        player_id = player["playerId"]
        player_game_log = self.get_player_game_log_nhl(player_id)
        self.game_logs_cache[player_key] = player_game_log
        return player_game_log

    def get_player_team_on_date(self, player_game_log, date):
        game = next(
            iter(
                [
                    game
                    for game in player_game_log
                    if datetime.strptime(game["gameDate"], "%Y-%m-%d")
                    <= datetime.strptime(date, "%Y-%m-%d")
                ]
            ),
            None,
        )
        if game is None:
            team = player_game_log[-1]["teamAbbrev"]
        else:
            team = game["teamAbbrev"]
        return team

    async def get_matchups(self):
        weeks = ",".join(
            [
                str(week)
                for week in range(self.league_start_week, self.league_end_week + 1)
            ]
        )
        url = f"/league/{self.league_key}/scoreboard;week={weeks}"
        response = await self.get_response(url)
        return response["league"]["scoreboard"]["matchups"]

    def get_opp_team_by_week(self, team_key, week):
        # TODO make this a dict to improve performance so don't have to search through list every time
        opp_key = [
            (
                matchup["teams"][0]["team_key"]
                if matchup["teams"][0]["team_key"] != team_key
                else matchup["teams"][1]["team_key"]
            )
            for matchup in self.matchups
            if int(matchup["week"]) == week
            and team_key in [team["team_key"] for team in matchup["teams"]]
        ]
        return opp_key[0] if len(opp_key) else None

    async def get_all_teams_daily_stats(self):
        start_date = datetime.strptime(self.league_start_date_str, "%Y-%m-%d")
        end_date = datetime.strptime(self.league_end_date_str, "%Y-%m-%d")
        dates = [
            (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range((end_date - start_date).days + 1)
        ]
        url = f"/league/{self.league_key}/teams/stats_collection;types=date;date={','.join(dates)}"
        response = await self.get_response(url)
        all_teams_daily_stats = response["league"]["teams"]
        all_teams_daily_stats_dict = {
            team["team_key"]: {
                team_points["date"]: float(team_points["total"])
                for team_points in team["team_stats_collection"]["team_points"]
            }
            for team in all_teams_daily_stats
        }  # Preprocess into dict for constant time lookup {[team_key: str]: {[date: str]: float}}
        return all_teams_daily_stats_dict

    async def get_players_points_by_date(
        self, player_team_dict, dates
    ):  # Look into whether or not its possible to do multiple dates in a single request
        if not player_team_dict:
            return {}
        player_keys = list(player_team_dict.keys())
        points_by_team = defaultdict(float)
        points_by_player = defaultdict(
            lambda: {"name": None, "image_url": None, "team_name": None, "points": 0}
        )
        for date_str in dates:
            for i in range(0, len(player_keys), 25):
                player_keys_csv = ",".join(
                    player_keys[i : min(i + 25, len(player_keys))]
                )
                url = f"/league/{self.league_key}/players;player_keys={player_keys_csv}/stats;type=date;date={date_str}"
                response = await self.get_response(url)
                players_stats_by_date = response["league"]["players"]
                for player in players_stats_by_date:
                    if player["player_key"] not in points_by_player:
                        points_by_player[player["player_key"]]["name"] = player["name"][
                            "full"
                        ]
                        points_by_player[player["player_key"]]["image_url"] = player[
                            "image_url"
                        ]
                        points_by_player[player["player_key"]]["team_keys"] = list(
                            player_team_dict[player["player_key"]]
                        )
                    points_by_player[player["player_key"]]["points"] = round(
                        points_by_player[player["player_key"]]["points"]
                        + float(player["player_points"]["total"]),
                        1,
                    )
        return points_by_player

    async def cleanup(self):
        await self.session.close()

    async def get_metrics(self):
        metrics = Metrics(self)
        tasks = [
            metrics.get_standings(),
            metrics.get_alternative_realities(),
            # metrics.get_draft_busts_steals(),
            # metrics.get_team_season_data(),
            # metrics.get_biggest_comebacks(),
            # metrics.get_worst_drops(),
        ]
        metrics_meta = {
            "official_standings": {
                "title": '"Official" Results',
                "description": "Sure, these are the official results. But were they really the best team? The luckiest? The biggest flop? Keep scrolling to uncover the real winners and losers of the season.",
                "type": "list",
            },
            "alternative_realities": {
                "title": "Alternative Realities",
                "description": "What if your team had a different schedule? This matrix reimagines the season by swapping team schedules, showing how records would have changed in an alternate universe. Did bad luck hold you back, or were you truly dominant no matter the matchups?",
                "type": "table",
            },
            "draft_steals": {
                "title": "Draft Steal",
                "description": "Some picks turn out to be absolute gems! This metric highlights the player who delivered the biggest return on investment, massively outperforming their draft position. Whether it was a late-round sleeper who dominated or a mid-round pick who played like a first-rounder, this is your league's ultimate steal of the draft.",
                "type": "list",
            },
            "draft_busts": {
                "title": "Draft Bust",
                "description": "Not all picks live up to the hype. This metric identifies the player who fell the hardest from expectations, drastically underperforming their draft position. Whether it was due to injuries, poor form, or just bad luck, this was the pick that stung the most for fantasy managers.",
                "type": "list",
            },
            "one_man_army": {
                "title": "One-Man Army",
                "description": "This metric highlights the player who carried the biggest scoring burden for their team by contributing the highest percentage of their team’s total points. It showcases which players were the most crucial to their team’s success, whether due to elite performance or a lack of supporting cast. A high percentage means this player was the go-to option, shouldering most of the team’s fantasy production.",
                "type": "list",
            },
            "team_tormentor": {
                "title": "Team Tormentor",
                "description": "This metric identifies the player who scored the most total points against a single team, revealing their toughest matchup.",
                "type": "list",
            },
            "biggest_comeback": {
                "title": "Greatest Comebacks",
                "description": "The most impressive turnarounds of the season! This stat highlights the teams that overcame the largest point deficits to secure a victory in a single week, proving that no lead is ever safe.",
                "type": "list",
            },
            "the_one_that_got_away": {
                "title": "The One That Got Away",
                "description": 'These players were the ultimate "what could have been" stories of the season. After being dropped, they went on to rack up the most points—leaving their former managers with major regret.',
                "type": "list",
            },
        }
        all_metrics = []
        for task in asyncio.as_completed(tasks):  # Yields tasks as they are completed
            results = await task  # Expects each task to return an array
            resp_vals = []
            for i, result in enumerate(results):
                resp_val = metrics_meta[result["id"]]
                resp_val["data"] = result["data"]
                if "headers" in result:  # For alternative realities
                    resp_val["headers"] = result["headers"]
                resp_vals.append(resp_val)
            json_resp_vals = json.dumps(
                resp_vals
            )  # StreamingResponse expects iterable of bytes or strings
            all_metrics.append(json_resp_vals)
            yield (json_resp_vals)
        if self.doc_ref:
            self.doc_ref.set({"metrics": all_metrics})
        await self.cleanup()
