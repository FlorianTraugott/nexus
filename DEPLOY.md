# Deploying Nexus AI (Railway)

This is the exact, ordered procedure to deploy the backend + frontend to Railway
and seed the public demo. Follow it top to bottom. It assumes a Railway account,
the `railway` CLI installed and logged in (`railway login`), and this repo checked
out locally.

Architecture note: the backend is **single-instance by design** (embedded ChromaDB
on a local volume — see the SINGLE-INSTANCE decision in CLAUDE.md). Do not add
replicas; Railway volumes are incompatible with them anyway.

---

## 0. OpenAI spend cap — FIRST, before anything is publicly reachable

This is the only backstop that survives every other control failing. Do it now.

1. OpenAI dashboard → Settings → **Limits** → set a **monthly budget / hard cap**
   on the project whose API key you will deploy with.
2. Create a **dedicated API key for this project** (so you can revoke it without
   touching anything else).

The per-user rate limits in the app (Part 12.5) are defense-in-depth; this cap is
the real financial guarantee.

---

## 1. Generate the JWT secret

```bash
openssl rand -hex 32
```

Save the output; it becomes `JWT_SECRET_KEY` below. **Changing it later invalidates
every issued token** (all users are logged out), so set it once and keep it.

---

## 2. Backend service + Postgres + volume

In the Railway project:

1. **Add Postgres** (Railway → New → Database → PostgreSQL). Note its connection
   string (Railway exposes it as a `DATABASE_URL` reference variable).
2. **Create the backend service** from this repo, root directory `backend/`
   (it builds `backend/Dockerfile`).
3. **Attach a volume** to the backend service, mounted at **`/data`** (Railway →
   service → Settings → Volumes). This is where Chroma vectors and uploaded files
   live. It pins the service to one instance permanently — expected.
4. **Pre-deploy command** (Railway → service → Settings → Deploy): set it to

   ```
   alembic upgrade head
   ```

   Railway runs this in a separate container off the built image before the new
   version goes live; a non-zero exit blocks the deploy (fail-loud migrations).

### Backend environment variables

Set these on the backend service (Railway → service → Variables):

| Variable | Value | Why |
|---|---|---|
| `ENVIRONMENT` | `production` | validated; gates prod behaviour |
| `DEBUG` | `false` | no verbose errors / SQL echo |
| `REGISTRATION_ENABLED` | `false` | closes public sign-up (returns 403) |
| `TRUST_PROXY_HEADERS` | `true` | read client IP from X-Forwarded-For (see step 4) |
| `DATABASE_URL` | *(reference the Postgres var)* | overrides POSTGRES_\*; normalised to asyncpg |
| `DB_SSL_REQUIRE` | `true` | managed Postgres requires TLS |
| `CHROMA_PERSIST_DIR` | `/data/chroma` | on the mounted volume |
| `UPLOAD_DIR` | `/data/uploads` | on the mounted volume |
| `OPENAI_API_KEY` | *(the capped key from step 0)* | embeddings + generation + vision |
| `JWT_SECRET_KEY` | *(step 1 output)* | token signing |
| `DEMO_USER_EMAIL` | `demo@nexus.ai` *(or your choice)* | the shared demo login |
| `DEMO_USER_PASSWORD` | *(choose one; not a secret)* | shown to visitors |
| `CORS_ORIGINS` | *(placeholder for now)* | set to the real frontend URL in step 3 |

Notes:
- Do **not** set `GEMINI_API_KEY`, `EVAL_USER_EMAIL`, or a Tavily key: the eval
  harness does not deploy, and web search stays the offline `null` provider.
- `RATE_LIMIT_QUERY` / `RATE_LIMIT_VISION` / `RATE_LIMIT_RESEARCH` have sane
  defaults (60/20/10 per hour); override only if you want different ceilings.

Deploy the backend. When it is up, **copy its public URL** (e.g.
`https://nexus-backend-production.up.railway.app`). You need it for step 3.

Sanity check: `GET <backend-url>/health` should return ok. On first boot with an
empty corpus the Part 12.2b consistency check logs `pg_chunks=0 chroma_chunks=0`
and starts clean.

---

## 3. Frontend service — the circular URL sequence

`NEXT_PUBLIC_API_URL` is **baked into the frontend bundle at build time**, so the
frontend cannot be built until the backend URL exists. Hence the ordering:

**(a) backend deployed (step 2) → (b) build frontend with the backend URL →
(c) point the backend's CORS at the frontend URL → redeploy backend.**

1. Create the **frontend service** from this repo, root directory `frontend/`
   (builds `frontend/Dockerfile`).
