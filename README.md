# ProtectMe AI — Test Team Setup Guide

> **Understand before you sign. Ask before you agree.**

This guide lets the test team run, configure, and test ProtectMe AI end‑to‑end
**without needing extra help**. Follow the sections in order.

> ⚠️ **It is not a lawyer.** ProtectMe AI helps you understand contracts and
> prepare better questions before signing. It does not provide legal advice.

---

## A. Project overview

**What it does:** you upload (or paste) a contract, Gemini analyzes every clause
and returns a structured risk report, and you can review the risks, generate
messages about them, and *talk to a voice agent* for follow‑up questions.

**Main features**
- **Contract upload / paste** — drop a PDF, DOCX, or TXT file, or paste text on the landing page.
- **Risk dashboard** — overall risk, stats, severity filters, and search.
- **All detected risks** — every risk is shown (no "top 3" limit), each card with:
  original clause · in plain terms · why it matters · question to ask · suggested action.
- **Message generator** — pick one or more risks → generate an email or WhatsApp
  message (clarification / negotiation / rejection) you can copy.
- **Call Your Agent** — a voice panel: ask questions out loud or by text and the
  agent answers, explains clauses, recommends, and drafts messages.
- **Journey TTS voice** — Google Cloud "Journey" voice (~300 ms) speaks the answers.
- **Arabic support** — ask in Arabic (or say "explain in Arabic") and the agent answers in Arabic with an Arabic voice; English questions stay English. Discover Arabic voices with `python -m app.utils.list_voices ar`.
- **Debug terminal** — a live log panel (bottom bar) showing what the system is doing.

**Current default mode**
- **Journey TTS mode is primary** (`NEXT_PUBLIC_VOICE_MODE=tts`) — stable, used for the demo.
- **Gemini Live is experimental** (`NEXT_PUBLIC_VOICE_MODE=live`) — **not used by default**. Don't enable it unless explicitly asked.

---

## B. Folder structure

```text
protectme-ai-agent/
├── backend/     # FastAPI REST API + WebSocket voice server (runs on port 8001)
├── frontend/    # Next.js 14 dashboard UI (runs on port 3000)
├── agent/       # Gemini agent logic: orchestrator, tools, prompts, fast paths
├── docs/        # Architecture, API reference, agent workflow, design reference
├── samples/     # Sample contracts for testing/demo
└── README.md    # This guide
```

