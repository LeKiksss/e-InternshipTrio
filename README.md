# e& Customer Service UI

A portable Flask application that presents customer-service workflows in a polished, mobile-first interface. It runs locally in a virtual phone frame on desktop and switches to a full-screen responsive layout on smaller devices.

The repository includes working authentication, a local SQLite data layer, Network & Bill Intelligence, Complaint Intelligence, Profile management, and a data-driven Roaming Recommender. The roaming workflow combines deterministic Python analysis with optional Gemini reasoning and strict backend validation.

## How it was built

The application uses a Flask application factory with separate authentication and application blueprints. Jinja renders the page shell, while modular vanilla JavaScript controls navigation, loading states, workflow restoration, chat refinements, and session-only saved recommendations. Custom CSS provides the design system, phone frame, responsive layouts, and animation.

SQLAlchemy owns all persistent records. The application creates `instance/prototype.db` automatically, performs an idempotent SQLite schema upgrade, and applies repeatable seed definitions at startup. Passwords are hashed with Argon2.

The Roaming Recommender follows this pipeline:

```text
Authenticated user
  -> six raw monthly usage rows from SQLite
  -> per-metric outlier and trend analysis
  -> recency-weighted monthly profile
  -> inclusive trip scaling with no added usage margin
  -> all 42 active packages
  -> Gemini structured decision when configured
  -> Python package, arithmetic, allowance, segment, and coverage validation
  -> one Gemini correction attempt if required
  -> bounded deterministic optimizer when Gemini is unavailable or invalid
  -> validated single, repeated, mixed, or segmented package plan
```

## Technology stack

| Layer | Technology | Responsibility |
|---|---|---|
| Backend | Python 3.11+, Flask | Application factory, routes, sessions, validation, and orchestration |
| Data | SQLite, Flask-SQLAlchemy | Users, monthly usage, package catalogue, bills, diagnostics, and complaints |
| Authentication | Flask-Login, Flask-WTF, Argon2 | Protected routes, CSRF protection, sessions, and password hashing |
| Recommendation reasoning | Google Gen AI SDK, Pydantic | Optional Gemini 3.5 Flash structured package-plan decisions |
| Frontend | Jinja2, vanilla JavaScript | Rendered shell, workflow state, API integration, and interactions |
| Styling | Custom CSS and inline SVG | Responsive phone presentation, design tokens, states, and motion |
| Testing | Pytest, Playwright | Unit, integration, security, API, and browser journeys |

Python 3.11 and newer are supported. Python 3.14.2 is suitable; the GitHub Actions workflow covers Python 3.11 and 3.14 on Windows and Linux.

## What is functional and what remains local

| Area | Implemented | Integration boundary |
|---|---|---|
| Authentication | Registration, duplicate checks, login, logout, remembered sessions, Argon2 hashes, CSRF | Password-recovery delivery does not send email or SMS |
| Database | Automatic creation, safe additive upgrade, idempotent seed data, persistent customer activity | Each clone has its own ignored local SQLite file |
| Network | Diagnostic workflow, results, local history, coverage layers, location choice | Measurements and map layers use deterministic local values |
| Bills | Upload/manual journeys, draft restoration, editable fields, charts, anomalies, plan review | Files are not sent to OCR or billing systems |
| Complaints | Chat and form paths, summary, database ticket creation, tracking, notes, closure | No external CRM or human-agent system is connected |
| Roaming | Usage analysis, 42-package catalogue, Gemini reasoning, deterministic fallback, plan sequences, refinements, session saves | Package activation and dialer actions do not change a live account |
| Profile | Persisted profile and preference edits, links to account activity | Email remains read-only in this application |

Gemini is the only optional external service. When configured, the backend sends anonymous user ID, trip context, raw usage measurements, calculated requirements, conversation context, and the active package catalogue. It does not send email, phone number, password, password hash, cookies, or authentication tokens.

## Main product areas

- **Home** — three equally prominent service widgets, account snapshot, alerts, notifications, help, and reviewable UI states.
- **Network & Bill** — network diagnostics and history, coverage visualization, bill upload/manual entry, charge analysis, anomalies, and plan review.
- **Complaints** — guided chat, structured form, attachment state, generated summary, ticket submission, ticket timeline, notes, and history.
- **Roaming** — searchable destinations, date validation, automatic usage-based recommendation, natural-language adjustments, package sequences, temporal segments, activation order, and saved plans.
- **Profile** — customer details, masked phone number, notification preferences, contact preference, activity links, help, and logout.

## Database structure

The runtime database is `instance/prototype.db`. Both `instance/` and database file extensions are ignored by Git. A fresh clone does not need a copied database because `python run.py` creates and seeds one automatically.

| Table/model | Responsibility |
|---|---|
| `User` | Identity, contact information, Argon2 password hash, and preferences |
| `UserMonthlyUsage` | One raw usage row per user/month for data, local minutes, international minutes, and SMS |
| `RoamingPackage` | Complete package facts, including code, family, duration, price, allowances, activation code, and stacking flags |
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
- Package requirements use the calculated trip estimate directly, without an added safety margin.
- The UI and package validator use the same values shown under “Your Average Usage in X Days.”

`app/services/user_requirement_parser.py` extracts explicit GB, local/international/general minutes, SMS, price, validity, zero-use requests, comparative requests, and temporal phrases. Newer conflicting input replaces older input, while unrelated explicit constraints remain active.

`app/services/package_fallback_optimizer.py` uses a bounded, canonicalized search rather than uncontrolled brute force. It can select one package, repeat a package, mix families, produce exact-duration combinations, and optimize each requested trip segment independently.

