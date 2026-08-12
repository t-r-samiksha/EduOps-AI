from supabase import create_client
from dotenv import load_dotenv
import os

load_dotenv()

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

client = create_client(url, key)

resp = client.auth.sign_in_with_password({
    "email": "test.teacher@eduopsai.test",
    "password": "EduOpsTest!2026"
})

print(resp.session.access_token)