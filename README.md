# e& Customer Service UI

A portable Flask application that presents customer-service workflows in a polished, mobile-first interface. It runs locally in a virtual phone frame on desktop, offers an expanded desktop preview without losing the preview controls, and switches to a stable full-screen layout on smaller devices.

The repository includes working authentication, a local SQLite data layer, Network & Bill Intelligence, Complaint Intelligence, Profile management, and a data-driven Roaming Recommender. The roaming workflow combines deterministic Python analysis with optional Gemini reasoning and strict backend validation.

## How it was built

The application uses a Flask application factory with separate authentication and application blueprints. Jinja renders the page shell, while modular vanilla JavaScript controls navigation, loading states, workflow restoration, chat refinements, and session-only saved recommendations. A shared workflow-state controller gives multi-screen journeys consistent forward/back behavior. Custom CSS provides the design system, phone frame, responsive layouts, readable type scale, and directional motion; mobile viewport handling keeps the interface stable when the iPhone keyboard opens.

SQLAlchemy owns all persistent records. The application creates `instance/prototype.db` automatically, performs an idempotent SQLite schema upgrade, and applies repeatable seed definitions at startup. Passwords are hashed with Argon2.

The Roaming Recommender follows this pipeline:

```text
Authenticated user
  -> six raw monthly usage rows from SQLite
  -> per-metric outlier and trend analysis
  -> recency-weighted monthly profile
  -> exact six-decimal inclusive trip requirements
  -> shared exact-match Smart Recommendation History lookup
     -> hit: return the revalidated stored plan with zero Gemini calls
     -> miss: Gemini 3.6 Flash plans from all 42 active packages
  -> chat: stateless Gemini 3.5 Flash-Lite interpretation
     -> clarification when the service itself is ambiguous
     -> comparative wording such as "more" becomes the next allowance tier
     -> fully understood requirements continue to exact Smart History lookup
     -> planner call only when that lookup misses
  -> Python package, price, allowance, segment, and coverage validation
  -> validated Gemini structural plan saved to shared Smart History
  -> bounded deterministic fallback when Gemini is unavailable or invalid
  -> validated single, repeated, mixed, or segmented package plan
  -> server-side history for previous/original package navigation
```

## Technology stack

| Layer | Technology | Responsibility |
|---|---|---|
| Backend | Python 3.11+, Flask, Waitress | Application factory, routes, sessions, validation, orchestration, and production-grade WSGI serving |
| Data | SQLite, Flask-SQLAlchemy | Users, monthly usage, package catalogue, Smart Recommendation History, bills, diagnostics, and complaints |
| Authentication | Flask-Login, Flask-WTF, Argon2 | Protected routes, CSRF protection, sessions, and password hashing |
| Recommendation reasoning | Google Gen AI SDK, Pydantic | Stateless Gemini 3.5 Flash-Lite requirements interpretation and stateful Gemini 3.6 Flash package planning |
| Frontend | Jinja2, vanilla JavaScript | Rendered shell, workflow state, API integration, and interactions |
| Styling | Custom CSS and inline SVG | Responsive phone presentation, design tokens, readable sizing, safe areas, and directional motion |
| PWA | Web App Manifest, service worker | iPhone Home Screen installation, stable standalone viewport, safe static caching, updates, and offline fallback |
| Public access | Waitress, Cloudflare Quick Tunnel | Loopback-only WSGI serving and temporary HTTPS access from an iPhone |
| Testing | Pytest, Playwright | Unit, integration, security, API, and browser journeys |

Python 3.11 and newer are supported. Python 3.14.2 is suitable; the GitHub Actions workflow covers Python 3.11 and 3.14 on Windows and Linux.

## What is functional and what remains local

| Area | Implemented | Integration boundary |
|---|---|---|
| Authentication | Registration, duplicate checks, login, logout, remembered sessions, Argon2 hashes, CSRF | Password-recovery delivery does not send email or SMS |
| Database | Automatic creation, safe additive upgrade, idempotent seed data, persistent customer activity | Each clone has its own ignored local SQLite file |
| Network | Diagnostic workflow, results, local history, coverage layers, location choice | Measurements and map layers use deterministic local values |
| Bills | Upload/manual journeys, draft restoration, editable fields, charts, anomalies, plan review, and six-month usage history | Files are not sent to OCR or billing systems |
| Complaints | Chat and form paths, summary, database ticket creation, tracking, notes, closure | No external CRM or human-agent system is connected |
| Roaming | Four-step mobile journey, usage analysis, 42-package catalogue, shared exact-match Smart History, Gemini reasoning, deterministic fallback, plan sequences, refinements, and session saves | Package activation and dialer actions do not change a live account |
| Profile | Persisted profile and preference edits, links to account activity | Email remains read-only in this application |
| iPhone installation | Manifest, branded Home Screen icon, zoom-resistant standalone presentation, safe areas, keyboard stability, update prompt, and offline status page | The Windows server and HTTPS tunnel must remain reachable |

