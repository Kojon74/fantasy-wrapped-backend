from typing import Annotated
from fastapi import FastAPI, Header
from fastapi.responses import StreamingResponse
from query import Query
import asyncio
import aiohttp

app = FastAPI(debug=True)

@app.get("/wrapped/{league_key}")
async def get_fantasy_wrapped(
    league_key: str, 
    authorization: Annotated[str | None, Header()] = None, 
    x_refresh_token: Annotated[str | None, Header()] = None
):
    if not authorization or not authorization.startswith("Bearer "):
        return jsonify({"error": "Missing or invalid access token"}), 401
    access_token = authorization.split(" ")[1]
    token = {"access_token": access_token, "refresh_token": x_refresh_token}
    query = await Query.create(league_key, token)
    return StreamingResponse(query.get_metrics(), media_type="text/event-stream")