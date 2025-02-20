import os
from dotenv import load_dotenv

load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST") 
WEBHOOK_PATH = "/webhook/{token}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"