Gemini is the only optional external service. Initial Smart History hits use no model. On an initial miss, the planner receives exact trip requirements and a compact active package catalogue. Each actionable chat message goes first to the stateless interpreter with the raw message, complete current requirements, current package allowances, trip context, and any pending clarification. Requests such as “more minutes” ask only whether the user means local or international; after that answer, Python converts “more” into the smallest value above the current package allowance without asking for an exact number. A planner miss receives only the interpreter's exact structured result, never the raw chat message. Neither model receives user IDs, raw usage history, email, phone number, password, password hash, cookies, or authentication tokens.

## Main product areas

- **Home** — three equally prominent service widgets, account snapshot, alerts, notifications, help, and reviewable UI states.
- **Network & Bill** — network diagnostics and history, coverage visualization, bill upload/manual entry, charge analysis, anomalies, plan review, and a six-card Usage History view for the latest six months.
- **Complaints** — guided chat, structured form, attachment state, generated summary, ticket submission, ticket timeline, notes, and history.
- **Roaming** — a four-step recommender with prefix-searchable destinations, date validation, automatic usage-based planning, natural-language adjustments, package sequences, temporal segments, protected activation controls, and saved plans.
- **Profile** — customer details, masked phone number, notification preferences, contact preference, activity links, help, and logout.

## Roaming Recommender experience

The product entry point is consistently named **Roaming Recommender**. **Roam with Balance** is one package family inside the catalogue, not the name of the recommender. Its legacy `RLH-*` package codes remain stable so existing database rows and saved structural plans do not need a destructive rename.

### Customer journey and design rationale

| Stage | Current experience | Why it is designed this way |
|---|---|---|
| Landing | A locally bundled travel image keeps its original `1150:560` aspect ratio and resizes without cropping. The page has one clear **Start planning** action plus recent and session-saved recommendations when available. | The visual establishes travel context immediately, while a single primary action avoids competing choices. Local delivery keeps the page independent of image CDNs. |
| Step 1 — Destination | Countries are grouped A–Z, displayed one country per row, and filtered by the beginning of the country name. Searching `B` therefore cannot surface Saudi Arabia merely because another field contains that letter. Only the country list scrolls; the search, progress context, and **Continue** button remain visible. | One full-width country per line improves scanning and tap accuracy. Prefix matching makes results predictable, and isolating scroll prevents the main action from moving out of reach. |
| Step 2 — Travel dates | The selected destination stays visible and editable. Departure and return dates must be in the future and the return cannot precede departure. The displayed trip length is inclusive of both travel dates. | Keeping trip context on screen reduces accidental input for the wrong destination. Inclusive dates match how package validity and allowance requirements are calculated on the backend. |
| Step 3 — Review and adjust | One validated plan is shown with its package sequence, price, destination, duration, combined validity, allowances, and activation count. Usage evidence and **Why this fits** sit behind optional **More details**. A larger free-text chat replaces suggested-answer chips; after a successful refinement, the updated recommendation scrolls into the top reading position. | The default card answers the decision-making questions without overwhelming the customer. Evidence remains available for reviewers, while open text lets users describe real needs in their own words. Returning focus to the changed card makes the result of a chat request obvious. |
| Step 4 — Final recommendation | The completion view repeats only the facts needed to act: sequence, total cost, coverage, allowances, and activation order. It omits the longer **Why this fits** explanation. Activation codes remain hidden and copy/dialer actions remain disabled until the customer acknowledges the preferred partner-network note. | The final page is an action checklist rather than a second analysis screen. The acknowledgement reduces the chance of activating while connected to the wrong carrier, and the dialer never activates a package automatically. |

If no plan can be shown, the empty state retains the destination and dates and returns the customer to adjustment instead of discarding the trip.

### Conversation behavior

- The first recommendation requires no chat prompt. Six months of the signed-in customer's usage are analysed and scaled to the selected trip before a package plan is requested.
- An exact Smart Recommendation History hit returns a freshly revalidated plan without calling Gemini. A miss uses the planner, and an unavailable or invalid model response uses the same backend requirements with the deterministic optimizer.
- Each chat message is interpreted against the complete current requirements and the **latest selected plan**, not only the original plan. This makes a second or third refinement cumulative.
- An explicit request such as “I need 200 local minutes” sets a minimum. Every service the user did not change must remain at least as generous as it is in the current plan; the selected plan may exceed the requested minimum if that is the next valid catalogue tier.
- A relative request such as “I need more data” means the next valid allowance above the current plan; the user is not asked to invent an exact number. “I need more minutes” asks one useful clarification—local or international—then applies the same next-tier rule.
- Clarifications use the lightweight interpreter only. The package planner is called only after the message has become complete technical requirements and Smart History has missed.
- Greetings and previous/original-plan navigation are handled locally. Model ambiguity, invalid output, or downtime never ends the journey: the backend clarifies or applies deterministic parsing and optimization. A quota or frequency failure is labelled **Gemini limit** in chat so it is distinguishable from an interpretation question.

