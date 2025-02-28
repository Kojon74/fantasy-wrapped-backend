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
        return teams_dict

    def get_team_name_from_key(self, team_key):
        team_name = next(team["name"] for team in self.teams if team["team_key"] == team_key)
        return team_name

    def get_standings(self):
        standings = [{"rank": i+1, "image_url": team["team_logos"]["team_logo"]["url"], "main_text": team["name"]} for i, team in enumerate(self.teams)]
        return standings

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
        # draft results doesn't return player stats
        draft_player_keys = [draft_result["player_key"] for draft_result in draft_results]
        draft_players = self.get_players(draft_player_keys)
        # Add some way to refeerence back to the team that drafted each player
        for draft_player, draft_results in zip(draft_players, draft_results): # TODO: See if using list comprehension would be faster, would be moree memory intensive
            draft_player["team_key"] = draft_results["team_key"]
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
        for pos in draft_players_by_pos:
            for draft_player, top_player in zip(draft_players_by_pos[pos], top_players_by_pos[pos]):
                diff = round(float(draft_player["player_points"]["total"]) - float(top_player["player_points"]["total"]), 1)
                diffs.append((diff, draft_player))
        smallest_diff = sorted(diffs, key=lambda x: x[0])
        biggest_diff = sorted(diffs, reverse=True, key=lambda x: x[0])
        draft_busts = [{"rank": i+1, "image_url": player["image_url"], "main_text": player["name"]["full"], "sub_text": self.get_team_name_from_key(player["team_key"]), "stat": diff} for i, [diff, player] in enumerate(smallest_diff[:5])]
        draft_steals = [{"rank": i+1, "image_url": player["image_url"], "main_text": player["name"]["full"], "sub_text": self.get_team_name_from_key(player["team_key"]), "stat": diff} for i, [diff, player] in enumerate(biggest_diff[:5])]
        return draft_busts, draft_steals

    def get_team_season_data(self):
        """
        Returns:
        NHL team that contributed most to each team
        Player that contributed most to each team
        Team with most hits
        """
        HITS_STAT_ID = 31
        hits_by_team = defaultdict(int)
        top_player_by_team = {}
        for team in self.teams:
            team_points_by_nhl_team = defaultdict(float)
            team_points_by_player = defaultdict(lambda: {"name": None, "image_url": None, "points": 0})
            for week in range(league_start_week, league_end_week + 1):
                week_end_date = get_dates_by_week(week)[-1]
                url = f"https://fantasysports.yahooapis.com/fantasy/v2/team/{team['team_key']}/roster;week={week}/players/stats;type=week;week={week}"
                roster_players = get_response(url)["team"]["roster"]["players"]
                for player in roster_players:
                    hits_by_team[team["team_key"]] += next(iter([int(stat["value"]) for stat in player["player_stats"]["stats"] if int(stat["stat_id"]) == HITS_STAT_ID and stat["value"] != "-"]), 0)
                    
                    if not player["player_points"]["total"]:
                        # Can skip rest if no points
                        continue
                    player_game_log = get_game_log_by_player(player["player_key"], player["name"]["full"], player["display_position"])

                    # Team points by player
                    if team_points_by_player[player["player_key"]]["name"] is None:
                        team_points_by_player[player["player_key"]]["name"] = player["name"]["full"]
                        team_points_by_player[player["player_key"]]["image_url"] = player["image_url"]
                    team_points_by_player[player["player_key"]]["points"] += float(player["player_points"]["total"])

                    # Team points by NHL team
                    nhl_team = get_player_team_on_date(player_game_log, week_end_date)
                    team_points_by_nhl_team[nhl_team] += float(player["player_points"]["total"])
                    
            team_points_by_nhl_team = sorted(team_points_by_nhl_team.items(), key=lambda item: item[1], reverse=True)
            team_points_by_player = sorted(team_points_by_player.values(), key=lambda value: value["points"], reverse=True)
            top_nhl_team = team_points_by_nhl_team[0][0]
            top_nhl_team_pct = round(team_points_by_nhl_team[0][1]/sum([row[1] for row in team_points_by_nhl_team])*100)
            top_player = team_points_by_player[0]
            top_player_pct = round(top_player["points"]/sum([row["points"] for row in team_points_by_player])*100)
            top_player_by_team[team["team_key"]] = {"player_name": top_player["name"], "player_pct": top_player_pct}

    def get_metrics(self):
        standings = self.get_standings()
        alternative_reality_matrix, team_order = self.get_alternative_realities()
        draft_busts, draft_steals = self.get_draft_busts_steals()
        metrics = [
            {
                "title": '"Official" Results',
                "description": "Sure, these are the official results. But were they really the best team? The luckiest? The biggest flop? Keep scrolling to uncover the real winners and losers of the season.",
                "type": "list",
                "data": standings
            },
            # {
            #     "title": 'Alternative Realities',
            #     "description": "What if your team had a different schedule? This matrix reimagines the season by swapping team schedules, showing how records would have changed in an alternate universe. Did bad luck hold you back, or were you truly dominant no matter the matchups?",
            #     "type": "table",
            #     "headers": team_order,
            #     "data": alternative_reality_matrix
            # },
            {
                "title": 'Draft Steal',
                "description": "Some picks turn out to be absolute gems! This metric highlights the player who delivered the biggest return on investment, massively outperforming their draft position. Whether it was a late-round sleeper who dominated or a mid-round pick who played like a first-rounder, this is your league's ultimate steal of the draft.",
                "type": "list",
                "data": draft_steals
            },
            {
                "title": 'Draft Bust',
                "description": "Not all picks live up to the hype. This metric identifies the player who fell the hardest from expectations, drastically underperforming their draft position. Whether it was due to injuries, poor form, or just bad luck, this was the pick that stung the most for fantasy managers.",
                "type": "list",
                "data": draft_busts
            }
        ]
        return metrics
