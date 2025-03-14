from typing import Annotated
from fastapi import FastAPI, Header
from fastapi.responses import StreamingResponse
from query import Query
import asyncio
import aiohttp
import firebase_admin
from firebase_admin import credentials, firestore
import json

from firebase import initialize_firebase

app = FastAPI(debug=True)


@app.get("/wrapped/{league_key}")
async def get_fantasy_wrapped(
    league_key: str,
    authorization: Annotated[str | None, Header()] = None,
    x_refresh_token: Annotated[str | None, Header()] = None,
):
    if not authorization or not authorization.startswith("Bearer "):
        return jsonify({"error": "Missing or invalid access token"}), 401
    db = initialize_firebase()
    doc_ref = db.collection("wrapped").document(league_key)
    doc = doc_ref.get()
    if doc.exists:
        resp = doc.to_dict()["metrics"]
        return StreamingResponse(
            [json_resp for json_resp in resp], media_type="text/event-stream"
        )
    access_token = authorization.split(" ")[1]
    token = {"access_token": access_token, "refresh_token": x_refresh_token}
    query = await Query.create(league_key, token, doc_ref)
    return StreamingResponse(query.get_metrics(), media_type="text/event-stream")
