# RUCAI Frontend Notes

## Current UI Scope
- Single-page interface served at `/`.
- Login with `AUTH_PASSWORD` via `/auth/login`.
- Set/read active course.
- Upload one or multiple `.pdf`/`.docx` files.
- Choose per-file scan mode on upload: `Digitaliseret` or `Håndscannet`.
- Automatic ingest job polling after upload.
- Automatic language detection (`da`/`en`/`unknown`) during ingest.
- Chat with source-backed answers.

## UX Decisions
- Removed manual "Check Job" button.
- Upload section now supports selecting multiple files in one action.
- Upload section exposes scan-mode selectors per selected file.
- Job states are shown inline per uploaded file until completion.
- Chat source display is reduced to short previews with optional full-text expansion.

## Known Limitations
- No persistent chat history yet.
- No document management page (list/delete/re-ingest) yet.
- Styling is intentionally lightweight and API-centric.

## Next Frontend Steps
1. Add left sidebar: course docs + ingestion states.
2. Add chat history with thread persistence.
3. Add citation click-through to source snippets.
4. Add explicit error banner for auth/session expiry.
5. Add responsive mobile layout improvements.
