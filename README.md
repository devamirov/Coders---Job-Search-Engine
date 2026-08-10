<p align="center">
  <img src="./assets/Coders---Job-Search-Engine-logo.png" width="180">
</p>

<h1 align="center">Spectre — Job Search Engine</h1>

**Type:** Web app (job search)  
**Stack:** Node.js, Python (Streamlit)  
**Live:** https://spectre.guru  

## Overview
Spectre is a remote job-search platform with AI-assisted tools, authentication, and email flows. This repository is the cleaned public source for the live Spectre product (formerly published as a partial “Coders Job Search Engine” snapshot).

## Setup
1. Copy `.env.example` → `.env` and fill in your own keys (never commit `.env`).
2. Install Node deps: `npm install`
3. Install Python deps if using the Streamlit/Robin UI: `pip install -r requirements.txt`
4. Follow `SETUP.md` for full deployment notes.

## Security
Secrets, databases, Google client JSON, and local env files are excluded from this public repo.
