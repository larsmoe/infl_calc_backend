"""Generate a study.json file from a folder structure of pre-selected images:

images
|- class_label_1
|  |- image_1.png
|  |- image_2.png
|  ...
|
|- class_label_2
|  |- image_1.png
|  ...
|
controls #To-DO: haben die eine Erklärung?
|- control_image_1.png
|  ...

"""
import pathlib
import time
import os
import couchdb
import requests
from pydantic import BaseSettings
import io
import hashlib
import cv2
import numpy as np
import base64
import json
from backend.prerecorded import get_hash

#Hier Credentials hart reincoden
class Settings(BaseSettings):
    db_user: str = "GTC-admin"
    db_password: str = "7epV5XDEunE6GuBkssXX"
    db_host: str = "localhost"
    db_port: int = 8002

settings = Settings()


couch = couchdb.Server(f"http://{settings.db_user}:{settings.db_password}"  # noqa
                       f"@{settings.db_host}:{settings.db_port}")

database = couch["xaidemo"]


def find_by_id(db, id_type: str, tracked_id: str):
    """Find a tracked record based on the prediction_id/explanation_id."""
    print(f"Searching for {id_type}={tracked_id}")
    mango_query = {
        "selector": {
            f"data.tracked.data.response.decoded.{id_type}": tracked_id
        },
        "use_index": f"_design/{id_type}"
    }
    for doc in db.find(mango_query):
        return doc
    print("Did not find a doc!?")

def make_hash(image_file) -> str:
    """Get the hash of an image file."""
    # https://stackoverflow.com/questions/3431825/generating-an-md5-checksum-of-a-file
    file_object = io.BytesIO(image_file)

    file_hash = hashlib.sha1()
    while chunk := file_object.read(8192):
        file_hash.update(chunk)
    return file_hash.hexdigest()


def process_image(path: pathlib.Path, class_label: str):
    print(f"Process {path} with label {class_label}")

    success = False

    while not success:

        with open(path, "rb") as image_file:
            image_file.seek(0)

            encoded_image_string = base64.b64encode(image_file.read())
            encoded_bytes = bytes("data:image/png;base64,",
                                    encoding="utf-8") + encoded_image_string
            files = {'file': encoded_bytes}
            image_hash = make_hash(files["file"])

            print("Predict...")
            response_predict = requests.post("https://gtc.xaidemo.de/api/country/predict", files=files)
            print(response_predict.json())
            print("Explain...")
            response_explain = requests.post("https://gtc.xaidemo.de/api/country/explain", files=files)
            print(response_explain.json()["explanation_id"])
  
        # wait for the tracked data to be recorded ...

        print("Wait for backend to finish recording...")

        time.sleep(10)

        print("Fetch recorded data...")

        record_predict = find_by_id(database, "prediction_id", response_predict.json()["prediction_id"])
   
        # ... and get the record where explanation_id matches
        record_explain = find_by_id(database, "explanation_id", response_explain.json()["explanation_id"])
    
        success = record_predict is not None and record_explain is not None

    image_data = {
        "image": path,
        "label": class_label,
        "predict": record_predict["_id"],
        "explain": record_explain["_id"]
    }

    return image_hash, image_data

DATADIR ="./images/"
CATEGORIES = ["tel_aviv", "jerusalem", "berlin", "hamburg"]
#,"WestJerusalem" ,"Berlin", "Hamburg"
if __name__ == "__main__":
    experiment = {"images":{}, "controls":{}
    }
    for control in os.listdir("./images/controls/"):
            image_hash, image_data = process_image(os.path.join("./images/controls/", control), "Berlin")
            experiment["controls"][image_hash] = image_data   
             
    for category in CATEGORIES:
        path = os.path.join(DATADIR, category)
         # path to the differen images
        for img in os.listdir(path):
            image_hash, image_data = process_image(os.path.join(path, img), category)
            experiment["images"][image_hash] = image_data

    with open("study.json", "wt+") as f:
        json.dump(experiment, f, indent=4)
