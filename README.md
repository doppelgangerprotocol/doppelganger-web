# The Doppelgänger Protocol
### `doppelgangerprotocol.app/verify`

A browser-based reference implementation of The Doppelgänger Protocol. This is a new standard for human-layer authentication using shared memory as a cryptographic trust anchor.

**The protocol is open.** realxreal is the first mobile implementation.  
Anyone can build on this.

---

## The Protocol

Traditional key exchange has a bootstrap problem: how does Alice know the public key she received actually belongs to Bob and not an impostor? PKI uses certificate authorities. PGP uses a web of trust.

The Doppelgänger Protocol uses **shared human memory** as the trust anchor.

```
Alice creates a challenge              Bob opens the one-time link
─────────────────────────              ────────────────────────────
1. Generate ECDH keypair locally       1. Generate ECDH keypair locally
2. Write memory question               2. See Alice's question
3. Write her answer                    3. Write his answer
4. Server embeds her answer            4. Server scores Bob's answer vs embedding
5. Alice's pubkey + question           5. Score ≥ threshold:
   bundled into one-time link             → Alice's pubkey released to Bob
                                          → Both derive AES-GCM shared secret
                                          → Channel opens
                                       Score < threshold:
                                          → No key exchange. Channel stays closed.
```

**Alice's public key is never exposed to an unverified Bob.**  
The memory answer is the gate. Passing it is what unlocks the key exchange.  
The server never makes a trust decision; the shared memory does.

---

## Why This Matters

A Ferrari executive stopped a deepfake attack by asking one question:  
*"What book did you recommend to me two weeks ago?"*  
The call ended immediately.

That instinct, verifying with shared memory, is what this protocol makes cryptographic, repeatable, and cross-platform. No passwords. No biometrics. No AI can fake it.

---

## Project Structure

```
doppelganger-web/
│
├── README.md
├── requirements.txt
├── Dockerfile
├── wsgi.py
├── .env.example
│
├── app/
│   ├── __init__.py               # Flask factory + rate limiter
│   ├── config.py                 # Dev / prod config
│   │
│   ├── routes/
│   │   ├── pages.py              # HTML routes (/verify, /verify/s/<id>)
│   │   ├── session.py            # POST /api/session — Alice creates challenge
│   │   ├── verify.py             # POST /api/session/<id>/verify — Bob answers
│   │   └── stream.py             # GET  /api/session/<id>/stream — SSE for Alice
│   │
│   ├── services/
│   │   ├── session_store.py      # Redis CRUD with TTL
│   │   ├── embedding_client.py   # Proxy to embedding microservice
│   │   └── qr.py                 # QR code generation
│   │
│   └── utils/
│       ├── session_id.py         # secrets.token_urlsafe(32)
│       └── validators.py         # Input validation
│
├── static/
│   ├── css/
│   │   ├── main.css              # @import only — no rules
│   │   ├── tokens.css            # Design tokens, reset, global typography
│   │   ├── layout.css            # Header, main, footer, two-column waiting layout
│   │   ├── components.css        # Buttons, forms, link box, QR, key status
│   │   └── protocol.css          # Screens, proof panels, loader, pulse
│   └── js/
│       ├── crypto.js             # Web Crypto API — ECDH P-256 + AES-GCM 256
│       ├── session.js            # Alice + Bob state machines
│       ├── sse.js                # Alice's SSE connection
│       ├── ui.js                 # DOM helpers, screen transitions
│       └── debug.js              # Live protocol log panel (floating, non-blocking)
│
└── templates/
    ├── base.html
    ├── index.html                # Alice's flow
    └── session.html              # Bob's flow
```

---

## API

```
POST   /api/session                   Alice creates session
GET    /api/session/<id>              Bob fetches question (Alice's pubkey withheld)
POST   /api/session/<id>/verify       Bob answers → scoring → conditional key exchange
GET    /api/session/<id>/stream       SSE — Alice waits for Bob's result
DELETE /api/session/<id>              Manual teardown (auto-expires after 5 min)
```

### What the server stores (Redis, 5 min TTL)

| Field | Value | Notes |
|---|---|---|
| `phase` | `WAITING_FOR_BOB` / `VERIFIED` / `FAILED` | |
| `alice_name` | string | |
| `memory_question` | string | Shown to Bob |
| `answer_embedding` | JSON vector | Alice's answer as 384-dim vector — raw text never stored |
| `alice_pubkey_jwk` | JSON | Only returned to Bob after PASS |
| `bob_pubkey_jwk` | JSON | Set after PASS, sent to Alice via SSE |
| `similarity_score` | float | Set after verification |

---

## Security Properties

| Property | How |
|---|---|
| Alice's pubkey never exposed to unverified Bob | Only returned in `/verify` response on PASS |
| Raw memory answers never stored | Embedded server-side, raw text discarded |
| Private keys never leave the browser | Web Crypto non-extractable flag |
| Session IDs unguessable | `secrets.token_urlsafe(32)` — 256 bits entropy |
| Sessions self-destruct | Redis TTL = 5 min |
| No accounts / no PII persisted | Ephemeral by design |
| `.app` TLD enforces HTTPS | Google registry policy — SSL required at the domain level |
| Rate limited | 500 sessions/hour, 20 verify attempts/min per IP |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Flask + Gunicorn |
| Session store | Redis Cloud |
| Client crypto | Web Crypto API — ECDH P-256 + AES-GCM 256 |
| Real-time | Server-Sent Events |
| Embedding | all-MiniLM-L6-v2 (separate microservice) |

---

## Local Setup

```bash
git clone https://github.com/doppelgangerprotocol/doppelganger-web
cd doppelganger-web

python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # fill in your values
redis-server &

flask --app wsgi run --debug --port 5001
open http://localhost:5001/verify
```

### Environment variables

```bash
FLASK_ENV=development
SECRET_KEY=your-secret-key
REDIS_URL=redis://localhost:6379
RATELIMIT_STORAGE_URI=redis://localhost:6379
EMBEDDING_SERVICE_URL=http://localhost:8000
EMBEDDING_API_KEY=your-embedding-api-key
BASE_URL=http://localhost:5001
SESSION_TTL_SECONDS=300
```

---

## The Debug Panel

A live protocol log panel is built into the demo (`debug.js`).  
Click **Protocol Log** in the bottom-right corner to open it.

The panel shows every cryptographic event in real time:
- ECDH keypair generation (public key coordinates, non-extractability confirmed)
- Embedding vector preview (first 8 of 384 dimensions)
- Cosine similarity score and pass/fail threshold
- ECDH shared secret derivation on both sides
- SSE events raw JSON
- Redis session phase transitions

The panel is non-blocking — it slides open alongside the main content so you can watch the protocol execute while clicking through the flow.

---

## Implementations

| Implementation | Platform | Repo |
|---|---|---|
| **This repo** | Web (reference) | `https://github.com/doppelgangerprotocol/doppelganger-web` |
| **realxreal** | iOS | [realxreal.app](https://realxreal.app) |

Built your own implementation? Open a PR to add it here.

---

## License

MIT — fork it, implement it, build on it.

To discuss the protocol or implementations: hello@realxreal.ai