2. Set frontend **build-time** variables (Railway passes service variables as
   build args to the Dockerfile ARG of the same name):

   | Variable | Value |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | the backend URL from step 2 |
   | `NEXT_PUBLIC_DEMO_RESEARCH_TASK_ID` | `de300000-0000-4000-a000-000000000001` |
   | `NEXT_PUBLIC_DEMO_EMAIL` | the same value as the backend's `DEMO_USER_EMAIL` |
   | `NEXT_PUBLIC_DEMO_PASSWORD` | the same value as the backend's `DEMO_USER_PASSWORD` |

   The research task id is the fixed id of the pre-seeded task (a constant in
   `scripts/seed_demo.py`), so the frontend's "example report" link can point at
   it. It is known in advance precisely because it is a hardcoded constant, not
   generated at seed time.

   The last two put the shared demo credentials on the sign-in page, so a
   visitor is not stopped by a login wall. Both must be set or the panel does not
   render — and `/login` hides its "Create one" link on the same condition, so a
   build that sets only one leaves a visitor with neither a sign-up nor a way in.
   They must match the backend's `DEMO_USER_*` exactly, or the credentials shown
   won't work.

   > Publishing the password in the bundle is safe **only** because
   > `REGISTRATION_ENABLED=false` and the demo account is shared and disposable.
   > If registration is ever reopened, remove these two variables.
3. Deploy the frontend. Copy **its** public URL.
4. Back on the **backend** service, set `CORS_ORIGINS` to the frontend URL
   (exact origin, no trailing slash) and **redeploy the backend**.

> Changing the backend URL later means **rebuilding** the frontend (the URL is
> compiled in), not just restarting it.

---

## 4. Verify the real X-Forwarded-For hop count (do NOT trust this from docs)

Part 12.2a's limiter takes the **rightmost** entry of `X-Forwarded-For`, assuming
**one** trusted proxy hop in front of the app. If Railway's chain differs, the
IP-keyed limits (register/login) collapse to a single global bucket and the
registration limiter becomes meaningless. Verify against a **real request**:

1. Temporarily add a log line at the top of `app/api/health.py`'s handler:

   ```python
   from app.core.middleware import _client_identifier
   log.info("xff_debug", xff=request.headers.get("x-forwarded-for"),
            resolved_key=_client_identifier(request))
   ```

   (add `request: Request` to the handler if needed). Deploy.
2. From a known network, find your public IP (`curl https://api.ipify.org`), then
   `curl <backend-url>/health`.
3. Read the backend logs. `resolved_key` **must equal your real public IP**. If it
   shows a Railway-internal address (e.g. `10.x`, `100.x`) or the wrong hop, the
   one-hop assumption is wrong — adjust the entry index in `_client_identifier`
   (`middleware.py`) accordingly and redeploy.
4. **Remove the debug log** and redeploy.

---

## 5. Seed the demo — AFTER the volume is mounted

Run the seed **against the deployed backend service** so it writes into the
mounted `/data` volume and the production Postgres. Run it from the repo, using
Railway's environment (NOT a local run — a local `make seed-demo` would seed your
laptop, not production):

```bash
railway run --service <backend-service-name> python -m scripts.seed_demo
```

Expected: 3 documents created (2 markdown → chunks, 1 PDF → 1 captioned image),
and `research task: created`. It is idempotent — re-running it is safe and makes
no OpenAI calls once everything is present, so running it again after a redeploy
is harmless.

---

## 6. End-to-end verification, then prove state survives a redeploy

Against the **frontend URL** in a real browser:

1. **Registration closed:** go to `/register`, submit — expect a 403 / "registration
   is disabled" (the `REGISTRATION_ENABLED=false` gate).
2. **Demo login:** log in with `DEMO_USER_EMAIL` / `DEMO_USER_PASSWORD`.
3. **Documents:** the three seeded Aurora docs are listed as `completed`.
4. **Query:** ask "What is Aurora's battery capacity?" → grounded answer (8 MWh)
   with citations.
5. **Streaming:** ask another question in chat → tokens stream in; sources appear
   before the first token.
6. **Vision:** ask the quarterly-output document "What was the Q3 energy output?"
   → 4.8 GWh, from the chart image.
7. **Research (pre-seeded):** open the "example report" link → the COMPLETED
   Project Aurora report renders instantly (zero cost).
8. **Research (live):** submit a new research topic → 202 → poll → report (this
   spends; the rate limit caps it).
9. **Upload:** upload a small PDF/txt → it ingests to `completed` and is queryable.

Then the **acceptance test for the state strategy (D2)**:

10. **Redeploy the backend** (Railway → service → Redeploy, or push a trivial
    change).
11. After it restarts, re-run query (step 4) and vision (step 6). They must still
    work — the seeded vectors and image files survived on the `/data` volume. The
    backend logs should show the consistency check with a **non-zero
    `chroma_chunks`** matching `pg_chunks`. If the volume were misconfigured, the
    Part 12.2b consistency check would **fail the boot loudly** instead of the app
    silently abstaining on everything — that loud failure is the point.

If step 11 passes, the state strategy is proven, not assumed.

---

## Rollback / redeploy notes

- A bad deploy: Railway → service → Deployments → redeploy a previous green build.
- Rotating `OPENAI_API_KEY`: update the variable and redeploy; no code change.
- The demo account is shared, so any visitor can delete the seeded documents.
  Re-run step 5 to restore them (idempotent).