`app/services/recommendation_validator.py` reloads every package fact from SQLite and recalculates all totals. Gemini-supplied price, allowance, validity, activation code, or arithmetic is never trusted.

## Gemini configuration

Gemini is called only by the Flask backend. The API key is never included in JavaScript, templates, API responses, or logs.

1. Copy `.env.example` to `.env` if `.env` is not already present.
2. Open the project-root `.env` file.
3. Insert the key after `GEMINI_API_KEY=`.

```dotenv
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.5-flash
GEMINI_REQUEST_LOG_DIR=instance/api_request_logs
```

The exact local path in this repository is:

```text
UI POC/.env
```

`.env` is ignored by Git. If the key is absent, times out, reaches a quota limit, or returns an unusable response, the application continues through the deterministic optimizer.

The Gemini service uses:

- `google-genai`, not the deprecated `google-generativeai` package
- Pydantic JSON schema output
- High thinking level with Gemini's default sampling configuration
- The complete active package catalogue
- One validation-guided correction attempt
- Backend-only error handling with no raw model response exposed to the browser

Every outbound Gemini attempt is saved as a separate JSON file in
`instance/api_request_logs/`. This includes initial recommendations, refinements, and validation
corrections. Each file contains the model, system instruction, input context, generation settings,
response schema, and timeout sent for that call. API keys and model responses are not written.
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

## Project structure

```text
UI POC/
|-- app/
|   |-- __init__.py                 Application factory, extensions, schema setup, seed command
|   |-- extensions.py               SQLAlchemy, Flask-Login, and CSRF instances
|   |-- models.py                   Persistent database models and serializers
|   |-- schema_upgrade.py           Safe additive SQLite package-table upgrade
|   |-- seed_data.py                Idempotent users, usage history, packages, and account activity
|   |-- auth/
|   |   |-- forms.py                Login and registration validation
|   |   `-- routes.py               Registration, login, logout, password-recovery response
|   |-- main/
|   |   `-- routes.py               Authenticated pages and JSON API routes
|   |-- services/
|   |   |-- usage_analysis.py       Outliers, trends, recency weighting, and trip scaling
|   |   |-- user_requirement_parser.py  Numeric, comparative, and temporal chat parsing
|   |   |-- gemini_recommender.py   Backend structured Gemini request/response models
|   |   |-- recommendation_validator.py Package facts, coverage, totals, segments, constraints
|   |   |-- package_fallback_optimizer.py Bounded deterministic package-plan search
|   |   |-- roaming_recommendation.py End-to-end recommendation orchestration
|   |   |-- mock_diagnostics.py     Deterministic network result values
|   |   |-- mock_bill_analysis.py   Bill anomaly and plan-review calculations
|   |   `-- mock_complaints.py      Complaint classification and routing rules
|   |-- templates/
|   |   |-- base.html               Virtual phone and desktop preview controls
|   |   |-- auth/                   Login and registration views
|   |   `-- app/shell.html          Authenticated screens, sheets, dialogs, and navigation
|   `-- static/
|       |-- css/                    Design system, authentication, and phone-frame styles
|       `-- js/                     Shared UI plus network, bill, complaint, roaming, and state modules
|-- tests/
|   |-- conftest.py                 In-memory application/database fixtures
|   |-- test_seed_data.py           Seed counts, constraints, hashes, preservation, idempotency
|   |-- test_usage_analysis.py      Reference weights, outliers, MAD fallback, trend protection
|   |-- test_trip_requirements.py   Inclusive dates and exact trip-duration scaling
|   |-- test_requirement_parser.py  Numeric, comparative, latest-input, and segment parsing
|   |-- test_package_plans.py       Optimizer, factual validation, scheduling, and segments
|   |-- test_gemini_recommender.py  Structured requests, correction retry, errors, and fallback
|   |-- test_refinement_behavior.py Explicit and comparative refinement enforcement
|   |-- test_roaming_api.py         Authentication, current-user isolation, APIs, and saved plans
|   `-- browser/                    Playwright end-to-end customer journeys and console audit
|-- instance/                       Local runtime database and backups; created and ignored
|-- .github/workflows/tests.yml     Windows/Linux CI matrix for Python 3.11 and 3.14
|-- config.py                       Environment-based application configuration
|-- run.py                          Local development entry point
|-- requirements.txt               Pinned Python dependencies
|-- .env.example                    Safe environment-variable template
`-- .gitignore                      Local secrets, databases, environments, caches, and IDE files
```

## Local setup

From the repository root:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run.py
```

macOS or Linux:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
python run.py
```

Open:

```text
http://127.0.0.1:5000
```

No Node.js, npm, CDN, or frontend build process is required.

## Database commands and portability

Apply the seed definitions manually at any time:

```bash
python -m flask --app run.py seed-data
```

To rebuild all local data, stop the server, delete `instance/prototype.db`, and run `python run.py` again. This is destructive to that machine's local records; normal startup and `seed-data` preserve existing unrelated records.

Do not commit `prototype.db`. Portability comes from the tracked models, schema upgrade, and seed definitions—not from sharing one developer's database file. Each team member receives an independent, reproducible local database after cloning and launching the application.

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
```

Automated tests never make a real Gemini request. They use an empty key for deterministic fallback or inject controlled structured responses.

## Known boundaries

- Saved roaming recommendations are intentionally session-only and clear on logout or data reset.
- SQLite is appropriate for local team use; a shared deployment would require a managed database and migrations.
- Gemini quality and latency depend on the configured account, quota, and network. Backend validation and fallback keep the workflow usable without it.
- Diagnostic readings, document extraction, billing-system changes, complaint routing, package activation, and outbound support actions are local workflow representations rather than connected operator services.
