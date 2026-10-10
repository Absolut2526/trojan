import os
from typing import List
from dotenv import load_dotenv

load_dotenv()

class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    # List of allowed Telegram User IDs and Group/Supergroup Chat IDs (e.g. -1002673536147)
    ALLOWED_CHAT_IDS: List[int] = [
        int(x.strip()) for x in os.getenv("ALLOWED_CHAT_IDS", "").split(",") if x.strip().lstrip("-").isdigit()
    ]
    ADMIN_IDS: List[int] = [
        int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().lstrip("-").isdigit()
    ]
    # Secret key to authenticate client PCs connecting to WebSocket
    CLIENT_SECRET: str = os.getenv("CLIENT_SECRET", "pc_club_secret_key_123")
    
    # Web Dashboard credentials
    DASHBOARD_PASSWORD: str = os.getenv("DASHBOARD_PASSWORD", "admin123")
    
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

config = Config()