### Mobile layout and motion choices

- Forward workflow views enter from the left and settle to the right; back views enter from the right and settle to the left. The shared `360 ms` eased transition is used across authenticated screens, segmented panels, and workflow steps so progression and regression feel related rather than abrupt.
- `prefers-reduced-motion` removes non-essential movement while preserving navigation and state changes.
- On desktop, Phone and Expanded preview controls remain outside the constrained application surface and stay reachable in either mode. Expanded content is width-limited for readability rather than stretching indefinitely.
- Text-based `e&` marks use compact negative letter spacing so the two characters read as one brand mark. The same treatment is reused in authentication, the app header, assistant avatars, and installation guidance for visual continuity.
- On iPhone, the viewport disables browser zoom and mobile form fields use a 16 px font to prevent focus zoom. `visualViewport` is tracked separately from the stable application height so opening the Apple keyboard does not push the bottom navigation upward.
- Focusing the roaming adjustment box scrolls the chat card to the top of the visible application area, leaving the remaining viewport for the keyboard. After the keyboard closes, the stable shell height is restored.
- Small labels, metadata, chat text, country names, and tap targets were raised to a consistent readable scale without making the compact phone layout feel oversized.

### Copy and placeholder boundaries

Static customer-facing screens avoid repeated “demo” or “prototype” labels because those notices competed with the actual task. A placeholder action still explains its boundary at the moment it is used—for example, the plan-switch confirmation states that it does not change a real account. The README remains the source of truth for all local and external-integration boundaries, and the seeded identities use unmistakably fictional `.example.test` details.

## Database structure

The runtime database is `instance/prototype.db`. Both `instance/` and database file extensions are ignored by Git. A fresh clone does not need a copied database because `python run.py` creates and seeds one automatically.

| Table/model | Responsibility |
|---|---|
| `User` | Identity, contact information, Argon2 password hash, and preferences |
| `UserMonthlyUsage` | One raw usage row per user/month for data, local minutes, international minutes, and SMS |
| `RoamingPackage` | Complete package facts, including code, family, duration, price, allowances, activation code, and stacking flags |
| `RoamingRecommendationHistory` | Validated package versions and parent links for previous/original chat navigation |
| `SmartRecommendationHistory` | Shared exact requirement keys, normalized split meaning, structural package plans, and reuse statistics; contains no user identity |
| `BillRecord` | Confirmed bill totals, charge groups, due date, and anomaly summary |
| `DiagnosticResult` | Saved download, upload, latency, location label, and verdict |
| `ComplaintTicket` | Ticket details, status, routing, expected resolution, and notes |

Database guarantees include unique user email, unique phone number, unique package code, unique user/month usage rows, and non-negative monthly usage checks.

### Seeded accounts

All four accounts use the password `Demo123!`; only its Argon2 hash is stored in SQLite.

| Name | Email | Phone |
|---|---|---|
| Aisha Noor | `aisha@example.test` | `+971500000101` |
| Omar Hassan | `omar@example.test` | `+971500000102` |
| Layla Faris | `layla@example.test` | `+971500000103` |
| Yusuf Kareem | `yusuf@example.test` | `+971500000104` |

The seed module creates exactly:

- 4 required login accounts
- 6 monthly usage rows per account, or 24 rows total
- 42 active, repeatable, stackable roaming packages across 7 families

The seven package families are `Roam Essentials`, `Roam with Balance`, `Roam Premium`, `Data First`, `Data Plus`, `Voice First`, and `Voice Plus`. Each family has 1-, 3-, 7-, 10-, 14-, and 30-day tiers. Package codes are stable database identifiers and may keep an older prefix even when customer-facing wording changes.

Existing unrelated users, bills, complaints, diagnostics, and other records are preserved. Re-running the seed operation updates the defined seed rows without duplicating them.

## Usage analysis and recommendation logic

`app/services/usage_analysis.py` analyses data, local minutes, international minutes, and SMS independently.

- Records are ordered from January through June 2026.
- Recency weights are exactly `0.10, 0.12, 0.15, 0.18, 0.20, 0.25`.
- Median Absolute Deviation identifies statistical candidates; IQR/surrounding-value logic handles zero MAD.
- Only an isolated spike or drop is excluded from that metric's calculation.
- Remaining weights are renormalized after an exclusion.
- Sustained upward or downward changes remain included and are never extrapolated.
- Trip duration is inclusive and scales monthly usage with `trip_days / 30`.
- Smart History keys use the exact trip values at six decimal places.
- Gemini, backend validation, and deterministic fallback all use those same values directly as minimum requirements.
- Gemini is instructed to choose the lowest-priced valid plan, using lower allowance excess and fewer activations as tie-breakers.

