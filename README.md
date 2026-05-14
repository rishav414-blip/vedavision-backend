# VedaVision Backend

Sidereal natal chart calculations using Swiss Ephemeris (pyswisseph).
Returns JSON matching the VedaVision SAMPLE_CHART data contract.

---

## Install

```bash
pip install -r requirements.txt
```

---

## Run locally

```bash
uvicorn main:app --reload --port 8000
```

Interactive docs available at http://localhost:8000/docs

---

## API

### POST http://localhost:8000/chart

**Sample request:**

```json
{
  "name": "Arjuna",
  "dob": "1990-04-14",
  "tob": "06:30",
  "pob": "New Delhi, India",
  "ayanamsa": "Lahiri"
}
```

Or pass coordinates directly (skips geocoding):

```json
{
  "name": "Arjuna",
  "dob": "1990-04-14",
  "tob": "06:30",
  "lat": 28.6139,
  "lon": 77.2090,
  "tz": "Asia/Kolkata"
}
```

### GET http://localhost:8000/health

Returns `{"status":"ok","version":"1.0"}`.

---

## Deploy to Railway (free tier)

1. Push this `backend/` folder to a GitHub repo.
2. Go to [railway.app](https://railway.app) and create a new project from that repo.
3. Railway auto-detects Python. Set the **Start Command** in project settings:

```
uvicorn main:app --host 0.0.0.0 --port $PORT
```

4. Deploy. Railway provides a public HTTPS URL.

---

## Environment variable

| Variable | Default | Purpose |
|---|---|---|
| `SWE_EPHE_PATH` | *(empty)* | Path to Swiss Ephemeris data files. pyswisseph ships with built-in data for 1800–2400 CE; only needed for extended date ranges. |
