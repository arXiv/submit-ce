from arxiv.config import Settings as ArxivBaseSettings

DEV_SQLITE_FILE="legacy.db"

class Settings(ArxivBaseSettings):
    pass

settings = Settings()