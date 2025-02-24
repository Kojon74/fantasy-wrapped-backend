import os
from yahoo_oauth import OAuth2
import requests
from requests.adapters import HTTPAdapter, Retry
from utils import xml_to_dict
from collections import defaultdict

from yahoo_oauth_wrapper import YahooOAuthWrapper

BASE_URL = "https://fantasysports.yahooapis.com/fantasy/v2"

class Query():
    def __init__(self, token, league_key):
        self.oauth = self.authenticate(token)
        
        self.oauth.refresh_access_token() # In case access_token is already expired
        self.session = self.init_session()

        self.league_key = league_key
        self.game_id, _, self.league_id = league_key.split(".")
        self.get_league()


    def authenticate(self, token):
        return YahooOAuthWrapper(token["access_token"], token["refresh_token"])

    def init_session(self):
        session = requests.Session()
        retries = Retry(
            total=5,
            backoff_factor=0.1,
            status_forcelist=[ 500, 502, 503, 504 ]
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def get_response(self, url):
        if not self.oauth.token_is_valid():
            self.oauth.refresh_access_token()

        headers = {
            "Authorization": f"Bearer {self.oauth.access_token}",
            "Content-Type": "application/json"
        }
        response = self.session.get(url, headers=headers)
        if response.status_code != 200:
            print(response)
            print(response.text)
            response.raise_for_status()
        xml = response.text
        data = xml_to_dict(response.text)
        return data

    def get_league(self):
        url = f"{BASE_URL}/league/{self.league_key};out=standings,settings"
        league = self.get_response(url)["league"]
        self.league_start_week = int(league["start_week"])
        self.league_end_week = int(league["end_week"])
        self.playoff_start_week = int(league["settings"].get("playoff_start_week", None))
        self.teams = league["standings"]["teams"]

    def get_teams(self):
        """
        Returns:
        {[team_key: string]: {team_image: string, team_name: string, team_nickname: string}}
        """
        teams_dict = {team["team_key"]: {"image": team["managers"]["manager"]["image_url"], "name": team["name"], "nickname": team["managers"]["manager"]["nickname"]} for team in self.teams}
        standings = [{"key": team["team_key"], "value": i+1} for i, team in enumerate(self.teams)] # More efficient to combine two loops?
        return teams_dict, standings

    def get_players(self, player_keys):
        return [
            player 
            for i in range(int(len(player_keys) / 25) + 1)
            for player in self.get_response(
                f"https://fantasysports.yahooapis.com/fantasy/v2/league/{self.league_key}/players;player_keys={','.join(player_keys[i*25:min((i+1)*25, len(player_keys))])};start={i*25}/stats"
            )["league"]["players"]
        ]

    def get_top_n_players_by_position(self, n, position):
        if position == "F":
            position = "C,LW,RW"
        return [
            player 
            for i in range(int(n/25)+1) 
            for player in self.get_response(
                f"https://fantasysports.yahooapis.com/fantasy/v2/league/{self.league_key}/players;sort=PTS;sort_type=season;position={position};count={n};start={i*25}/stats"
            )["league"]["players"]
        ]

    def get_alternative_realities(self):
        """
        Returns:
        alternative_reality_matrix (float[][]): Matrix of records if each team had another teams schedule
        team_order (str[]): list of team_keys indicating the order of teams in the matrix
        """
        num_reg_weeks = self.playoff_start_week - self.league_start_week
        weeks = ",".join([str(week) for week in range(self.league_start_week, self.playoff_start_week)])
        url = f"https://fantasysports.yahooapis.com/fantasy/v2/league/{self.league_key}/scoreboard;week={weeks}/matchups"
        matchups = self.get_response(url)["league"]["scoreboard"]["matchups"]
        team_schedules = defaultdict(lambda: {"points": [], "opponent": []})
        for matchup in matchups:
            teams = matchup["teams"]
            team_schedules[teams[0]["team_key"]]["points"].append(float(teams[0]["team_points"]["total"]))
            team_schedules[teams[1]["team_key"]]["points"].append(float(teams[1]["team_points"]["total"]))
            team_schedules[teams[0]["team_key"]]["opponent"].append({"key": teams[1]["team_key"], "points": float(teams[1]["team_points"]["total"])})
            team_schedules[teams[1]["team_key"]]["opponent"].append({"key": teams[0]["team_key"], "points": float(teams[0]["team_points"]["total"])})
        team_schedule_matrix = [[0 for _ in range(len(self.teams))] for _ in range(len(self.teams))]
        for i, [team_a_key, team_a]  in enumerate(team_schedules.items()):
            for j, team_b in enumerate(team_schedules.values()):
                results = [0.5 if team_a_pts == team_opp["points"] else team_a_pts > team_opp["points"] for team_a_pts, team_opp in zip(team_a["points"], team_b["opponent"]) if team_opp["key"] != team_a_key]
                percent = round(sum(results)/len(results), 3)
                team_schedule_matrix[i][j] = percent
        team_order = list(team_schedules.keys())
        return team_schedule_matrix, team_order

    def get_draft_busts_steals(self):
        '''
        Biggest draft busts/steals
        '''
        # Get draft results
        url = f"{BASE_URL}/league/{self.league_key}/draftresults"
        draft_results = self.get_response(url)["league"]["draft_results"]
        draft_player_keys = [draft_result["player_key"] for draft_result in draft_results]
        draft_players = self.get_players(draft_player_keys)
        draft_players_by_pos = defaultdict(list)
        positions_map = {"C": "F", "LW": "F", "RW": "F", "D": "D", "G": "G"}
        for draft_player in draft_players:
            draft_players_by_pos[positions_map[draft_player["primary_position"]]].append(draft_player)
        # Get the top players by position
        top_players_by_pos = {
            "F": self.get_top_n_players_by_position(len(draft_players_by_pos["F"]), "F"), 
            "D": self.get_top_n_players_by_position(len(draft_players_by_pos["D"]), "D"), 
            "G": self.get_top_n_players_by_position(len(draft_players_by_pos["G"]), "G")
        }
        # Get differences between draft player and top player
        diffs = []
        for key in draft_players_by_pos:
            for draft_player, top_player in zip(draft_players_by_pos[key], top_players_by_pos[key]):
                diff = round(float(draft_player["player_points"]["total"]) - float(top_player["player_points"]["total"]), 1)
                diffs.append((diff, draft_player))
        smallest_diff = sorted(diffs, key=lambda x: x[0])
        biggest_diff = sorted(diffs, reverse=True, key=lambda x: x[0])
        draft_busts = [{"key": player["player_key"], "name": player["name"]["full"], "image": player["image_url"], "value": diff} for diff, player in smallest_diff[:5]]
        draft_steals = [{"key": player["player_key"], "name": player["name"]["full"], "image": player["image_url"], "value": diff} for diff, player in biggest_diff[:5]]
        return draft_busts, draft_steals