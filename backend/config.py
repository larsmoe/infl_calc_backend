from pydantic import BaseSettings


class Settings(BaseSettings):
    service_name: str = "study-backend-service"
    root_path: str = "/api/study"
    path_prefix: str = ""
    # Experiment database
    db_name: str = "study"
    db_user: str
    db_password: str
    db_host: str = "couchdb"
    db_port: int = 5984
    # Data collector
    collector_url: str = "http://collector:8000"


settings = Settings()