When Gemini is configured, `app/services/gemini_requirements_interpreter.py` converts each actionable chat message into a complete exact state and identifies changed and preserved metrics. Python verifies the preserved values, trip period, segment coverage, and independently calculated split totals before any lookup or plan. Relative increases are resolved against the current selected package: data uses a strict `+0.001 GB` requirement and minutes or SMS use `+1`, causing the planner or optimizer to choose the next valid catalogue allowance while keeping every unchanged service at least as generous as the current package. `app/services/user_requirement_parser.py` remains the local parser and adjustment fallback when Gemini is not configured, rate-limited, unavailable, or invalid.

`app/services/package_fallback_optimizer.py` uses a bounded, canonicalized search rather than uncontrolled brute force. It can select one package, repeat a package, mix families, produce exact-duration combinations, and optimize each requested trip segment independently.

`app/services/recommendation_validator.py` reloads every package fact from SQLite and recalculates all totals. Gemini-supplied price, allowance, validity, activation code, or arithmetic is never trusted.

### Smart Recommendation History

Before an initial planner call, and after every fully understood chat interpretation, the backend searches one system-wide exact key: `data_gb`, `local_minutes`, `international_minutes`, `sms`, inclusive `period_days`, and `split`. Numeric fields use `Numeric(18, 6)` and one shared Decimal canonicalizer. Split requests additionally require identical canonical segment JSON and its SHA-256 signature; segments must cover Day 1 through the final day exactly once.

On a hit, only package codes and scheduling structure are read from history. Current package rows are reloaded from SQLite, totals and coverage are recalculated, and the complete plan is validated again. Missing, inactive, insufficient, or invalid plans are treated as misses. A hit never calls Gemini and returns a new generic explanation rather than another user's wording. Requests such as cheapest, premium, fewer activations, package exclusions, budgets, or other preferences outside the six fields bypass reuse.

History stores no user ID, name, email, phone, raw chat message, Gemini prompt, session value, or API key. Valid Gemini plans are upserted; fallbacks and invalid responses are not saved. API responses identify `recommendation_source` as `gemini`, `smart_history`, or `fallback` and include `smart_history_hit` without exposing the row ID or split signature.

Standalone greetings and package-history navigation are handled locally without an API call. Distinct validated recommendations are stored server-side for the active journey, allowing repeated “previous package” navigation and exact restoration of the original recommendation. Colloquial budget, reset, and service-focus phrases also have deterministic handling when Gemini is unavailable.

## Gemini configuration

Gemini is called only by the Flask backend. The API key is never included in JavaScript, templates, API responses, or logs.

1. From the repository root, copy `.env.example` to `.env` if `.env` is not already present:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Open `.env` in any text editor.
3. Insert the key after `GEMINI_API_KEY=`.

```dotenv
GEMINI_API_KEY=
GEMINI_INTERPRETER_MODEL=gemini-3.5-flash-lite
GEMINI_PLANNER_MODEL=gemini-3.6-flash
GEMINI_TIMEOUT_SECONDS=30
GEMINI_RATE_LIMIT_COOLDOWN_SECONDS=60
GEMINI_REQUEST_LOG_DIR=instance/api_request_logs
```

The file is always `<repository-root>/.env`; no user-specific absolute path is required. `.env` is ignored by Git. If the key is blank, absent, times out, reaches a quota limit, or returns an unusable response, the application continues through the deterministic optimizer. Copied example placeholders are also treated as unconfigured rather than being sent to Google.

The Gemini service uses:

- `google-genai`, not the deprecated `google-generativeai` package
- Strict Pydantic JSON schemas for both model roles
- `thinking_level="high"` for both models
- No `temperature`, `top_p`, or `top_k` override; Gemini 3.x uses its provider defaults
- The same backend-only `GEMINI_API_KEY` with separate configured model IDs
- Gemini 3.5 Flash-Lite as a stateless requirements interpreter with `store=False`, no `previous_interaction_id`, and no package catalogue
- Gemini 3.6 Flash as the package planner with `store=True`
- The complete active package catalogue, limited to selection fields, only on the first planner call in a recommendation session
- `previous_interaction_id` and catalogue omission on later planner misses
- A locally validated baseline schedule that Gemini can copy or improve
- A compact structural response schema and 30-second request timeout
- A provider-directed rate-limit cooldown (60-second fallback) so consecutive chat messages do not repeatedly hit an exhausted quota
- Clarification responses that leave the recommendation unchanged and skip Smart History and the planner
- Exact comparative requirements resolved from the current package without asking the user for a number
- Immediate deterministic fallback when either model is unavailable, rate-limited, or invalid
- An explicit `Gemini limit` chat message for quota/rate-limit fallback; other failures stay usable through a local clarification or adjustment
- Backend-only error handling with no raw model response exposed to the browser

