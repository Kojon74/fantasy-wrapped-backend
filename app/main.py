from typing import Annotated
from fastapi import FastAPI, Header
from fastapi.responses import StreamingResponse
import json
import asyncio

from query import Query
from firebase import initialize_firebase

app = FastAPI()


async def event_stream(resp):
    await asyncio.sleep(1)
    for json_resp in resp:
        yield f"{json_resp}\n"  # StreamingResponse already prefixes data with "data: "
        await asyncio.sleep(1)


@app.get("/wrapped/{league_key}")
async def get_fantasy_wrapped(
    league_key: str,
    authorization: Annotated[str | None, Header()] = None,
    x_refresh_token: Annotated[str | None, Header()] = None,
):
    db = initialize_firebase()
    doc_ref = db.collection("wrapped").document(league_key)
    doc = doc_ref.get()
    if doc.exists:
        resp = doc.to_dict()["metrics"]
        return StreamingResponse(event_stream(resp), media_type="text/event-stream")
    print("Not in Firebase Firestore cache")
    if not authorization or not authorization.startswith("Bearer "):
        return json.dumps({"error": "Missing or invalid access token"}), 401
    access_token = authorization.split(" ")[1]
    token = {"access_token": access_token, "refresh_token": x_refresh_token}

    # Send an initial response while Query is being initialized
    async def delayed_stream():
        yield "Test\n"
        query = await Query.create(league_key, token, doc_ref)
        async for metric in query.get_metrics():
            yield f"{metric}\n"

    return StreamingResponse(delayed_stream(), media_type="text/event-stream")