- **backend/** — the API the frontend talks to. Contract analysis, message
  generation, session state, and the `/ws/voice/` voice WebSocket + Journey TTS.
- **frontend/** — everything you see in the browser (landing, dashboard, panels).
- **agent/** — the Gemini "brain": contract analysis agent, conversation agent,
  intent router, deterministic fast paths, and message/explain tools. The backend
  imports this package.
- **docs/** — deeper reference material (not needed to run the app).
- **samples/** — `samples/sample-contracts/sample-rental-agreement.txt` for quick testing.

---

## C. Prerequisites

Install these first:

| Tool | Version | Notes |
|---|---|---|
| **Python** | 3.11+ | Backend + agent |
| **Node.js** | 18.17+ (or 20+) | Frontend (Next.js 14) |
| **npm** | 9+ | Ships with Node |
| **Git** | any recent | To clone the repo |
| **Google Gemini API key** | — | From https://aistudio.google.com/app/apikey (starts with `AIza…`) |
| **Google Cloud TTS service‑account JSON** | — | For the Journey voice (Cloud Text‑to‑Speech API enabled) |

> If you only have a Gemini key (no Google Cloud TTS), the app still analyzes
> contracts and the voice agent still answers — it falls back to Gemini TTS
> (slower) or text‑only. Journey voice needs the service‑account JSON.

---

## D. Backend setup (step by step)

```bash
cd backend
python -m venv .venv
```

Activate the virtual environment:

```bash
# Windows (PowerShell or cmd):
.venv\Scripts\activate

# macOS / Linux:
source .venv/bin/activate
```

Install **all** dependencies in one command (do **not** install packages one by one):

```bash
pip install -r requirements.txt
```

`requirements.txt` already includes everything needed:
fastapi · uvicorn · pydantic · pydantic‑settings · google‑genai ·
google‑cloud‑texttospeech · PyMuPDF · python‑docx · python‑multipart · python‑dotenv ·
httpx · websockets · pytest · pytest‑asyncio.

Supported contract upload formats: **PDF** (`.pdf`), **Word** (`.docx`), **Text** (`.txt`).

---

## E. Backend environment variables

Copy the example file:

```bash
# Windows:
copy .env.example .env

# macOS / Linux:
cp .env.example .env
```

Then open `backend/.env` and fill in the values. Line by line:

| Variable | What to set | Notes |
|---|---|---|
| `GEMINI_API_KEY` | your Gemini key (`AIza…`) | **Required.** From Google AI Studio. |
| `GEMINI_ANALYSIS_MODEL` | e.g. `gemini-2.5-pro` | Model that analyzes the contract. |
| `GEMINI_CONVERSATION_MODEL` | e.g. `gemini-2.5-flash` | Voice agent / intent routing. |
| `VOICE_FALLBACK_MODEL` | `gemini-2.5-flash-lite` | Fast model for short spoken fallback answers. |
| `GEMINI_LIVE_MODEL` | `gemini-2.5-flash-native-audio-latest` | **Experimental only** (Live mode). |
| `TTS_PROVIDER` | `google_cloud` | `google_cloud` (Journey) or `gemini`. |
| `GOOGLE_APPLICATION_CREDENTIALS` | `.secrets/google-tts-service-account.json` | Path **relative to `backend/`**. |
| `GOOGLE_CLOUD_TTS_VOICE` | `en-US-Journey-D` | Journey warm male voice (English). |
| `GOOGLE_CLOUD_TTS_LANGUAGE` | `en-US` | |
| `GOOGLE_CLOUD_TTS_ARABIC_VOICE` | `ar-XA-Wavenet-B` | Used when the answer is Arabic. Blank → Google picks a default ar-XA voice (logs a warning). |
| `GOOGLE_CLOUD_TTS_ARABIC_LANGUAGE` | `ar-XA` | |
| `TTS_CHUNK_TIMEOUT_SECONDS` | `8` | One slow TTS chunk won't block the whole reply. |
| `BACKEND_CORS_ORIGINS` | `http://localhost:3000` | Comma‑separated allowed frontend origins. |
| `FRONTEND_URL` | `http://localhost:3000` | Legacy single‑origin (still honored). |
| `SESSION_TTL_MINUTES` | `60` | Idle session lifetime (in memory). |

**Where to put the Google Cloud TTS service‑account JSON:**

```text
backend/.secrets/google-tts-service-account.json
```

Then in `.env`:

```env
GOOGLE_APPLICATION_CREDENTIALS=.secrets/google-tts-service-account.json
```

> 🔒 **Do NOT commit `.env` or `.secrets/`.** Both are gitignored. Never paste a
> real key into any tracked file or into chat.

To discover valid model IDs for your key:

```bash
python -m app.utils.model_check
```

---

## F. Start the backend

```bash
uvicorn app.main:app --reload --port 8001
```

Backend runs at **`http://localhost:8001`**.

Health check:

```bash
curl http://localhost:8001/health
# -> {"status":"ok","app":"ProtectMe AI","version":"0.1.0","gemini_configured":true,...}
```

Expected startup log lines (success signs):

```text
Gemini configured — analysis model: … | conversation model: …
Google Cloud TTS credentials configured.
Gemini client warm-up complete.
TTS warm-up OK — NNNN bytes synthesized.
Application startup complete.
Uvicorn running on http://127.0.0.1:8001
```

> The first start can take a while (cold‑start model warm‑up). Wait for
> `Application startup complete.`

---

## G. Frontend setup (step by step)

Open a **second terminal**:

```bash
cd frontend
npm install
```

Create the frontend env file:

```bash
# Windows:
copy .env.example .env.local

# macOS / Linux:
cp .env.example .env.local
```

`frontend/.env.local` should contain:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8001
NEXT_PUBLIC_WS_BASE_URL=ws://localhost:8001
NEXT_PUBLIC_VOICE_MODE=tts
```

- Keep **`NEXT_PUBLIC_VOICE_MODE=tts`** (the stable demo voice).
- Gemini Live is experimental only — `NEXT_PUBLIC_VOICE_MODE=live`. **Do not use
  Live unless you are explicitly asked to test it.**

> ⚠️ Next.js bakes `NEXT_PUBLIC_*` values at startup. **Restart `npm run dev`
> after changing `.env.local`.**

Start the frontend:

```bash
npm run dev
```

Open: **`http://localhost:3000`**

---

## H. How to use the app (test flow)

1. Open the frontend at `http://localhost:3000`.
2. **Upload or paste** a contract (use `samples/sample-contracts/sample-rental-agreement.txt`).
3. Wait for analysis to finish.
4. View the **risk dashboard** (overall risk, stats, filters).
5. Expand and check **every risk card**.
6. Confirm each card shows all of:
   - original clause
   - in plain terms
   - **why it matters** (never empty)
   - question to ask
   - suggested action
7. Click **Generate message** on one risk → a draft appears.
8. **Select multiple risks** (the Select button) → use the action bar to generate one message covering them.
9. Click **Call Your Agent** (action bar) — or **Ask agent** on a specific card.
10. Ask the agent:
    - "What is the largest risk?"
    - "Explain this clause." (after opening from a card)
    - "Should I sign?"
    - "Write me a WhatsApp message." → then "Make it shorter."
    - "Explain the low risk." / "Explain clause 3."
11. Confirm the **voice plays** (caption reveals as it speaks).
12. Confirm a **draft card** appears for message requests.
13. Confirm **Copy** copies the draft.

---

## I. Suggested test cases

| Test | Expected Result | Pass/Fail |
|---|---|---|
| Upload contract | Risk report generated | |
| All risks visible | No top‑3 limitation | |
| Why it matters visible | No empty fields on any card | |
| Generate email | Draft appears | |
| Generate WhatsApp short message | Short, WhatsApp‑style draft (no email subject) | |
| Call Your Agent | Voice starts | |
| "Largest risk" question | Answer uses the risk report | |
| Ask Agent from a risk card | Explains the *selected* clause | |
| Low‑risk question ("explain the low risk") | Explains the low risk(s); never says "none" when low risks exist | |
| Clause number ("explain clause 6") | Maps to `risk_006` (or says not found) | |
| "Make it shorter" | Updates the latest draft (doesn't re‑explain) | |
| Mute voice | Stops audio | |
| New question while speaking | Cancels old audio, starts new answer | |

---

## J. Troubleshooting

### Backend does not start
- Virtual environment not activated (`.venv\Scripts\activate` / `source .venv/bin/activate`).
- Missing `backend/.env` (copy it from `.env.example`).
- Missing / invalid `GEMINI_API_KEY`.
- Missing service‑account JSON, or wrong `GOOGLE_APPLICATION_CREDENTIALS` path.
- Port 8001 already in use → stop the old process, or run on another port.

### TTS (voice) does not work
- `TTS_PROVIDER=google_cloud`.
- `backend/.secrets/google-tts-service-account.json` exists.
- **Cloud Text‑to‑Speech API is enabled** in that Google Cloud project.
- `GOOGLE_APPLICATION_CREDENTIALS` path is correct (relative to `backend/`).
- Backend **restarted** after env changes. Look for `TTS warm-up OK` in the logs.

### Frontend cannot connect to backend
- Backend is running on **port 8001**.
- `frontend/.env.local` has `NEXT_PUBLIC_API_BASE_URL=http://localhost:8001`.
- `BACKEND_CORS_ORIGINS` (or `FRONTEND_URL`) includes `http://localhost:3000`.
- (The two `404`s for `com.chrome.devtools.json` and `*.js.map` in the dev log are
  harmless browser/devtools noise — not errors.)

### Voice not working in the browser
- Allow **microphone** permission when prompted.
- Use **Chrome or Edge** (best Web Speech support).
- Use **`http://localhost`** (not a file:// or remote IP).
- `NEXT_PUBLIC_VOICE_MODE=tts`.
- **Restart `npm run dev`** after changing `.env.local`.

### Environment variable changes not reflected
- **Restart the backend** after editing `backend/.env`.
- **Restart the frontend** (`npm run dev`) after editing `frontend/.env.local`.

---

## K. Testing commands

Backend unit/integration tests (all Gemini/TTS calls are mocked — fast, no quota):

```bash
cd backend
python -m pytest tests/ -v
```

Frontend production build (also type‑checks and lints):

```bash
cd frontend
npm run build
```

---

## L. Security rules

**Never commit** any of these (all are gitignored — keep it that way):
- `.env`  (backend secrets)
- `.env.local`  (frontend local config)
- `.secrets/`  (service‑account JSON folder)
- the Google Cloud service‑account JSON
- any API key or key file
- any logs that contain secrets

Never paste a real key into a tracked file, an issue, or chat.

---

## M. Current known limitations

- **Gemini Live mode is experimental** and **not** the default. Use Journey TTS.
- **Journey TTS mode is the stable demo mode.**
- Browser **speech‑recognition quality** depends on the browser/device (Chrome/Edge recommended).
- Sessions are **in memory** — restarting the backend clears analyzed contracts.
- **This is not legal advice.** ProtectMe AI helps you understand contracts and ask better questions.

---

## Tech stack

- **Backend:** FastAPI · Pydantic v2 · google‑genai · Google Cloud TTS (Journey) · PyMuPDF · Uvicorn
- **Agent:** Custom orchestrator (ADK‑compatible) · Gemini streaming · deterministic fast paths
- **Frontend:** Next.js 14 · TypeScript · Tailwind CSS · Zustand
- **Voice:** Browser SpeechRecognition (input) · Google Cloud Journey TTS (output) · Gemini Live (experimental)
