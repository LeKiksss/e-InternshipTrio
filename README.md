# e& Customer Care UI Proof of Concept

> A locally hosted, mobile-first customer-service prototype for stakeholder demonstrations. All telecom data and commercial information are fictional and no live e& systems are connected.

## How the application was built

The project uses a Flask application factory with separate authentication and application blueprints. Flask renders the initial interface with Jinja templates, while modular vanilla JavaScript manages screen navigation, animations, modal sheets, and reusable workflow state. SQLAlchemy stores local prototype users and records in SQLite; short-lived drafts and saved roaming recommendations use the authenticated Flask session. Deterministic Python services provide repeatable demonstration results without calling external APIs.

```text
Browser UI
   |-- Jinja templates + custom CSS
   |-- Vanilla JavaScript workflows
   v
Flask routes and CSRF-protected forms
   |-- Deterministic mock services
   v
SQLAlchemy models -> local SQLite database
```

The interface is bundled entirely in the repository. It does not require React, Node.js, a frontend build process, a CDN, or an internet connection at runtime.

## Technology stack

| Layer | Technology | Responsibility |
| --- | --- | --- |
| Backend | Python 3.11+, Flask | Application factory, routes, sessions, and API endpoints |
| Templates | Jinja2 | Initial server-rendered pages and authenticated app shell |
| Database | SQLite, Flask-SQLAlchemy | Local users, bills, diagnostics, complaints, and roaming catalogue |
| Authentication | Flask-Login, Flask-WTF | Sessions, protected routes, form validation, and CSRF protection |
| Password security | `argon2-cffi` | Argon2 password hashing and verification |
| Frontend | Vanilla JavaScript | Navigation, workflow state, API calls, modals, and animations |
| Styling | Custom HTML/CSS/SVG | Responsive phone frame, design system, charts, map, and accessibility states |
| Testing | Pytest, Playwright | Unit/integration coverage plus end-to-end Chromium workflow checks |
| Configuration | `python-dotenv` | Optional local `.env` settings |

## Implemented functionality vs. simulation

This distinction is important when extracting code for another project.

| Area | Implemented locally | Demonstration placeholder |
| --- | --- | --- |
| Authentication | Registration, login, logout, remembered sessions, validation, Argon2 hashes, protected routes | Forgot-password message delivery is simulated |
| Database | SQLite creation, automatic seed data, and persisted user, bill, diagnostic, and complaint records | Seeded customer and telecom records are fictional |
| Dashboard | Responsive widgets, account snapshot, alerts, help, notifications, loading/error/empty states | Usage, plan, alerts, and notifications are seeded UI data |
| Network | Repeatable animated tests, controlled Back/Done/Run Another actions, optional location, saved history, deletion, map layers, and zoom | No real speed test, GPS lookup, network API, or map service |
| Bills | Repeatable upload/manual flows, preserved draft fields, saved bill records, charts, anomaly and recommendation UI | Uploaded-file metadata is retained for the draft; files, OCR, and analysis are simulated |
| Complaints | Repeatable guided chat and form flows, editable preserved answers, saved tickets, notes, timeline, and closing | Assistant classification uses local rules; no LLM or complaint-system integration |
| Roaming | Four-step flow, duration-scaled usage, comparative adjustments, session saves, duplicate protection, viewing, and removal | Packages, networks, prices, activation codes, and dialer actions are fictional |
| Profile | Persisted name, phone, notification preference, and contact-method edits | Demo plan and linked activity summaries are fictional |
| Presenter controls | Immediate switching between normal, loading, error, empty, and success states | State changes do not represent live service conditions |

## Main customer journeys

- **Network & Bill Intelligence** - diagnostic simulation, local history, fictional coverage map, bill entry, simulated parsing, spending chart, anomaly explanation, and plan recommendation.
- **Complaint Intelligence** - privacy consent, deterministic guided chat, structured-form fallback, preliminary diagnosis, local ticket creation, history, notes, and tracking timeline.
- **Roaming Package Advisor** - searchable destinations, validated travel dates, automatic current-usage recommendation, deterministic comparative adjustments, activation guidance, and session-only saved recommendations.
- **Shared experience** - account dashboard, profile, help, notifications, responsive phone/expanded modes, accessibility states, toasts, sheets, and presenter controls.

## Project structure and responsibilities

