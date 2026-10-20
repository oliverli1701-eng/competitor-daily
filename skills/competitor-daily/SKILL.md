---
name: competitor-daily
description: Import a college's recognized competition list, configure its branding and user-owned research credentials, and generate source-backed local HTML/PDF competition briefings. Use for building or updating a personal competition daily from PDF, DOCX, spreadsheet, or structured catalogs.
---

# Competitor Daily · 竞赛日报机

Turn the user's own competition catalog into a branded daily briefing. Keep each user's catalog, credentials, state and reports in an independent workspace. The installed skill is the program distribution, not the user's data directory.

## Start with the workspace

Use Python 3.11+. Run the bundled launcher `scripts/competitor_daily.py` by its absolute path; pass `--root` with the user's chosen workspace on every call. Never default to the author's production directory, credentials or university. Run `--help` for exact command flags and `doctor` to check dependencies and configuration. If dependencies are missing, use a user-local virtual environment and install the bundled `runtime/requirements.txt`; use that environment's Python for later calls.

For a new workspace:

```text
python scripts/competitor_daily.py --root /path/to/my-daily init --university "你的大学" --college "你的学院"
python scripts/competitor_daily.py --root /path/to/my-daily import-catalog /path/to/competition-list.pdf
```

The `init` command creates editable `config/profile.json`. University, college, report title and visual accent belong there; use the same branding for HTML and PDF. Preserve an existing user's edits.

## Import and confirm the catalog

Read [catalog-import.md](references/catalog-import.md) when importing a new list or resolving document extraction problems. Compare the extracted draft against the original: competition names, recognition levels and duplicate entries. Ask the user only about material ambiguities or missing information. Do not silently replace the list with an example university's catalog. A scanned PDF requires the Agent's available OCR/document capability; the program does not claim to recognize images itself.

When the draft has been checked and material ambiguities are resolved, call `confirm-catalog`. Do not require an extra user approval for an unambiguous transcription; preserve any explicit user review preference. Keep the original file and extraction provenance inside the user's workspace; do not publish it by default.

## Choose research and generate

Use the user's chosen research route:

- **Their DeepSeek API:** the user saves `DEEPSEEK_API_KEY` in the workspace `.env`. Never request a key in chat, print it, or copy credentials from an existing installation. The optional direct search/analysis API uses the user's token and may incur their provider's charges. Check `doctor`, configure official sources using `sources --help`, then call `run`.
- **Their Agent's research tools:** use the Agent's available search/browser capability under the user's account, record the required source-backed research batch, then call `run --from-research` with that folder. Read [research-and-extension.md](references/research-and-extension.md) for the batch contract. This route avoids a separate DeepSeek key; the Agent's own provider may still charge for its tools and tokens.
- **Preview only:** call `demo` in a separate workspace. Clearly identify the generated page as a demonstration snapshot. Do not present sample dates or competitions as today's verified intelligence.

Research only the confirmed catalog. Prioritize official organizer pages and attachments. A search snippet is a lead, not evidence. Preserve source URLs and dates, distinguish original publication dates from current verification time, and omit unsupported fields from the public report. Do not invent deadlines, participation requirements, online formats or file submissions.

Generated briefings cover new registrations, important updates, approaching deadlines and ongoing competitions. These sections may overlap; never add their counts and call the result a unique competition total. PDF and HTML should come from the same report data. Open the generated HTML and link the PDF when available; report any actual extraction or coverage limitation without filling cards with unknown-value placeholders.

## Extend only as needed

Read [research-and-extension.md](references/research-and-extension.md) when adding official sources, using an Agent-supplied research batch, or extending document/provider support. Read [scheduling.md](references/scheduling.md) only when the user asks for automatic updates or deployment. Installing this skill does not itself create schedules, publish files, open a repository or grant access to the author's server.
