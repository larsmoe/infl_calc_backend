import csv
import os
import couchdb
from pydantic import BaseSettings
from datetime import datetime

class Settings(BaseSettings):
    db_user: str = "GTC-admin"
    db_password: str = "7epV5XDEunE6GuBkssXX"
    db_host: str = "localhost"
    db_port: int = 8001


settings = Settings()


couch = couchdb.Server(f"http://{settings.db_user}:{settings.db_password}"  # noqa
                       f"@{settings.db_host}:{settings.db_port}")

database = couch["study"]


def get_player_score(db, starting_point):
    mango_query = {
        "selector": {
            "player_id":"fa8cab1e-18ea-4c8c-b8c0-6a7feac83bb5"
        },
        "fields": [
            "player_id",
            "created_at",
            "ai_score",
            "player_score",
            "rounds",
            "prediction_city",
            "user_city_answer",
            "label_city"
        ],
        "sort": [
            {
                "player_score": "desc"
            },
            {
                "created_at": "desc"
            }
        ],
        "limit": 100
    }

    return db.find(mango_query)


if __name__ == "__main__":
    starting_point = 1648189447

    users = get_player_score(database, starting_point)

    f = open('users.csv', 'w')

    # create the csv writer
    writer = csv.writer(f)

    # write a row to the csv file
    writer.writerow(["player_id", "created_at",
                       "ai_score", "player_score", "rounds","prediction_city","user_city_answer","label_city"])

    for user in users:
        writer.writerow([user["player_id"], datetime.utcfromtimestamp(user["created_at"]).strftime('%Y-%m-%d %H:%M:%S'),
                        user["ai_score"], user["player_score"], user["rounds"],user["prediction_city"],user["user_city_answer"],user["label_city"]])
    # close the file
    f.close()