Every initial recommendation starts a new application recommendation session and
clears the prior planner interaction ID. An exact initial Smart History hit returns
without either model and leaves the planner uninitialized. If a later interpreted
chat request misses history, that first planner call receives the current validated
plan, exact requirements, trip context, and all active packages without a previous
ID. Later planner misses continue the latest valid interaction and omit packages.
A Smart History hit between planner turns updates the application state without
advancing or erasing that planner chain. Only a backend-validated planner response
may create or advance an interaction ID.

Google stores only Gemini 3.6 planner interactions for continuation. Gemini 3.5
interpreter calls are explicitly not stored. Planner retention follows the Gemini
project tier and settings configured in AI Studio.

Every outbound Gemini attempt is saved as a separate JSON file in
`instance/api_request_logs/`. Filenames distinguish `interpreter`,
`planner_initial`, and `planner_refinement` calls. Each file contains the model,
system instruction, input context, generation settings, response schema,
conversation reference when applicable, storage flag, and timeout sent for that
call. API keys and model responses are not written.
The folder is created automatically and remains local because `instance/` is ignored by Git.

## API overview

| Route | Purpose |
|---|---|
| `POST /api/roaming/recommend` | Build the initial recommendation for `current_user` |
| `POST /api/roaming/refine` | Recalculate the current plan from the latest user instruction |
| `GET /api/roaming/current` | Restore the current validated recommendation after refresh |
| `GET/POST /api/roaming/saved` | List or save validated session-only recommendations |
| `DELETE /api/roaming/saved/<id>` | Remove a saved recommendation |
| `GET/PUT/DELETE /api/workflows/<name>` | Restore, persist, or reset compact workflow state |
| `POST /api/diagnostics` | Save a deterministic diagnostic result |
| `POST /api/bills` | Save confirmed bill fields |
| `POST /api/complaints` | Create a complaint ticket |
| `POST /api/profile` | Save editable profile preferences |

The roaming routes never accept a browser-provided user ID as authoritative; they always use Flask-Login's `current_user.id`.

## PWA and offline behavior

The manifest starts at `/`, so normal Flask authentication remains authoritative: an active session opens the application and an unauthenticated session redirects to sign-in. The installed presentation uses portrait standalone mode, the existing red theme, iPhone safe areas, and 16 px mobile form controls to avoid focus zoom. The viewport also disables pinch zoom so the installed experience behaves like a stable app surface rather than a freely zoomable webpage.

The 180×180 Apple touch icon uses the supplied red **e& / etisalat and** artwork. Standard and maskable local PNG variants support other install surfaces. iOS caches Home Screen artwork aggressively; after an icon update, remove the existing Home Screen item and add it again if the old artwork remains.

Mobile keyboard handling tracks `window.visualViewport` while retaining a separate stable application height. When a form control is focused, the shell and bottom navigation keep their position and the relevant control—especially the roaming adjustment chat—is aligned into the visible area above the keyboard. This behavior is progressive enhancement: all inputs still work in browsers without `visualViewport`.

The root service worker uses the version declared as `CACHE_VERSION` in `app/static/service-worker.js`. It caches only local CSS, JavaScript, icons, the manifest, and the session-neutral offline page. Navigations are always network-first and are never stored. `/app`, `/auth`, `/api`, non-GET requests, personalized HTML, CSRF tokens, SQLite-derived data, and Gemini responses are never cached.

When the server cannot be reached, navigation falls back to a generic connection page without account information. SQLite, login, Gemini, and the application workflows remain server-side and do not operate offline. When frontend assets change, increment `CACHE_VERSION`; the application then offers a Refresh action when the new worker is ready instead of interrupting an active form or chat.

## User manual assets

The `docs/roaming_user_manual_capture/` folder contains the Roaming Recommender user-manual handoff and its reviewed screenshot set:

- `USER_MANUAL_HANDOFF.md` — complete customer workflow, UI labels, validation and safety notes, screenshot manifest, and observed behavior.
- `screenshots/mobile/` — primary phone/PWA walkthrough screenshots.
- `screenshots/desktop/` — desktop Phone and Expanded mode reference screenshots.

## Project structure

