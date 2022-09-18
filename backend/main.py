import asyncio
import time
import uuid
from typing import List

import couchdb
from fastapi import FastAPI, UploadFile, File, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from xaidemo import tracing, http_client

from .config import settings
from .prerecorded import IMAGE_HASHES, CONTROL_IMAGE_HASHES, get_response, get_hash, get_streetview, Record
from .repository import repo

CONTROL_ROUND = 15

tracing.set_up()

app = FastAPI(root_path=settings.root_path)
http_client.set_up(app)

origins = [
    "https://study.xaidemo.de"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter()

IN_MEMORY_SCORE_TRACKER = {}


class ScoreRequest(BaseModel):
    ai_score: int
    player_score: int
    rounds: int
    prediction_city: str = ""
    label_city: str = ""
    user_city_answer: str = ""


class ScoreRecord(BaseModel):
    player_id: str
    created_at: float
    ai_score: int
    player_score: int
    rounds: int
    prediction_city: str = ""
    label_city: str = ""
    user_city_answer: str = ""


@tracing.traced
def record_score(player: str, score_request: ScoreRequest):
    record = ScoreRecord(player_id=player,
                         ai_score=score_request.ai_score,
                         player_score=score_request.player_score,
                         created_at=time.time(),
                         rounds=score_request.rounds,
                         prediction_city=score_request.prediction_city,
                         user_city_answer=score_request.user_city_answer,
                         label_city=score_request.label_city)

    # Erstmal im Speicher aktualisieren...
    IN_MEMORY_SCORE_TRACKER[player] = record.dict()

    # ...und dann in der Datenbank
    repo[str(uuid.uuid4())] = record.dict()
    return record


@api.get("/find/{id_type}/{tracked_id}")
def get_document_by_tracked_id(id_type: str, tracked_id: str) -> Record:
    return Record(**repo.find_by_id(id_type, tracked_id))


class ExperimentRecord(BaseModel):
    player_id: str
    created_at: float
    images: List[str] = []


@api.post("/{player}/streetview")
async def streetview(player: str, score_request: ScoreRequest):
    try:
        exp_record = repo[player]
    except couchdb.http.ResourceNotFound:
        exp_record = ExperimentRecord(player_id=player, created_at=time.time()).dict()

    if score_request.rounds == CONTROL_ROUND:
        new_image_hash = CONTROL_IMAGE_HASHES[0]
    else:
        new_image_hash = IMAGE_HASHES[(score_request.rounds - 1) - (score_request.rounds // CONTROL_ROUND)]

    exp_record["images"].append(new_image_hash)

    record_score(player, score_request)
    repo[player] = exp_record

    return await get_streetview(new_image_hash)


class RequestRecord(BaseModel):
    player_id: str
    created_at: float
    route: str
    image_hash: str


@api.post("/{player}/predict")
async def predict(player: str, file: UploadFile = File(...)):
    current_image = get_hash(file.file.read())
    record = RequestRecord(player_id=player, route="predict", created_at=time.time(), image_hash=current_image)
    repo[str(uuid.uuid4())] = record.dict()

    await asyncio.sleep(1)  # Tunen wie es sich im Frontend verhält

    return await get_response("predict", current_image)


@api.post("/{player}/explain")
async def explain(player: str, file: UploadFile = File(...)):
    current_image = get_hash(file.file.read())
    record = RequestRecord(player_id=player, route="explain", created_at=time.time(), image_hash=current_image)
    repo[str(uuid.uuid4())] = record.dict()

    await asyncio.sleep(1)  # Tunen wie es sich im Frontend verhält

    return await get_response("explain", current_image)


@api.post("/{player}/score")
def score(player: str, score_request: ScoreRequest):
    return record_score(player, score_request)


class FinishedResponse(BaseModel):
    has_finished: bool


@api.get("/{player}/has_completed/{total_rounds}")
def has_finished(player: str, total_rounds: int) -> FinishedResponse:
    """Has the player completed the game?"""
    try:
        if IN_MEMORY_SCORE_TRACKER[player]["rounds"] >= total_rounds:
            return FinishedResponse(has_finished=True)
        else:
            return FinishedResponse(has_finished=False)
    except KeyError:
        # kein Eintrag für diese Player-ID in unserem In-Memory-Score-Tracker
        mango_query = (
            {
                "selector": {
                    f"player_id": player,
                    "ai_score": {"$exists": True},  # wir suchen nur ScoreRecords
                },
                "fields": [
                    "player_id",
                    "created_at",
                    "ai_score",
                    "player_score",
                    "rounds",
                    "prediction_city",
                    "label_city",
                    "user_city_answer"
                ],
                "sort": [
                    {
                        "created_at": "desc"
                    }
                ],
                "use_index": "_design/player_id"
            })

        for record in repo.database.find(mango_query):
            # schreibe jüngsten Eintrag in den Speicher ...
            print(record)
            IN_MEMORY_SCORE_TRACKER[player] = ScoreRecord(**record).dict()
            # ... und prüfe erneut
            return has_finished(player)
        else:
            # kein Record in der Datenbank für diese Player-ID
            return FinishedResponse(has_finished=False)


@api.get("/{player}/final_score")
def final_score(player: str) -> ScoreRecord:
    """Return the final score the player achieved"""
    mango_query = (
        {
            "selector": {
                f"player_id": player,
                "ai_score": {"$exists": True},  # wir suchen nur ScoreRecords
                "rounds": {"$in": [4, 12, 17]}  # die Spiele enden bei 4, 12 und 17 gespielten Runden
            },
            "fields": [
                "player_id",
                "created_at",
                "ai_score",
                "player_score",
                "rounds",
                "prediction_city",
                "label_city",
                "user_city_answer"
            ],
            "sort": [
                {
                    "created_at": "desc"
                }
            ],
            "use_index": "_design/player_id"
        })

    total_ai_score = 0
    total_player_score = 0
    created_at = 0
    prediction_city = ""
    label_city = ""
    user_city_answer = ""

    recorded_rounds = []

    for doc in repo.database.find(mango_query=mango_query):
        if doc["rounds"] in recorded_rounds:
            continue  # wir haben schon einen jüngeren Eintrag für diese Runde verarbeitet
        else:
            total_ai_score += doc["ai_score"]
            total_player_score += doc["player_score"]
            created_at = doc["created_at"]
            recorded_rounds.append(doc["rounds"])
            label_city = doc["label_city"]
            prediction_city = doc["prediction_city"]
            user_city_answer = doc["user_city_answer"]


    return ScoreRecord(player_id=player,
                       created_at=created_at,
                       ai_score=total_ai_score,
                       player_score=total_player_score,
                       rounds=max(recorded_rounds),
                       prediction_city=prediction_city,
                       user_city_answer=user_city_answer,
                       label_city=label_city
                       )



# noinspection PyUnusedLocal
@api.get("/{player}/msg")
def msg(player: str):
    return {
        "data": "Your guess: Where has this Google Streetview picture been taken?"
    }


@api.get("/{player}/attentioncheck")
def attention_check(player: str):
    """Has the player answered the attention check correctly?"""
    mango_query = (
        {
            "selector": {
                "player_id": player,
                "ai_score": {"$exists": True},  # wir suchen nur ScoreRecords
                "rounds": CONTROL_ROUND
            },
            "fields": [
                "rounds",
                "created_at",
                "player_score"
            ],
            "sort": [
                {
                    "created_at": "desc"
                }
            ],
            "use_index": "_design/player_id"
        })

    docs = list(repo.database.find(mango_query))

    if len(docs) < 2:  # wenn das der Fall ist, kann man den Check nicht durchführen
        answer = False
    else:
        if docs[1]["player_score"] == docs[0]["player_score"]:
            answer = False
        else:
            answer = True

    return {"attention_check": answer}


app.include_router(api, prefix=settings.path_prefix)

tracing.instrument_app(app)
