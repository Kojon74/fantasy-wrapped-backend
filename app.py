from flask import Flask, request
from query import Query

app = Flask(__name__)

@app.route("/api/get-fantasy-data", methods=["GET"])
def get_fantasy_data():
    auth_header = request.headers.get("Authorization")
    refresh_token = request.headers.get("X-Refresh-Token")
    league_key = request.args.get("league_key")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"error": "Missing or invalid access token"}), 401
    access_token = auth_header.split(" ")[1]
    token = {"access_token": access_token, "refresh_token": refresh_token}
    query = Query(token, league_key)
    teams, standings = query.get_teams()
    alternative_reality_matrix, team_order = query.get_alternative_realities()
    draft_busts, draft_steals = query.get_draft_busts_steals()
    metrics = [
        {
            "title": '"Official" Results',
            "description": "Sure, these are the official results. But were they really the best team? The luckiest? The biggest flop? Keep scrolling to uncover the real winners and losers of the season.",
            "stats": standings
        },
        {
            "title": 'Alternative Realities',
            "description": "What if your team had a different schedule? This matrix reimagines the season by swapping team schedules, showing how records would have changed in an alternate universe. Did bad luck hold you back, or were you truly dominant no matter the matchups?",
            "stats": {"alternative_reality_matrix": alternative_reality_matrix, "team_order": team_order}
        },
        {
            "title": 'Draft Steal',
            "description": "Some picks turn out to be absolute gems! This metric highlights the player who delivered the biggest return on investment, massively outperforming their draft position. Whether it was a late-round sleeper who dominated or a mid-round pick who played like a first-rounder, this is your league's ultimate steal of the draft.",
            "stats": draft_steals
        },
        {
            "title": 'Draft Bust',
            "description": "Not all picks live up to the hype. This metric identifies the player who fell the hardest from expectations, drastically underperforming their draft position. Whether it was due to injuries, poor form, or just bad luck, this was the pick that stung the most for fantasy managers.",
            "stats": draft_busts
        },
    ]
    response = {
        "teams": teams,
        "metrics": metrics,
    }
    return response