```text
UI POC/
|-- app/
|   |-- __init__.py                 Application factory, extensions, schema setup, seed command
|   |-- extensions.py               SQLAlchemy, Flask-Login, and CSRF instances
|   |-- models.py                   Persistent database models and serializers
|   |-- pwa.py                      Manifest, root service worker, and session-neutral offline routes
|   |-- schema_upgrade.py           Safe additive SQLite package and Smart History upgrades
|   |-- seed_data.py                Idempotent users, usage history, packages, and account activity
|   |-- auth/
|   |   |-- forms.py                Login and registration validation
|   |   `-- routes.py               Registration, login, logout, password-recovery response
|   |-- main/
|   |   `-- routes.py               Authenticated pages and JSON API routes
|   |-- services/
|   |   |-- usage_analysis.py       Outliers, trends, recency weighting, and trip scaling
|   |   |-- recommendation_values.py Shared six-place Decimal canonicalization
|   |   |-- smart_history.py        Exact keys, split JSON, lookup/upsert, plan rehydration, and statistics
|   |   |-- user_requirement_parser.py  Numeric, comparative, and temporal chat parsing
|   |   |-- gemini_requirements_interpreter.py Stateless exact chat interpretation and clarification
|   |   |-- gemini_recommender.py   Stateful structured Gemini package-planner client
|   |   |-- recommendation_validator.py Package facts, coverage, totals, segments, constraints
|   |   |-- package_fallback_optimizer.py Bounded deterministic package-plan search
|   |   |-- roaming_chat_intent.py  Greetings and package-history navigation intents
|   |   |-- roaming_history.py      Server-side recommendation history and parent navigation
|   |   |-- roaming_recommendation.py End-to-end recommendation orchestration
|   |   |-- mock_diagnostics.py     Deterministic network result values
|   |   |-- mock_bill_analysis.py   Bill anomaly and plan-review calculations
|   |   `-- mock_complaints.py      Complaint classification and routing rules
|   |-- templates/
|   |   |-- base.html               Shared metadata, virtual phone, install help, and update UI
|   |   |-- offline.html            Non-sensitive connection fallback
|   |   |-- auth/                   Login and registration views
|   |   `-- app/shell.html          Authenticated screens, sheets, dialogs, and navigation
|   `-- static/
|       |-- manifest.webmanifest    Install identity, scope, display mode, colors, and icons
|       |-- service-worker.js       Versioned static cache and network-first navigation fallback
|       |-- icons/                  Branded Apple, standard, and maskable local PNG icons
|       |-- images/                 Local interface artwork, including the roaming-advisor hero
|       |-- css/                    Design system, phone frame, safe-area, and offline styles
|       `-- js/                     Workflows plus PWA registration, updates, install help, and offline status
|-- docs/
|   `-- roaming_user_manual_capture/ User-manual handoff plus mobile and desktop screenshots
|-- tests/
|   |-- conftest.py                 In-memory application/database fixtures
|   |-- test_seed_data.py           Seed counts, constraints, hashes, preservation, idempotency
|   |-- test_usage_analysis.py      Reference weights, outliers, MAD fallback, trend protection
|   |-- test_trip_requirements.py   Inclusive dates and exact trip-duration scaling
|   |-- test_requirement_parser.py  Numeric, comparative, latest-input, and segment parsing
|   |-- test_package_plans.py       Optimizer, factual validation, scheduling, and segments
|   |-- test_gemini_recommender.py  Structured requests, latency settings, errors, and fallback
|   |-- test_two_model_pipeline.py  Interpreter/planner roles, history routing, IDs, and split state
|   |-- test_refinement_behavior.py Explicit and comparative refinement enforcement
|   |-- test_roaming_api.py         Authentication, current-user isolation, APIs, and saved plans
|   |-- test_roaming_chat_intent.py Greetings and previous/original navigation language
|   |-- test_pwa.py                 Manifest, icons, routes, cache policy, metadata, and auth start flow
|   |-- test_portability.py         Secret templates, ignore rules, path independence, and key-shape scan
|   |-- test_smart_history.py       Exact matching, splits, revalidation, privacy, call counts, and CLI commands
|   |-- test_public_server.py       Proxy trust, HTTPS cookies, CSRF, Waitress, and local HTTP behavior
|   `-- browser/                    Playwright end-to-end customer journeys and console audit
|-- tools/generate_pwa_icons.py     Deterministic local icon generator
|-- instance/                       Local runtime database and backups; created and ignored
|-- .github/workflows/tests.yml     Windows/Linux CI matrix for Python 3.11 and 3.14
|-- config.py                       Environment-based application configuration
|-- run.py                          Loopback local server entry point
|-- serve_public.py                 Hardened loopback Waitress entry point for an HTTPS tunnel
|-- start_iphone_pwa.ps1            Checked Waitress + Cloudflare Quick Tunnel launcher
|-- requirements.txt               Pinned Python dependencies
|-- .env.example                    Safe environment-variable template
`-- .gitignore                      Local secrets, databases, environments, caches, and IDE files
```

## Local setup

### Prerequisites

- Python 3.11 or newer; Python 3.14.2 is supported and covered by CI.
- Git only if cloning from the command line. A GitHub ZIP download works as well.
- No Node.js, npm, frontend compiler, database server, or API key is required.
- Chromium is needed only for the optional browser tests.

### Get the source

Clone the branch containing this application:

```powershell
git clone --branch UI-Demo --single-branch https://github.com/LeKiksss/e-InternshipTrio.git
Set-Location e-InternshipTrio
```

Alternatively, select the `UI-Demo` branch on GitHub, choose **Code → Download ZIP**, extract it anywhere, and open a terminal in the extracted folder. Every command below is relative to that repository root; no developer-specific path is assumed.

### First run on Windows PowerShell

```powershell
python -m venv .venv
& ".\.venv\Scripts\Activate.ps1"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python run.py
```

### First run on macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python run.py
```

