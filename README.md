# Student Academic History API — Phase 2

FastAPI service with per-student history HTML import, history replacement/removal, course planning, and unified student profiles.

## Run locally

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Visit http://127.0.0.1:8000/docs for interactive API documentation.

## Deploy on Render

Push this folder to a **new GitHub repository**; create a Render **Web Service** using Python runtime with:

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

Submit an `api_url.txt` file containing the resulting service base URL, without a trailing slash.

Note: per-student data is stored in process memory and resets on service restarts. Use **one worker** so in-memory student state is consistent.
