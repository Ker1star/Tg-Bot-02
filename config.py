import os
from dotenv import load_dotenv

load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")
ADMIN_ID = [int(admin_id.strip()) for admin_id in os.getenv("ADMIN_ID", "").split(',')]
DATABASE_URL = os.getenv("DATABASE_URL")
PROXY_URL = os.getenv("PROXY_URL")  # пример: http://user:pass@host:port
WAITER_CHAT_ID = -1002246175197