Open:

```text
http://127.0.0.1:5000
```

`python run.py` serves locally through Waitress on `127.0.0.1`. On the first launch, the application creates `<repository-root>/instance/prototype.db`, upgrades its schema if necessary, and inserts the required seed records. The ignored `instance/` directory does not need to be downloaded or copied from another developer.

Public temporary access uses the stricter `serve_public.py` entry point described below. Neither entry point exposes Flask's built-in development server.

On later local runs, dependencies do not need to be reinstalled unless `requirements.txt` changed:

```powershell
& ".\.venv\Scripts\Activate.ps1"
python run.py
```

Stop the server with `Ctrl+C`. Waitress does not auto-reload source changes, so after modifying Python, templates, CSS, or JavaScript, stop and restart the active Python server. When using a Quick Tunnel on the same port, cloudflared may stay running while `serve_public.py` is restarted; the HTTPS URL normally remains the same until cloudflared itself is stopped.

### Optional configuration

Local mode works without `.env` and without Gemini. To configure either, copy the safe blank template:

```powershell
Copy-Item .env.example .env
```

| Variable | Required | Purpose |
|---|---|---|
| `SECRET_KEY` | Public mode only | Stable session-signing secret with at least 32 characters |
| `APP_HOST`, `APP_PORT` | No | Local bind address and port; defaults to `127.0.0.1:5000` |
| `DATABASE_URL` | No | Optional database override; the default SQLite file is created under `instance/` |
| `GEMINI_API_KEY` | No | Enables backend-only Gemini interpretation and planning |
| `GEMINI_INTERPRETER_MODEL`, `GEMINI_PLANNER_MODEL` | No | Override the two default Gemini model IDs |
| `GEMINI_TIMEOUT_SECONDS` | No | Provider request timeout |
| `GEMINI_RATE_LIMIT_COOLDOWN_SECONDS` | No | Local cooldown after a provider quota response |
| `GEMINI_REQUEST_LOG_DIR` | No | Request-audit directory, resolved relative to the repository root when not absolute |

Generate a public-mode `SECRET_KEY` without relying on a machine-specific value:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste the generated value after `SECRET_KEY=` in the local `.env`. Never paste it into `.env.example`, source files, screenshots, issues, or commits.

## Install on iPhone without a Mac

Before public access, ensure the project-root `.env` contains a unique `SECRET_KEY` of at least 32 characters. Never commit `.env`. Cloudflared 2026.7.2 was used during verification. Rename the Windows download to `cloudflared.exe`, place it in any dedicated folder, and add that folder to `PATH`.

Windows steps:

1. Activate the virtual environment:

   ```powershell
   & ".\.venv\Scripts\Activate.ps1"
   ```

2. Install requirements:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Install cloudflared for Windows, rename the downloaded executable to `cloudflared.exe`, and add its folder to `PATH`. Reopen PowerShell after changing `PATH`.
4. Verify the command:

   ```powershell
   cloudflared --version
   ```

5. In the first PowerShell terminal, start the secure public server:

   ```powershell
   python serve_public.py
   ```

6. In a second PowerShell terminal, start the temporary tunnel:

   ```powershell
   cloudflared tunnel --url http://localhost:5000
   ```

   If cloudflared reports an `[::1]` connection refusal or a 502, use the server's explicit IPv4 loopback address instead:

   ```powershell
   cloudflared tunnel --url http://127.0.0.1:5000
   ```

7. Copy the generated HTTPS `trycloudflare.com` address.
8. Open that HTTPS address in Safari on the iPhone.
9. Log in and verify the application works.
10. Tap Safari's Share button.
11. Select **Add to Home Screen**.
12. Enable **Open as Web App** if the option is available.
13. Tap **Add**.
14. Launch e& Care from its new Home Screen icon.

The optional helper performs the server and tunnel checks in one terminal while keeping cloudflared's standard URL output visible:

```powershell
.\start_iphone_pwa.ps1
```

The helper requires the repository virtual environment to be active and `cloudflared` to be in `PATH`. It starts Waitress hidden on `127.0.0.1`, runs the Quick Tunnel in the current terminal, and stops the server when the script exits.

Keep the Windows computer, `serve_public.py`, and cloudflared running while using the installed application. A Quick Tunnel address changes whenever the tunnel restarts. If it changes, the existing Home Screen icon may still target the old address and may need to be removed and added again. A permanent address requires a deployed backend or a persistent configured tunnel.

