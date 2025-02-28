from typing import Annotated
from fastapi import FastAPI, Header
from query import Query

app = FastAPI(debug=True)

@app.get("/wrapped/{league_key}")
def get_fantasy_wrapped(
    league_key: str, 
    authorization: Annotated[str | None, Header()] = None, 
    x_refresh_token: Annotated[str | None, Header()] = None
):
    if not authorization or not authorization.startswith("Bearer "):
        return jsonify({"error": "Missing or invalid access token"}), 401
    access_token = authorization.split(" ")[1]
    token = {"access_token": access_token, "refresh_token": x_refresh_token}
    query = Query(token, league_key)
    metrics = query.get_metrics()
    response = {
        "metrics": metrics,
    }
    return response