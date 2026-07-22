# e& Insights – Mobile App

A smart, insight-driven mobile experience built for e& UAE customers. This app gives users clear visibility into their network performance, breaks down monthly bills in plain English, and offers proactive customer support.

> **Current Branch:** UI-Hamzah  
> **Module Scope:** Home Dashboard, Network Diagnostics, & Bill Intelligence

---

## Features Included on This Branch

### 1. Smart Dashboard
* **Synthesized Account Status:** Gives an instant top-level account status (e.g., "Your account looks good") derived from live network and billing health.
* **Quick-Access Cards:** Fast access to Network & Bill insights, Open Complaint tracking, and Roaming Package planning.
* **Account Snapshot:** At-a-glance view of live monthly data usage, voice minutes, and next bill due dates.
* **Active Alerts Feed:** Real-time updates for planned area maintenance, bill spikes, and ticket status changes.

### 2. Network Diagnostics & Coverage Map
* **One-Tap Speed Test:** Measures download speed, upload speed, and latency in seconds.
* **Plain-English Verdicts:** Translates technical Mbps metrics into meaningful everyday context (e.g., "Excellent for video calls, streaming, gaming, and everyday browsing").
* **Interactive Coverage Map:** Features toggleable map layers for UAE baselines, personal speed test history, and community coverage heat maps.
* **Local Caching & GPS Tagging:** Stores speed test history locally with location tagging for historical tracking.

### 3. Bill Intelligence & Smart Recommendations
* **Category Breakdown:** Visual spend distribution across Data, Voice, Roaming, and Add-ons.
* **Anomaly Detection:** Automatically flags sudden bill increases (e.g., "Your bill is 28% higher than usual due to roaming charges").
* **Plan Recommendations:** Analyzes actual usage against current plan allowances to calculate unused waste or overage risks, suggesting better-fit plans (e.g., Smart Value 425) with direct e& Store switching links.

---

## Repository Structure

This repository is structured as a monorepo containing both the Flask backend API and the Flutter mobile frontend:

```text
e-InternshipTrio/
├── app/                  # Python / Flask Backend API
├── instance/             # SQLite database & local server configs
├── venv/                 # Python Virtual Environment (ignored in git)
│
└── e_insights/           # Flutter Mobile Application (UI-Hamzah Work)
    ├── lib/
    │   ├── main.dart
    │   ├── screens/      # Dashboard, Insights, & Bill screens
    │   ├── widgets/      # Status Cards, Gauges, & Map overlays
    │   └── models/       # Data models for Speed Tests & Bills
    └── pubspec.yaml      # Flutter dependencies