This is an installable PWA, not a native IPA. It does not require a Mac, Xcode, an Apple Developer account, or seven-day re-signing. The temporary URL is reachable from the internet while cloudflared runs, so share it only with intended testers and stop the tunnel when finished.

## Database commands and portability

Apply the seed definitions manually at any time:

```bash
python -m flask --app run.py seed-data
```

Inspect aggregate Smart History usage or clear only that table:

```bash
python -m flask --app run.py smart-history-stats
python -m flask --app run.py clear-smart-history --confirm
```

`clear-smart-history` refuses to run without `--confirm`. Startup, seeding, logout, account reset, and saved-recommendation reset do not clear the shared history.

To rebuild all local data, stop the server, delete `instance/prototype.db`, and run `python run.py` again. This is destructive to that machine's local records; normal startup and `seed-data` preserve existing unrelated records.

Do not commit `prototype.db`. Portability comes from the tracked models, schema upgrade, and seed definitions—not from sharing one developer's database file. Each team member receives an independent, reproducible local database after cloning and launching the application.

## Repository safety and portability audit

The distributable repository is intentionally separated from each developer's machine:

- `.env`, `.env.*`, `.venv/`, `instance/`, API request logs, and SQLite/database extensions are ignored. Only the blank `.env.example` template is tracked.
- The current tracked tree and reachable Git history were scanned for Google, GitHub, and AWS key shapes, private-key markers, local usernames, and Windows/macOS/Linux user-home paths. No credential-shaped value or developer-specific path was found.
- Configuration loads `.env` from the repository root regardless of the terminal's current directory. Relative Gemini request-log folders are also rooted there rather than in a developer-specific working directory.
- Empty or copied example values do not enable Gemini or become a stable Flask signing secret. Local mode safely generates a temporary secret; public mode refuses to start until a unique stable secret is supplied.
- The database, schema upgrades, seed definitions, templates, JavaScript, CSS, images, PWA icons, and Python dependencies required to run the application are tracked. A fresh clone generates only its own ignored runtime data.
- `tests/test_portability.py` protects the blank secret template, required ignore rules, relative path resolution, and common credential/user-path patterns in distributable text files.

The Gemini key remains backend-only. It is not rendered into HTML or JavaScript, returned by an API, written into request logs, or required by automated tests. When publishing changes, stage intended source files explicitly and confirm `git status` before committing.

## Tests

Install the browser once per environment:

```bash
python -m playwright install chromium
```

Run the complete suite:

```bash
python -m pytest -q
```

Useful focused commands:

```bash
python -m pytest -q tests --ignore=tests/browser
python -m pytest -q tests/browser
python -m pytest -q tests/test_pwa.py tests/test_public_server.py
python -m pytest -q tests/browser/test_pwa.py
```

Automated tests never make a real Gemini request. They use an empty key for deterministic fallback or inject controlled structured responses.

The roaming and mobile regression coverage specifically checks:

- exact usage scaling, package facts, multi-package scheduling, temporal segments, and deterministic fallback;
- two-model routing, high thinking, omitted sampling overrides, request logging, continuation IDs, quota cooldown, and Smart History call avoidance;
- explicit and comparative refinements, preservation of untouched allowances, sequential changes against the latest plan, one-question clarification, and original/previous navigation;
- prefix country search, one-row country layout, list-only destination scrolling, a visible **Continue** button, and absence of horizontal overflow;
- reachable Phone/Expanded preview controls, stable iPhone keyboard behavior, directional transitions across every workflow, and reduced-motion behavior;
- six-month Usage History, carrier acknowledgement, masked activation controls, saved recommendations, logout clearing, and repeatable end-to-end journeys.

GitHub Actions runs the same Pytest suite on Windows and Linux using Python 3.11 and 3.14. GitHub sends a workflow notification when any job in that operating-system/version matrix fails; the tests live in this repository under `tests/`, while GitHub only provides the clean runner that executes them after a push.

## Known boundaries

- Saved roaming recommendations are intentionally session-only and clear on logout or data reset.
- SQLite is appropriate for local team use; a shared deployment would require a managed database and migrations.
- Gemini quality and latency depend on the configured account, quota, and network. Backend validation and fallback keep the workflow usable without it.
- The offline page reports connectivity only; account data and workflows require the Windows server and tunnel.
- Automated Chromium checks cover installation metadata, service-worker scope, offline privacy, safe-area geometry, and mobile layout. Final Add to Home Screen behavior and standalone session persistence must still be confirmed on the physical iPhone.
- Quick Tunnel addresses are temporary; use a configured tunnel or hosted backend for a stable Home Screen address.
- Diagnostic readings, document extraction, billing-system changes, complaint routing, package activation, and outbound support actions are local workflow representations rather than connected operator services.
