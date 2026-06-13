# AI Customer Support Agent — E-Commerce Refunds

A full-stack AI agent that handles e-commerce refund requests using policy-aware tool calling, live admin reasoning logs over WebSocket, and browser voice input/output.

## Stack

| Layer | Technology |
|-------|------------|
| Backend | Python, FastAPI, LangGraph, SQLite |
| LLM | Groq API (`llama-3.3-70b-versatile`) — free tier at [console.groq.com](https://console.groq.com) |
| Frontend | Plain HTML, CSS, vanilla JavaScript (no build step) |
| Voice | Browser Web Speech API (SpeechRecognition + SpeechSynthesis) |
| Real-time | WebSocket (`/ws/logs`) for live agent reasoning |

## Project Structure

```
backend/
  main.py              FastAPI app + static file serving
  db.py                SQLite schema
  ws_manager.py        WebSocket broadcast manager
  agent/
    tools.py           Refund lookup & eligibility tools
    graph.py           LangGraph agent loop
  data/
    seed.py            Mock data seeder
    refund_policy.md   Strict refund policy
frontend/
  index.html           Customer chat UI
  admin.html           Admin reasoning dashboard
  style.css            Shared styles
  app.js               Chat + voice logic
  admin.js             WebSocket log viewer
```

## Setup

### 1. Clone and install dependencies

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Get a free Groq API key

1. Sign up at [console.groq.com](https://console.groq.com)
2. Create an API key
3. Copy `.env.example` to `.env` and set your key:

```bash
cp ../.env.example ../.env
# Edit .env and set GROQ_API_KEY=gsk_...
```

### 3. Seed the database

```bash
python data/seed.py
```

This creates 15 mock customers, 20 orders (mix of eligible/ineligible scenarios), and 1 prior refund for abuse detection testing.

### 4. Run the server

```bash
uvicorn main:app --reload --port 8000
```

The frontend is served by FastAPI — no separate frontend server needed.

- **Customer chat:** [http://localhost:8000](http://localhost:8000)
- **Admin dashboard:** [http://localhost:8000/admin.html](http://localhost:8000/admin.html)

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/customers` | List all mock customers |
| `POST` | `/chat` | Send a refund request `{customer_id, message}` |
| `WS` | `/ws/logs` | Stream live reasoning events |

### Test with curl

```bash
# List customers
curl http://localhost:8000/customers

# Send a refund request
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "C003", "message": "I want a refund for order O005, the sneakers dont fit. Change of mind."}'
```

## Refund Policy (Summary)

- Refunds within **30 days of delivery** only (unless defective)
- **Final Sale** items non-refundable except if defective
- **Defective items:** full refund + free return shipping, up to 90 days
- **Change of mind:** 15% restocking fee, item must be unused/unopened
- **Digital goods:** non-refundable once downloaded/delivered
- Order must be **delivered**
- Max **1 refund per customer per 30-day window**

See `backend/data/refund_policy.md` for the full policy.

## Policy Enforcement (Deterministic Guardrails)

The LLM reasons about and explains every decision, but the **hard abuse rules are
enforced in code**, not left to the model. `process_refund` is the authoritative
policy engine: if an `approved` decision would refund the same order twice, or grant
a customer a second approved refund inside the 30-day window, the approval is **blocked
and recorded as a denial** regardless of what the model decided. This guarantees the
agent "holds the line" consistently on every retry instead of occasionally being talked
into an approval. The authoritative decision returned to the UI is read from the
`process_refund` result, not parsed from free text.

## Mock Data Highlights

| Scenario | Example |
|----------|---------|
| Recent eligible order | O001 — headphones, 5 days ago |
| Outside 30-day window | O002 — dress, 45 days ago |
| Final sale | O005, O007, O011 |
| Defective items | O004, O010 |
| Not delivered | O008 (shipped), O015 (processing) |
| Prior refund (abuse flag) | C001 — refund 10 days ago |
| Digital goods | O003, O014 |

## Voice Features

- **Microphone button** on the chat page uses `SpeechRecognition` to fill the input and auto-send
- **Speaker toggle** uses `SpeechSynthesis` to read agent responses aloud
- Works in Chrome/Edge (Web Speech API); Safari/Firefox support varies

## Admin Dashboard

Open `/admin.html` to watch live agent reasoning:

- **THOUGHT** — agent internal reasoning (blue)
- **TOOL CALL** — tool invocation with inputs (yellow)
- **TOOL RESULT** — tool output (green)
- **DECISION** — approve/deny with green/red background

Stats update live: total requests, approved, denied, average tools per request.
