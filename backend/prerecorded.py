import base64
import hashlib
import io
import json
import pathlib
from typing import Dict, Any

from cache import AsyncLRU
from fastapi import UploadFile
from pydantic import BaseModel
from xaidemo.http_client import AioHttpClientSession

from .config import settings

with open(pathlib.Path(__file__).parent / "study.json", "rt") as f:
    DATA = json.load(f)

IMAGE_BASE_DIR = pathlib.Path(__file__).parent

ALL_IMAGES = {**DATA["images"], **DATA["controls"]}

IMAGE_HASHES = list({**DATA["images"]}.keys())
CONTROL_IMAGE_HASHES = list({**DATA["controls"]}.keys())


class Streetview(BaseModel):
    image: bytes
    class_label: str


@AsyncLRU(maxsize=128)
async def get_streetview(file_hash: str) -> Streetview:
    """Load an image from disk and return it in a `Streetview` response."""
    with open(IMAGE_BASE_DIR / ALL_IMAGES[file_hash]["image"], "rb") as image_file:
        encoded_image_string = base64.b64encode(image_file.read())

    encoded_bytes = bytes("data:image/png;base64,",
                          encoding="utf-8") + encoded_image_string

    return Streetview(image=encoded_bytes, class_label=ALL_IMAGES[file_hash]["label"])


def get_hash(file: UploadFile) -> str:
    """Get the hash of an image file."""
    # https://stackoverflow.com/questions/3431825/generating-an-md5-checksum-of-a-file
    file_object = io.BytesIO(file)
    file_hash = hashlib.sha1()
    while chunk := file_object.read(8192):
        file_hash.update(chunk)
    return file_hash.hexdigest()


async def get_response(route: str, file_hash: str):
    """Get the pre-recorded response of the original GtC-backend."""
    identifier = ALL_IMAGES[file_hash][route]
    record = await get_record(identifier)
    return record.data["tracked"]["data"]["response"]["decoded"]


class Record(BaseModel):
    id: str
    timestamp: float
    service: str
    data: Dict[str, Dict[str, Any]]

    class Config:
        extra = "ignore"


@AsyncLRU(maxsize=128)
async def get_record(identifier: str) -> Record:
    """Pull a pre-recorded response from the experiment tracking data-collectors service."""
    async with AioHttpClientSession() as session:
        async with session.get(settings.collector_url + "/get/" + identifier) as response:
            json_body = await response.json()

    return Record(**json_body)
