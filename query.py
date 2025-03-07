import os
from yahoo_oauth import OAuth2
import requests
from requests.adapters import HTTPAdapter, Retry
from utils import xml_to_dict
from collections import defaultdict
import unicodedata
from datetime import datetime, timedelta
from dotenv import load_dotenv

from yahoo_oauth_wrapper import YahooOAuthWrapper

load_dotenv()
CLIENT_ID = os.getenv("YAHOO_CONSUMER_KEY")
CLIENT_SECRET = os.getenv("YAHOO_CONSUMER_SECRET")

BASE_URL = "https://fantasysports.yahooapis.com/fantasy/v2"

class Query():
    def __init__(self, league_key, token=None):
        self.oauth = self.authenticate(token)
        
        self.oauth.refresh_access_token() # In case access_token is already expired
        self.session = self.init_session()

        self.league_key = league_key
        self.game_id, _, self.league_id = league_key.split(".")
        self.get_league()
        self.matchups = self.get_matchups()
        self.game_logs_cache = {}

    def authenticate(self, token):
        if not token:
            return OAuth2(CLIENT_ID, CLIENT_SECRET, browser_callback=True)
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
        self.league_start_date_str = league["start_date"]
        self.league_end_date_str = league["end_date"]
        self.league_start_week = int(league["start_week"])
        self.league_end_week = int(league["end_week"])
        self.playoff_start_week = int(league["settings"].get("playoff_start_week", None))
        self.league_season = int(league["season"])
        self.teams = league["standings"]["teams"]

    def get_game_weeks(self):
        url = f"{BASE_URL}/game/{self.game_id}/game_weeks"
        game_weeks = self.get_response(url)["game"]["game_weeks"]
        game_weeks[self.league_start_week-1]["start"] = self.league_start_date_str # Should it be -1 or -league_start_week?
        game_weeks[self.league_end_week-1]["end"] = self.league_end_date_str
        return game_weeks

    def get_dates_by_week(self, week):
        league_game_weeks = self.get_game_weeks()
        start_date_str = league_game_weeks[week-1]["start"]
        end_date_str = league_game_weeks[week-1]["end"]
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        dates = [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((end_date - start_date).days + 1)]
        return dates

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
                f"{BASE_URL}/league/{self.league_key}/players;player_keys={','.join(player_keys[i*25:min((i+1)*25, len(player_keys))])};start={i*25}/stats"
            )["league"]["players"]
        ]

    def get_top_n_players_by_position(self, n, position):
        if position == "F":
            position = "C,LW,RW"
        return [
            player 
            for i in range(int(n/25)+1) 
            for player in self.get_response(
                f"{BASE_URL}/league/{self.league_key}/players;sort=PTS;sort_type=season;position={position};count={n};start={i*25}/stats"
            )["league"]["players"]
        ]

    def normalize_name(self, name):
        # Normalize the name to NFKD form and remove diacritics
        return ''.join(
            c for c in unicodedata.normalize('NFKD', name)
            if not unicodedata.combining(c)
        )

    def get_player_game_log_nhl(self, player_id):
        season = f"{self.league_season}{self.league_season+1}"
        return requests.get(f"https://api-web.nhle.com/v1/player/{player_id}/game-log/{season}/2").json()["gameLog"] # 2 inndicates regular season games

    def get_game_log_by_player(self, player_key, player_name, player_position):
        if player_key in self.game_logs_cache:
            return self.game_logs_cache[player_key]
        player_name_url = player_name.replace(" ", "%20").replace("-", "%20")
        players_resp = requests.get(f"https://search.d3.nhle.com/api/v1/search/player?culture=en-us&limit=20&q={player_name_url}%2A").json()
        players = [player for player in players_resp if self.normalize_name(player["name"]) == player_name] # Matching names
        # If there are multiple players matching name, filter by other attributes
        if len(players) > 1:
            players = [player for player in players if player["lastSeasonId"] and int(player["lastSeasonId"][:4]) >= self.league_season]
            if len(players) > 1:
                players = [player for player in players if player["positionCode"] in player_position.split(",")]
        if len(players) != 1:
            print(len(players), player_name, players)
        player = players[0]
        player_id = player["playerId"]
        player_game_log = self.get_player_game_log_nhl(player_id)
        self.game_logs_cache[player_key] = player_game_log
        return player_game_log

    def get_player_team_on_date(self, player_game_log, date):
        game = next(iter([game for game in player_game_log if datetime.strptime(game["gameDate"], "%Y-%m-%d") <= datetime.strptime(date, "%Y-%m-%d")]), None)
        if game is None:
            team = player_game_log[-1]["teamAbbrev"]
        else:
            team = game["teamAbbrev"]
        return team

    def get_matchups(self):
        weeks = ",".join([str(week) for week in range(self.league_start_week, self.league_end_week + 1)])
        url = f"{BASE_URL}/league/{self.league_key}/scoreboard;week={weeks}"
        return self.get_response(url)["league"]["scoreboard"]["matchups"]

    def get_opp_team_by_week(self, team_key, week):
        # TODO make this a dict to improve performance so don't have to search through list every time
        opp_key = [matchup["teams"][0]["team_key"] if matchup["teams"][0]["team_key"] != team_key else matchup["teams"][1]["team_key"] for matchup in self.matchups if int(matchup["week"]) == week and team_key in [team["team_key"] for team in matchup["teams"]]]
        return opp_key[0] if len(opp_key) else None

    def get_all_teams_daily_stats(self):
        start_date = datetime.strptime(self.league_start_date_str, "%Y-%m-%d")
        end_date = datetime.strptime(self.league_end_date_str, "%Y-%m-%d")
        dates = [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((end_date - start_date).days + 1)]
        url = f"{BASE_URL}/league/{self.league_key}/teams/stats_collection;types=date;date={','.join(dates)}"
        all_teams_daily_stats = self.get_response(url)["league"]["teams"]
        all_teams_daily_stats_dict = {team["team_key"]: {team_points["date"]: float(team_points["total"]) for team_points in team["team_stats_collection"]["team_points"]} for team in all_teams_daily_stats} # Preprocess into dict for constant time lookup {[team_key: str]: {[date: str]: float}}
        return all_teams_daily_stats_dict

    def get_alternative_realities(self):
        """
        Returns:
        alternative_reality_matrix (float[][]): Matrix of records if each team had another teams schedule
        team_order (str[]): list of team_keys indicating the order of teams in the matrix
        """
        num_reg_weeks = self.playoff_start_week - self.league_start_week
        weeks = ",".join([str(week) for week in range(self.league_start_week, self.playoff_start_week)])
        url = f"{BASE_URL}/league/{self.league_key}/scoreboard;week={weeks}/matchups"
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
                percent = format(round(sum(results)/len(results), 3), ".3f")
                team_schedule_matrix[i][j] = percent
        team_order = [self.get_team_name_from_key(team_key) for team_key in team_schedules.keys()]
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
        draft_busts = [{"rank": i+1, "image_url": player["image_url"], "main_text": player["name"]["full"], "sub_text": self.get_team_name_from_key(player["team_key"]), "stat": f"{format(diff, '.1f')} pts"} for i, [diff, player] in enumerate(smallest_diff[:5])]
        draft_steals = [{"rank": i+1, "image_url": player["image_url"], "main_text": player["name"]["full"], "sub_text": self.get_team_name_from_key(player["team_key"]), "stat": f"+{format(diff, '.1f')} pts"} for i, [diff, player] in enumerate(biggest_diff[:5])]
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
        opp_players_by_team = defaultdict(lambda: defaultdict(lambda: {"name": None, "image_url": None, "points": 0}))
        for team in self.teams:
            team_points_by_nhl_team = defaultdict(float)
            team_points_by_player = defaultdict(lambda: {"name": None, "image_url": None, "points": 0})
            for week in range(self.league_start_week, self.league_end_week + 1):
                opp_team = self.get_opp_team_by_week(team["team_key"], week)
                if not opp_team:
                    # Means this team had no matchup for the current week, skip
                    continue
                week_end_date = self.get_dates_by_week(week)[-1]
                url = f"{BASE_URL}/team/{team['team_key']}/roster;week={week}/players/stats;type=week;week={week}"
                roster_players = self.get_response(url)["team"]["roster"]["players"]
                for player in roster_players:
                    hits_by_team[team["team_key"]] += next(iter([int(stat["value"]) for stat in player["player_stats"]["stats"] if int(stat["stat_id"]) == HITS_STAT_ID and stat["value"] != "-"]), 0)
                    
                    if not player["player_points"]["total"]:
                        # Can skip rest if no points
                        continue

                    # Team points by player
                    if team_points_by_player[player["player_key"]]["name"] is None:
                        team_points_by_player[player["player_key"]]["name"] = player["name"]["full"]
                        team_points_by_player[player["player_key"]]["image_url"] = player["image_url"]
                    team_points_by_player[player["player_key"]]["points"] += float(player["player_points"]["total"])

                    # Team points by opposing player
                    if opp_players_by_team[opp_team][player["player_key"]]["name"] is None:
                        opp_players_by_team[opp_team][player["player_key"]]["name"] = player["name"]["full"]
                        opp_players_by_team[opp_team][player["player_key"]]["image_url"] = player["image_url"]
                    opp_players_by_team[opp_team][player["player_key"]]["points"] += float(player["player_points"]["total"])

                    # Team points by NHL team
                    # player_game_log = self.get_game_log_by_player(player["player_key"], player["name"]["full"], player["display_position"])
                    # nhl_team = self.get_player_team_on_date(player_game_log, week_end_date)
                    # team_points_by_nhl_team[nhl_team] += float(player["player_points"]["total"])
                    
            team_points_by_nhl_team = sorted(team_points_by_nhl_team.items(), key=lambda item: item[1], reverse=True)
            team_points_by_player = sorted(team_points_by_player.values(), key=lambda value: value["points"], reverse=True)
            # top_nhl_team = team_points_by_nhl_team[0][0]
            # top_nhl_team_pct = round(team_points_by_nhl_team[0][1]/sum([row[1] for row in team_points_by_nhl_team])*100)
            top_player = team_points_by_player[0]
            top_player_pct = round(top_player["points"]/sum([row["points"] for row in team_points_by_player])*100)
            top_player_by_team[team["team_key"]] = {"player_name": top_player["name"], "player_img": top_player["image_url"], "player_pct": top_player_pct}
        top_player_by_team_sorted = sorted(top_player_by_team.items(), key=lambda x: x[1]["player_pct"], reverse=True)
        top_player_by_team_sorted_ret = [
            {
                "rank": i+1, 
                "image_url": v["player_img"], 
                "main_text": v["player_name"], 
                "sub_text": self.get_team_name_from_key(k), 
                "stat": f'{v["player_pct"]}%'
            } for i, [k, v] in enumerate(top_player_by_team_sorted)
        ]
        top_opp_player_by_team = {k: sorted(v.values(), key=lambda x: x["points"], reverse=True)[0] for k, v in opp_players_by_team.items()}
        top_opp_player_by_team_sorted = sorted(top_opp_player_by_team.items(), key=lambda x: x[1]["points"], reverse=True)
        top_opp_player_by_team_sorted_ret = [{"rank": i+1, "image_url": v["image_url"], "main_text": v["name"], "sub_text": self.get_team_name_from_key(k), "stat": f'{format(round(v["points"], 1), ".1f")} pts'} for i, [k, v] in enumerate(top_opp_player_by_team_sorted)]
        return top_player_by_team_sorted_ret, top_opp_player_by_team_sorted_ret

    def get_biggest_comebacks(self):
        '''
        Biggest comeback
        52.8s
        '''
        deficits = []
        all_teams_daily_stats = self.get_all_teams_daily_stats()
        for matchup in self.matchups:
            # Comeback win can't happen without a winner
            if int(matchup["is_tied"]):
                continue
            team_keys = [matchup["teams"][0]["team_key"], matchup["teams"][1]["team_key"]]
            team_w_idx, team_l_idx = [0, 1] if team_keys[0] == matchup["winner_team_key"] else [1, 0]
            team_w_key, team_l_key = [team_keys[team_w_idx], team_keys[team_l_idx]]
            deficit = 0
            start_date = datetime.strptime(matchup["week_start"], "%Y-%m-%d")
            end_date = datetime.strptime(matchup["week_end"], "%Y-%m-%d")
            # Don't include the last day since the matchup is over
            for i in range((end_date - start_date).days):
                current_date_str = (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
                team_w_points = all_teams_daily_stats[team_w_key][current_date_str]
                team_l_points = all_teams_daily_stats[team_l_key][current_date_str]
                deficit = round(deficit + team_l_points - team_w_points, 1)
                if deficit > 0:
                    deficits.append((deficit, {"week": matchup["week"], "winner_team_key": matchup["winner_team_key"], "team_image_url": matchup["teams"][team_w_idx]["team_logos"]["team_logo"]["url"], "team_name": matchup["teams"][team_w_idx]["name"], "opp_team_name": matchup["teams"][team_l_idx]["name"]}))
        biggest_deficits = sorted(deficits, key=lambda x: x[0]) # This needs to be in ascending order so when duplicates are removed only the last (largest) is kept
        biggest_deficits = list({f'{matchup["week"]}.{matchup["winner_team_key"]}': (deficit, matchup) for (deficit, matchup) in biggest_deficits}.values()) # This removes duplicates from same matchup
        biggest_deficits = sorted(biggest_deficits, reverse=True, key=lambda x: x[0])
        biggest_combacks = [{"rank": i+1, "image_url": matchup["team_image_url"], "main_text": matchup["team_name"], "sub_text": f'Week {matchup["week"]} vs {matchup["opp_team_name"]}', "stat": f"{format(deficit, '.1f')} pts"} for i, [deficit, matchup] in enumerate(biggest_deficits[:5])]
        return biggest_combacks

    def get_metrics(self):
        standings = self.get_standings()
        # alternative_reality_matrix, team_order = self.get_alternative_realities()
        # draft_busts, draft_steals = self.get_draft_busts_steals()
        # top_players_by_team, top_opp_players_by_team = self.get_team_season_data()
        biggest_comebacks = self.get_biggest_comebacks()
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
            # {
            #     "title": 'Draft Steal',
            #     "description": "Some picks turn out to be absolute gems! This metric highlights the player who delivered the biggest return on investment, massively outperforming their draft position. Whether it was a late-round sleeper who dominated or a mid-round pick who played like a first-rounder, this is your league's ultimate steal of the draft.",
            #     "type": "list",
            #     "data": draft_steals
            # },
            # {
            #     "title": 'Draft Bust',
            #     "description": "Not all picks live up to the hype. This metric identifies the player who fell the hardest from expectations, drastically underperforming their draft position. Whether it was due to injuries, poor form, or just bad luck, this was the pick that stung the most for fantasy managers.",
            #     "type": "list",
            #     "data": draft_busts
            # },
            # {
            #     "title": 'One-Man Army',
            #     "description": "This metric highlights the player who carried the biggest scoring burden for their team by contributing the highest percentage of their team’s total points. It showcases which players were the most crucial to their team’s success, whether due to elite performance or a lack of supporting cast. A high percentage means this player was the go-to option, shouldering most of the team’s fantasy production.",
            #     "type": "list",
            #     "data": top_players_by_team
            # },
            # {
            #     "title": 'Team Tormentor',
            #     "description": "This metric identifies the player who scored the most total points against a single team, revealing their toughest matchup.",
            #     "type": "list",
            #     "data": top_opp_players_by_team
            # },
            {
                "title": 'Greatest Comebacks',
                "description": "The most impressive turnarounds of the season! This stat highlights the teams that overcame the largest point deficits to secure a victory in a single week, proving that no lead is ever safe.",
                "type": "list",
                "data": biggest_comebacks
            },
        ]
        return metrics