```text
app/
|-- __init__.py                 App factory, extension setup, database creation, seed data
|-- extensions.py               Shared SQLAlchemy, Flask-Login, and CSRF instances
|-- models.py                   User, package, ticket, diagnostic, and bill models
|
|-- auth/
|   |-- forms.py                Login and registration validation
|   `-- routes.py               Login, registration, forgot-password, and logout routes
|
|-- main/
|   `-- routes.py               App shell plus profile, bill, diagnostic, complaint, and roaming APIs
|
|-- services/
|   |-- mock_diagnostics.py     Deterministic strong and weak network results
|   |-- mock_bill_analysis.py   Bill anomaly and recommendation rules
|   |-- mock_complaints.py      Complaint category and routing rules
|   `-- mock_roaming.py         Package filtering and alternative-selection rules
|
|-- templates/
|   |-- base.html               Shared document, phone frame, preview controls, and asset loading
|   |-- auth/                   Login and create-account screens
|   `-- app/shell.html          Authenticated screens, sheets, forms, navigation, and SVG icons
|
`-- static/
    |-- css/
    |   |-- app.css             Main design system and authenticated application styling
    |   |-- auth.css            Authentication-screen styling
    |   `-- phone-frame.css     Desktop phone preview and expanded/mobile layouts
    `-- js/
        |-- app.js              Shared API helper, sheets, toasts, auth, profile, and map behavior
        |-- navigation.js       Screen, browser-history, and segmented-control navigation
        |-- workflow-state.js   Shared Back/Forward, draft persistence, reset, and restore controller
        |-- diagnostics.js      Speed-test phases, results, and diagnostic history
        |-- bills.js            Upload simulation, manual form, analysis, and plan modal
        |-- complaints.js       Chat, form, diagnosis, ticket submission, and tracking
        |-- roaming.js          Trip steps, scaled usage, adjustments, session saves, copy, and dialer
        `-- demo-controls.js    Presenter state switching and demo-data reset

tests/
|-- conftest.py                 Test app, database, client, and login fixtures
|-- browser/                    Real Chromium tests for repeatability, navigation, saves, and refresh
|-- test_auth.py                Registration, hashing, login, and logout tests
|-- test_models.py              Seed-data and roaming-catalogue tests
|-- test_roaming_service.py     Duration scaling and deterministic adjustment rules
`-- test_routes.py              Protected routes, session state, and workflow API tests

config.py                       Environment-aware development and test configuration
run.py                          Local application entry point and host/port handling
requirements.txt                Pinned Python dependencies
.env.example                    Safe local configuration template
.gitignore                      Excludes secrets, runtime data, environments, and caches
.gitattributes                  Cross-platform line-ending rules
.github/workflows/tests.yml     Python 3.11/3.14 tests on Windows and Linux
instance/                       Runtime SQLite data; created automatically and not committed
```

## Extracting modules for reuse

| If your team needs... | Start with... | Also required |
| --- | --- | --- |
| Authentication | `app/auth/`, authentication templates | `models.py`, `extensions.py`, `config.py` |
| Database models | `app/models.py` | `extensions.py` and the app-factory initialization |
| Network workflow | `diagnostics.js`, `mock_diagnostics.py` | Diagnostic routes and relevant `shell.html` markup/CSS |
| Bill workflow | `bills.js`, `mock_bill_analysis.py` | Bill model, routes, markup, and chart styles |
| Complaint workflow | `complaints.js`, `mock_complaints.py` | Ticket model, complaint routes, markup, and sheet styles |
| Roaming workflow | `roaming.js`, `mock_roaming.py` | Roaming package model, seed catalogue, route, and markup |
| Phone preview shell | `phone-frame.css`, `base.html` | Preview-switch handling in `app.js` |
| Shared UI system | `app.css`, shared SVG symbols in `shell.html` | Component markup and common behavior in `app.js` |

Each JavaScript workflow expects specific element IDs from `shell.html` and API paths from `main/routes.py`. When extracting a workflow, copy its JavaScript, related template section, styles, service, route, and model together.

## Quick start

Python 3.11 or newer is required. The project is verified on Python 3.11 and 3.14.2.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python run.py
```

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 run.py
```

Open <http://127.0.0.1:5000>.

### Demonstration account

| Field | Value |
| --- | --- |
| Name | `Prototype Demo User` |
| Email | `demo@prototype.local` |
| Phone | `+971501234567` |
| Password | `Demo123!` |

The password is stored only as an Argon2 hash. The login screen can fill the credentials but will not submit automatically.

## Configuration

Copy `.env.example` to `.env` for local overrides. The real `.env` is ignored by Git.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SECRET_KEY` | Random temporary value | Stable local session signing |
| `APP_HOST` | `127.0.0.1` | Server bind address |
| `APP_PORT` | `5000` | Local server port |
| `DATABASE_URL` | `instance/prototype.db` | Optional SQLAlchemy database override |

Keep `APP_HOST=127.0.0.1` unless access from another device is intentionally required.

## Database and reset

`instance/prototype.db` is created and seeded automatically on first launch. It contains a demo user, five fictional roaming packages, one bill, one diagnostic result, and one complaint ticket.

- In the UI: open **Demo states -> Reset demonstration data** while signed into the demo account.
- Full reset: stop the app, delete `instance/prototype.db`, then run `python run.py` again.

## Tests

```bash
python -m playwright install chromium
python -m pytest -q
```

The suite contains 37 tests: 34 unit/integration checks and three end-to-end Chromium journeys. It covers authentication, password hashing, route protection, seed data, workflow draft restoration, repeated requests, duration-scaled roaming usage, and session save/refresh/remove/logout behavior. GitHub Actions installs Chromium and runs the suite on Windows and Linux with Python 3.11 and 3.14.

## Repository notes

- Runtime assets are local; no CDN is required.
- `.env`, virtual environments, SQLite files, caches, logs, and IDE settings are excluded from Git.
- The repository does not include an open-source license. Add the appropriate license before making it public if redistribution should be permitted.
- This is a UI proof of concept, not a production telecom application.
