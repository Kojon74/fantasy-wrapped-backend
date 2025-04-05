from collections import defaultdict
from datetime import datetime, timedelta

# import pandas as pd


class Metrics:
    def __init__(self, query):
        self.query = query

    async def get_standings(self):
        standings = [
            {
                "rank": i + 1,
                "image_url": team["team_logos"]["team_logo"]["url"],
                "main_text": team["name"],
            }
            for i, team in enumerate(self.query.teams)
        ]
        return [{"id": "official_standings", "data": standings}]

    async def get_alternative_realities(self):
        """
        Returns:
        alternative_reality_matrix (float[][]): Matrix of records if each team had another teams schedule
        team_order (str[]): list of team_keys indicating the order of teams in the matrix
        """
        self.query.num_requests = 0
        num_reg_weeks = self.query.playoff_start_week - self.query.league_start_week
        weeks = ",".join(
            [
                str(week)
                for week in range(
                    self.query.league_start_week, self.query.playoff_start_week
                )
            ]
        )
        url = f"/league/{self.query.league_key}/scoreboard;week={weeks}/matchups"
        response = await self.query.get_response(url)
        matchups = response["league"]["scoreboard"]["matchups"]
        team_schedules = defaultdict(lambda: {"points": [], "opponent": []})
        for matchup in matchups:
            teams = matchup["teams"]
            team_schedules[teams[0]["team_key"]]["points"].append(
                float(teams[0]["team_points"]["total"])
            )
            team_schedules[teams[1]["team_key"]]["points"].append(
                float(teams[1]["team_points"]["total"])
            )
            team_schedules[teams[0]["team_key"]]["opponent"].append(
                {
                    "key": teams[1]["team_key"],
                    "points": float(teams[1]["team_points"]["total"]),
                }
            )
            team_schedules[teams[1]["team_key"]]["opponent"].append(
                {
                    "key": teams[0]["team_key"],
                    "points": float(teams[0]["team_points"]["total"]),
                }
            )
        team_schedule_matrix = [
            [0 for _ in range(len(self.query.teams))]
            for _ in range(len(self.query.teams))
        ]
        for i, [team_a_key, team_a] in enumerate(team_schedules.items()):
            for j, team_b in enumerate(team_schedules.values()):
                results = [
                    (
                        0.5
                        if team_a_pts == team_opp["points"]
                        else team_a_pts > team_opp["points"]
                    )
                    for team_a_pts, team_opp in zip(
                        team_a["points"], team_b["opponent"]
                    )
                    if team_opp["key"] != team_a_key
                ]
                percent = format(round(sum(results) / len(results), 3), ".3f")
                team_schedule_matrix[i][j] = percent
        team_order = [
            self.query.get_team_name_from_key(team_key)
            for team_key in team_schedules.keys()
        ]
        # print(f'Alternative Realities: {self.query.num_requests}')
        return [
            {
                "id": "alternative_realities",
                "data": team_schedule_matrix,
                "headers": team_order,
            }
        ]

    async def get_draft_busts_steals(self):
        """
        Biggest draft busts/steals
        """
        self.query.num_requests = 0
        # Get draft results
        url = f"/league/{self.query.league_key}/draftresults"
        response = await self.query.get_response(url)
        draft_results = response["league"]["draft_results"]
        # draft results doesn't return player stats
        draft_player_keys = [
            draft_result["player_key"] for draft_result in draft_results
        ]
        draft_players = await self.query.get_players(draft_player_keys)
        # Add some way to refeerence back to the team that drafted each player
        for draft_player, draft_results in zip(
            draft_players, draft_results
        ):  # TODO: See if using list comprehension would be faster, would be moree memory intensive
            draft_player["team_key"] = draft_results["team_key"]
        draft_players_by_pos = defaultdict(list)
        positions_map = {"C": "F", "LW": "F", "RW": "F", "D": "D", "G": "G"}
        for draft_player in draft_players:
            draft_players_by_pos[
                positions_map[draft_player["primary_position"]]
            ].append(draft_player)
        # Get the top players by position
        top_players_by_pos = {
            "F": await self.query.get_top_n_players_by_position(
                len(draft_players_by_pos["F"]), "F"
            ),
            "D": await self.query.get_top_n_players_by_position(
                len(draft_players_by_pos["D"]), "D"
            ),
            "G": await self.query.get_top_n_players_by_position(
                len(draft_players_by_pos["G"]), "G"
            ),
        }
        # Get differences between draft player and top player
        diffs = []
        for pos in draft_players_by_pos:
            for draft_player, top_player in zip(
                draft_players_by_pos[pos], top_players_by_pos[pos]
            ):
                diff = round(
                    float(draft_player["player_points"][0]["total"])
                    - float(top_player["player_points"][0]["total"]),
                    1,
                )
                diffs.append((diff, draft_player))
        smallest_diff = sorted(diffs, key=lambda x: x[0])
        biggest_diff = sorted(diffs, reverse=True, key=lambda x: x[0])
        draft_busts = [
            {
                "rank": i + 1,
                "image_url": player["image_url"],
                "main_text": player["name"]["full"],
                "sub_text": self.query.get_team_name_from_key(player["team_key"]),
                "stat": f"{format(diff, '.1f')} pts",
            }
            for i, [diff, player] in enumerate(smallest_diff[:5])
        ]
        draft_steals = [
            {
                "rank": i + 1,
                "image_url": player["image_url"],
                "main_text": player["name"]["full"],
                "sub_text": self.query.get_team_name_from_key(player["team_key"]),
                "stat": f"+{format(diff, '.1f')} pts",
            }
            for i, [diff, player] in enumerate(biggest_diff[:5])
        ]
        # print(f'Draft Busts/Steals: {self.query.num_requests}')
        return [
            {"id": "draft_busts", "data": draft_busts},
            {"id": "draft_steals", "data": draft_steals},
        ]

    async def get_team_season_data(self):
        """
        Returns:
        NHL team that contributed most to each team
        Player that contributed most to each team
        Team with most hits
        """
        self.query.num_requests = 0
        HITS_STAT_ID = 31
        hits_by_team = defaultdict(int)
        top_player_by_team = {}
        opp_players_by_team = defaultdict(
            lambda: defaultdict(lambda: {"name": None, "image_url": None, "points": 0})
        )
        for team in self.query.teams:
            team_points_by_nhl_team = defaultdict(float)
            team_points_by_player = defaultdict(
                lambda: {"name": None, "image_url": None, "points": 0}
            )
            for week in range(
                self.query.league_start_week, self.query.league_end_week + 1
            ):
                opp_team = self.query.get_opp_team_by_week(team["team_key"], week)
                if not opp_team:
                    # Means this team had no matchup for the current week, skip
                    continue
                week_end_date = self.query.get_dates_by_week(week)[-1]
                url = f"/team/{team['team_key']}/roster;week={week}/players/stats;type=week;week={week}"
                response = await self.query.get_response(url)
                roster_players = response["team"]["roster"]["players"]
                for player in roster_players:
                    hits_by_team[team["team_key"]] += next(
                        iter(
                            [
                                int(stat["value"])
                                for stat in player["player_stats"][0]["stats"]
                                if int(stat["stat_id"]) == HITS_STAT_ID
                                and stat["value"] != "-"
                            ]
                        ),
                        0,
                    )

                    if not player["player_points"][0]["total"]:
                        # Can skip rest if no points
                        continue

                    # Team points by player
                    if team_points_by_player[player["player_key"]]["name"] is None:
                        team_points_by_player[player["player_key"]]["name"] = player[
                            "name"
                        ]["full"]
                        team_points_by_player[player["player_key"]]["image_url"] = (
                            player["image_url"]
                        )
                    team_points_by_player[player["player_key"]]["points"] += float(
                        player["player_points"][0]["total"]
                    )

                    # Team points by opposing player
                    if (
                        opp_players_by_team[opp_team][player["player_key"]]["name"]
                        is None
                    ):
                        opp_players_by_team[opp_team][player["player_key"]]["name"] = (
                            player["name"]["full"]
                        )
                        opp_players_by_team[opp_team][player["player_key"]][
                            "image_url"
                        ] = player["image_url"]
                    opp_players_by_team[opp_team][player["player_key"]][
                        "points"
                    ] += float(player["player_points"][0]["total"])

                    # Team points by NHL team
                    # player_game_log = self.query.get_game_log_by_player(player["player_key"], player["name"]["full"], player["display_position"])
                    # nhl_team = self.query.get_player_team_on_date(player_game_log, week_end_date)
                    # team_points_by_nhl_team[nhl_team] += float(player["player_points"][0]["total"])

            team_points_by_nhl_team = sorted(
                team_points_by_nhl_team.items(), key=lambda item: item[1], reverse=True
            )
            team_points_by_player = sorted(
                team_points_by_player.values(),
                key=lambda value: value["points"],
                reverse=True,
            )
            # top_nhl_team = team_points_by_nhl_team[0][0]
            # top_nhl_team_pct = round(team_points_by_nhl_team[0][1]/sum([row[1] for row in team_points_by_nhl_team])*100)
            top_player = team_points_by_player[0]
            top_player_pct = round(
                top_player["points"]
                / sum([row["points"] for row in team_points_by_player])
                * 100
            )
            top_player_by_team[team["team_key"]] = {
                "player_name": top_player["name"],
                "player_img": top_player["image_url"],
                "player_pct": top_player_pct,
            }
        top_player_by_team_sorted = sorted(
            top_player_by_team.items(), key=lambda x: x[1]["player_pct"], reverse=True
        )
        top_player_by_team_sorted_ret = [
            {
                "rank": i + 1,
                "image_url": v["player_img"],
                "main_text": v["player_name"],
                "sub_text": self.query.get_team_name_from_key(k),
                "stat": f'{v["player_pct"]}%',
            }
            for i, [k, v] in enumerate(top_player_by_team_sorted)
        ]
        top_opp_player_by_team = {
            k: sorted(v.values(), key=lambda x: x["points"], reverse=True)[0]
            for k, v in opp_players_by_team.items()
        }
        top_opp_player_by_team_sorted = sorted(
            top_opp_player_by_team.items(), key=lambda x: x[1]["points"], reverse=True
        )
        top_opp_player_by_team_sorted_ret = [
            {
                "rank": i + 1,
                "image_url": v["image_url"],
                "main_text": v["name"],
                "sub_text": self.query.get_team_name_from_key(k),
                "stat": f'{format(round(v["points"], 1), ".1f")} pts',
            }
            for i, [k, v] in enumerate(top_opp_player_by_team_sorted)
        ]
        # print(f'Top Players: {self.query.num_requests}')
        return [
            {"id": "one_man_army", "data": top_player_by_team_sorted_ret},
            {"id": "team_tormentor", "data": top_opp_player_by_team_sorted_ret},
        ]

    async def get_biggest_comebacks(self):
        """
        Biggest comeback
        52.8s
        """
        self.query.num_requests = 0
        deficits = []
        all_teams_daily_stats = await self.query.get_all_teams_daily_stats()
        for matchup in self.query.matchups:
            # Comeback win can't happen without a winner
            if int(matchup["is_tied"]):
                continue
            team_keys = [
                matchup["teams"][0]["team_key"],
                matchup["teams"][1]["team_key"],
            ]
            team_w_idx, team_l_idx = (
                [0, 1] if team_keys[0] == matchup["winner_team_key"] else [1, 0]
            )
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
                    deficits.append(
                        (
                            deficit,
                            {
                                "week": matchup["week"],
                                "winner_team_key": matchup["winner_team_key"],
                                "team_image_url": matchup["teams"][team_w_idx][
                                    "team_logos"
                                ]["team_logo"]["url"],
                                "team_name": matchup["teams"][team_w_idx]["name"],
                                "opp_team_name": matchup["teams"][team_l_idx]["name"],
                            },
                        )
                    )
        biggest_deficits = sorted(
            deficits, key=lambda x: x[0]
        )  # This needs to be in ascending order so when duplicates are removed only the last (largest) is kept
        biggest_deficits = list(
            {
                f'{matchup["week"]}.{matchup["winner_team_key"]}': (deficit, matchup)
                for (deficit, matchup) in biggest_deficits
            }.values()
        )  # This removes duplicates from same matchup
        biggest_deficits = sorted(biggest_deficits, reverse=True, key=lambda x: x[0])
        biggest_combacks = [
            {
                "rank": i + 1,
                "image_url": matchup["team_image_url"],
                "main_text": matchup["team_name"],
                "sub_text": f'Week {matchup["week"]} vs {matchup["opp_team_name"]}',
                "stat": f"{format(deficit, '.1f')} pts",
            }
            for i, [deficit, matchup] in enumerate(biggest_deficits[:5])
        ]
        # print(f'Biggest Comebacks: {self.query.num_requests}')
        return [{"id": "biggest_comeback", "data": biggest_combacks}]

    async def get_worst_drops(self):
        async def update_drop_players_points(drop_players_dict, dates):
            players = list(drop_players_dict.keys())
            drop_players_points_cur = await self.query.get_players_points_by_date(
                players, dates
            )
            for player_key, drop_player in drop_players_points_cur.items():
                for team_key in drop_players_dict[player_key]:
                    key = player_key + team_key
                    if key not in drop_players_points:
                        drop_players_points[key]["player_name"] = drop_player["name"]
                        drop_players_points[key]["image_url"] = drop_player["image_url"]
                        drop_players_points[key]["team_name"] = (
                            self.query.get_team_name_from_key(team_key)
                        )
                    drop_players_points[key]["points"] = round(
                        drop_players_points[key]["points"] + drop_player["points"], 1
                    )

        def get_dates(start_date, end_date):
            return [
                (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
                for i in range((end_date.date() - start_date.date()).days)
                if start_date + timedelta(days=i - 1)
                < datetime.strptime(self.query.league_end_date_str, "%Y-%m-%d")
            ]

        self.query.num_requests = 0
        url = f"/league/{self.query.league_key}/transactions"
        response = await self.query.get_response(url)
        transactions = list(reversed(response["league"]["transactions"]))
        last_transaction_date = datetime.strptime(
            self.query.league_start_date_str, "%Y-%m-%d"
        )
        drop_players_dict = defaultdict(set)
        drop_players_remove = []
        drop_players_points = defaultdict(
            lambda: {
                "player_name": None,
                "image_url": None,
                "team_name": None,
                "points": 0,
            }
        )
        done = False
        for transaction in transactions:
            if not "players" in transaction:
                continue
            for player in transaction["players"]:
                if player["transaction_data"]["type"] in ["add", "drop"]:
                    if player["transaction_data"]["type"] == "add":
                        # This needs to be at the top because team needs to get removed in current iteration
                        drop_players_remove.append(
                            {
                                "player_key": player["player_key"],
                                "team_key": player["transaction_data"][
                                    "destination_team_key"
                                ],
                            }
                        )
                    transaction_date = datetime.fromtimestamp(
                        int(transaction["timestamp"])
                    )
                    if transaction_date.strftime(
                        "%Y-%m-%d"
                    ) != last_transaction_date.strftime("%Y-%m-%d"):
                        # If new date, calculate points accumulated by dropped players
                        if (
                            last_transaction_date > transaction_date
                            and player["transaction_data"]["type"] == "drop"
                        ):
                            # Accounts for transactions before league start date
                            drop_players_dict[player["player_key"]].add(
                                player["transaction_data"]["source_team_key"]
                            )
                            continue
                        elif last_transaction_date > transaction_date:
                            continue
                        dates = get_dates(last_transaction_date, transaction_date)
                        await update_drop_players_points(drop_players_dict, dates)
                        if transaction_date > datetime.strptime(
                            self.query.league_end_date_str, "%Y-%m-%d"
                        ):
                            done = True
                            break
                        last_transaction_date = datetime.strptime(
                            dates[-1], "%Y-%m-%d"
                        ) + timedelta(days=1)
                        for drop_player_remove in drop_players_remove:
                            drop_players_dict[drop_player_remove["player_key"]].discard(
                                drop_player_remove["team_key"]
                            )
                            if (
                                len(drop_players_dict[drop_player_remove["player_key"]])
                                == 0
                            ):
                                drop_players_dict.pop(
                                    drop_player_remove["player_key"], None
                                )
                    if player["transaction_data"]["type"] == "drop":
                        drop_players_dict[player["player_key"]].add(
                            player["transaction_data"]["source_team_key"]
                        )
            if done:
                break
        if (
            last_transaction_date.date()
            != datetime.strptime(self.query.league_end_date_str, "%Y-%m-%d").date()
        ):
            # If last transaction was not on or past the league end date, get points until league end date
            league_end_date = datetime.strptime(
                self.query.league_end_date_str, "%Y-%m-%d"
            )
            dates = get_dates(last_transaction_date, league_end_date)
            await update_drop_players_points(drop_players_dict, dates)
        # print(self.query.num_requests)
        worst_drops = sorted(
            drop_players_points.values(), key=lambda x: x["points"], reverse=True
        )[:10]
        worst_drops = [
            {
                "rank": i + 1,
                "image_url": worst_drop["image_url"],
                "main_text": worst_drop["player_name"],
                "sub_text": worst_drop["team_name"],
                "stat": f'{worst_drop["points"]} pts',
            }
            for i, worst_drop in enumerate(worst_drops)
        ]
        return [{"id": "the_one_that_got_away", "data": worst_drops}]

    async def get_most_dropped_players(self):
        url = f"/league/{self.query.league_key}/transactions"
        response = await self.query.get_response(url)
        transactions = response["league"]["transactions"]
        drops = {}
        missed = 0
        for transaction in transactions:
            if (transaction["type"] == "drop") and transaction[
                "status"
            ] == "successful":
                try:
                    drops[transaction["players"][0]["player_key"]][1] += 1
                except:
                    drops[transaction["players"][0]["player_key"]] = [
                        transaction["players"][0]["name"]["full"],
                        1,
                    ]
            elif (
                transaction["type"] == "add/drop"
                and transaction["status"] == "successful"
            ):
                try:
                    drops[transaction["players"][1]["player_key"]][1] += 1
                except:
                    drops[transaction["players"][1]["player_key"]] = [
                        transaction["players"][1]["name"]["full"],
                        1,
                    ]

        drops = dict(sorted(drops.items(), key=lambda item: item[1][1], reverse=True))
        top_x = 10
        players = await self.query.get_players(list(drops.keys())[:top_x])
        top_drops_list = [
            {
                "rank": i + 1,
                "image_url": players[i]["image_url"],
                "main_text": list(drops.values())[i][0],
                "sub_test": "",
                "stat": f"{list(drops.values())[i][1]} add/drops",
            }
            for i in range(top_x)
        ]

        return [{"id": "most_dropped", "data": top_drops_list}]

    async def get_best_worst_drafts(self):
        url = f"/league/{self.query.league_key}/draftresults"
        response = await self.query.get_response(url)
        full_draft = response["league"]["draft_results"]
        full_draft = pd.DataFrame(
            data=full_draft, columns=["pick", "round", "team_key", "player_key"]
        )
        teams = self.query.get_teams()
        team_keys = tuple(teams.keys())
        team_drafts = {
            self.query.get_team_name_from_key(team_key): full_draft[
                full_draft["team_key"] == team_key
            ]
            for team_key in team_keys
        }
        ranked_drafts_list = []
        i = 0
        for team, draft in team_drafts.items():
            stats = await self.query.get_players(player_keys=draft["player_key"])
            ranked_drafts_list.append(
                {
                    "rank": 0,
                    "image_url": self.query.teams[
                        next(
                            (
                                i
                                for i, t in enumerate(self.query.teams)
                                if t["name"] == team
                            ),
                            None,
                        )
                    ]["team_logos"]["team_logo"]["url"],
                    "main_text": team,
                    "sub_text": "",
                    "stat": 0,
                }
            )
            i += 1
            for j in range(len(draft)):
                ranked_drafts_list[len(ranked_drafts_list) - 1]["stat"] += round(
                    float(stats[j]["player_points"][0]["total"]), 1
                )
        ranked_drafts_list = sorted(
            ranked_drafts_list, key=lambda item: list(item.items())[4][1], reverse=True
        )
        rank = 1
        for draft in ranked_drafts_list:
            draft["rank"] = rank
            draft["stat"] = round(draft["stat"], 1)
            rank += 1

        return {"id": "best_worst_drafts", "data": ranked_drafts_list}

    async def get_closest_matchups(self):
        completed_matchups_data = await self.query.get_matchup_data()
        top_x = 10
        matchups_data_by_point_diff_ascen = sorted(
            completed_matchups_data, key=lambda x: abs(x["point_diff"])
        )
        closest_matchups_list = [
            {
                "rank": i + 1,
                "image_url": matchups_data_by_point_diff_ascen[i]["team1_url"],
                "main_text": (
                    f"{matchups_data_by_point_diff_ascen[i]['team1_name']} ({matchups_data_by_point_diff_ascen[i]['team1_points']}) def. {matchups_data_by_point_diff_ascen[i]['team2_name']} ({matchups_data_by_point_diff_ascen[i]['team2_points']})"
                    if not matchups_data_by_point_diff_ascen[i]["is_tied"]
                    else f"{matchups_data_by_point_diff_ascen[i]['team1_name']} and {matchups_data_by_point_diff_ascen[i]['team2_name']} tied"
                ),
                "sub_text": (
                    "playoffs"
                    if matchups_data_by_point_diff_ascen[i]["is_playoffs"]
                    else ""
                ),
                "stat": matchups_data_by_point_diff_ascen[i]["point_diff"],
            }
            for i in range(top_x)
        ]
        return {"id": "closest_matchups", "data": closest_matchups_list}

    async def get_biggest_blowout_matchups(self):
        completed_matchups_data = await self.query.get_matchup_data()
        top_x = 10
        matchups_data_by_point_diff_descen = sorted(
            completed_matchups_data, key=lambda x: abs(x["point_diff"]), reverse=True
        )
        biggest_blowouts_list = [
            {
                "rank": i + 1,
                "image_url": matchups_data_by_point_diff_descen[i]["team1_url"],
                "main_text": f"{matchups_data_by_point_diff_descen[i]['team1_name']} ({matchups_data_by_point_diff_descen[i]['team1_points']}) def. {matchups_data_by_point_diff_descen[i]['team2_name']} ({matchups_data_by_point_diff_descen[i]['team2_points']})",
                "sub_text": (
                    "playoffs"
                    if matchups_data_by_point_diff_descen[i]["is_playoffs"]
                    else ""
                ),
                "stat": matchups_data_by_point_diff_descen[i]["point_diff"],
            }
            for i in range(top_x)
        ]
        return {"id": "biggest_blowouts", "data": biggest_blowouts_list}

    async def get_rivalry_dominance(self):
        completed_matchups_data = await self.query.get_matchup_data()
        matchup_dict = defaultdict(list)
        for matchup in completed_matchups_data:
            key = frozenset([matchup["team1_key"], matchup["team2_key"]])
            matchup_dict[key].append(matchup)
        matchup_dict = dict(matchup_dict)
        season_matchup_stats = {}
        for matchup_combination in matchup_dict.keys():
            team1_total_points = 0
            team2_total_points = 0
            for matchup in matchup_dict[matchup_combination]:
                if (
                    matchup_combination in season_matchup_stats.keys()
                    and matchup["team1_key"]
                    == season_matchup_stats[matchup_combination]["team2_key"]
                ):
                    team1_total_points += matchup["team2_points"]
                    team2_total_points += matchup["team1_points"]
                    season_matchup_stats[matchup_combination]["team1_total_points"] = (
                        round(team1_total_points, 2)
                    )
                    season_matchup_stats[matchup_combination]["team2_total_points"] = (
                        round(team2_total_points, 2)
                    )
                    season_matchup_stats[matchup_combination] = {
                        "team1_key": matchup["team2_key"],
                        "team1_name": matchup["team2_name"],
                        "team1_total_points": round(team1_total_points, 2),
                        "team1_url": matchup["team2_url"],
                        "team2_key": matchup["team1_key"],
                        "team2_name": matchup["team1_name"],
                        "team2_total_points": round(team2_total_points, 2),
                        "team2_url": matchup["team1_url"],
                        "incl_playoffs": matchup["is_playoffs"],
                        "incl_consolation": matchup["is_consolation"],
                    }
                else:
                    team1_total_points += matchup["team1_points"]
                    team2_total_points += matchup["team2_points"]
                    season_matchup_stats[matchup_combination] = {
                        "team1_key": matchup["team1_key"],
                        "team1_name": matchup["team1_name"],
                        "team1_total_points": round(team1_total_points, 2),
                        "team1_url": matchup["team1_url"],
                        "team2_key": matchup["team2_key"],
                        "team2_name": matchup["team2_name"],
                        "team2_total_points": round(team2_total_points, 2),
                        "team2_url": matchup["team2_url"],
                        "incl_playoffs": matchup["is_playoffs"],
                        "incl_consolation": matchup["is_consolation"],
                    }
                season_matchup_stats[matchup_combination]["total_point_diff"] = round(
                    season_matchup_stats[matchup_combination]["team1_total_points"]
                    - season_matchup_stats[matchup_combination]["team2_total_points"],
                    2,
                )
            if season_matchup_stats[matchup_combination]["total_point_diff"] < 0:
                team1_key_temp = season_matchup_stats[matchup_combination]["team1_key"]
                team1_name_temp = season_matchup_stats[matchup_combination][
                    "team1_name"
                ]
                team1_total_points_temp = season_matchup_stats[matchup_combination][
                    "team1_total_points"
                ]
                team1_url_temp = season_matchup_stats[matchup_combination]["team1_url"]
                season_matchup_stats[matchup_combination]["team1_key"] = (
                    season_matchup_stats[matchup_combination]["team2_key"]
                )
                season_matchup_stats[matchup_combination]["team1_name"] = (
                    season_matchup_stats[matchup_combination]["team2_name"]
                )
                season_matchup_stats[matchup_combination]["team1_total_points"] = (
                    season_matchup_stats[matchup_combination]["team2_total_points"]
                )
                season_matchup_stats[matchup_combination]["team1_url"] = (
                    season_matchup_stats[matchup_combination]["team2_url"]
                )
                season_matchup_stats[matchup_combination]["team2_key"] = team1_key_temp
                season_matchup_stats[matchup_combination][
                    "team2_name"
                ] = team1_name_temp
                season_matchup_stats[matchup_combination][
                    "team2_total_points"
                ] = team1_total_points_temp
                season_matchup_stats[matchup_combination]["team2_url"] = team1_url_temp
                season_matchup_stats[matchup_combination]["total_point_diff"] = abs(
                    season_matchup_stats[matchup_combination]["total_point_diff"]
                )
        season_matchup_stats_descen = sorted(
            season_matchup_stats.items(),
            key=lambda matchup: abs(matchup[1]["total_point_diff"]),
            reverse=True,
        )
        top_x = 10
        season_matchup_list = [
            {
                "rank": i + 1,
                "image_url": season_matchup_stats_descen[i][1]["team1_url"],
                "main_text": f"{season_matchup_stats_descen[i][1]['team1_name']} ({season_matchup_stats_descen[i][1]['team1_total_points']}) def. {season_matchup_stats_descen[i][1]['team2_name']} ({season_matchup_stats_descen[i][1]['team2_total_points']})",
                "sub_text": (
                    "playoffs"
                    if season_matchup_stats_descen[i][1]["incl_playoffs"]
                    else ""
                ),
                "stat": season_matchup_stats_descen[i][1]["total_point_diff"],
            }
            for i in range(top_x)
        ]
        return {"id": "rivalry_dominance", "data": season_matchup_list}
