import os
from dotenv import load_dotenv

load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")
ADMIN_ID = [int(admin_id.strip()) for admin_id in os.getenv("ADMIN_ID", "").split(',')]
DATABASE_URL = os.getenv("DATABASE_URL")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST") 
WEBHOOK_PATH = "/webhook/{token}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

STATIC_ROOT = os.path.join(BASE_DIR, "static")

STATIC_URL = "/static"