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
    metrics = [
        {
            "title": '"Official" Results',
            "description": "Sure, these are the official results. But were they really the best team? The luckiest? The biggest flop? Keep scrolling to uncover the real winners and losers of the season.",
            "stats": standings
        }
    ]
    response = {
        "teams": teams,
        "metrics": metrics,
    }
    return response