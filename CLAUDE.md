# AdCut — Create monorepo

AI video editing for UGC / short-form / performance content. "Record messy. We'll clean it." Then: "Tell AI what to change." Then: "Create variants to test."

## Structure
- `backend/` — FastAPI API + Celery worker + vendored OpenMontage (Python). Owns all provider credentials.
- `mobile/` — Flutter iOS-first client (`mobile/lib`). Talks only to the backend REST API.

## Product hierarchy (do not invert)
1. Nav is `Home · [Camera] · Projects`. Camera is the dominant center action. Account/settings = avatar, top right. No other root tabs.
2. Primary loop: Record → stop → upload → automatic clean → Result → Use this cut. No prompt, no questions in between.
3. Prompt-to-Edit only appears behind **Adjust** on the result. Versions are preserved (V1, V2...).
4. Home is intent-first ("What are you making today?"): Record & Clean, Upload & Clean, then "Do more" (only backend-supported: Ad Variants; Video to Clips stays hidden until the backend reports it).
5. UI speaks intents, never engine words. `core/intents/edit_intent.dart` is the only place that maps an intent to backend instructions. No pipeline names, model IDs or provider names in widgets.
6. Never fabricate: no fake progress/percentages, credits, scores, projects or results. Time saved = real raw duration − real result duration, otherwise not shown.

## Mobile commands (run in `mobile/`)
- `flutter pub get` · `dart format .` · `flutter analyze` · `flutter test` — all clean before any milestone commit
- Run: `flutter run --dart-define=API_BASE_URL=<url> --dart-define=API_TOKEN=<dev token>`
- Goldens (design review): `flutter test --update-goldens test/goldens`

## Backend URL and auth
- Base URL lives ONLY in `lib/core/api/api_config.dart` (`API_BASE_URL`, default = Railway production). Never hardcode elsewhere.
- Auth = backend dev bearer token via `--dart-define=API_TOKEN` (development stand-in; never ship a release with a master token).
- The client never contains provider/infra secrets (OpenRouter, Anthropic, MiniMax, R2, DATABASE_URL, Redis).
- Endpoints are those in `backend/server/api/routes/`. Do not invent routes; adapt the client.

## Architecture (`mobile/lib`)
- `core/api` HTTP client, typed `ApiException`, `AdCutApi`. `core/models` typed DTOs. `core/intents` domain intents. `core/design` tokens + theme. `core/widgets` shared components.
- `features/<name>/` = screens + Riverpod controllers (`flutter_riverpod`). Widgets never call the API or build JSON. No global mutable singletons.
- Hardware/IO behind interfaces so they are testable: `CameraGateway`, `FootagePicker`, `ExportService`.
- Navigation: `go_router`, paths in `app/routes.dart`. Onboarding runs once (redirect on `onboarding.done`).
- Backend is source of truth; only onboarding answers, default platform/format, and raw-recording length per edit are stored locally.
- Features are gated by `GET /v1/capabilities`. Unsupported = hidden or explicitly unavailable.
- POSTs that create work carry an `Idempotency-Key` created once per user action, reused on retry.
- Polling stops on terminal state and on dispose. Camera/video controllers are disposed with their screens; uploads stream from disk.

## UI rules
- Dark-first, one flat accent. NO gradients, glows, sparkle icons, emoji, decorative blur. Tokens only (no raw hex, magic paddings/radii/sizes).
- Radii 8/12/16 (+18 media, 24 sheet). Pills only for tiny tags. Spacing 4/8/12/16/20/24/32/40/48.
- Buttons: `PrimaryButton` (solid brand), `SecondaryButton` (solid surface), `TertiaryButton` (text), `DangerButton`. One primary per screen. No outlined buttons; surfaces have no borders.
- Selectors are real: `AppSelector` (bottom sheet), `SegmentedChoice`. Never fake a dropdown.
- Cupertino icons only. Tap targets >= 44pt. Text >= 12pt, respects text scaling. Status never by color alone.
- Every network view has loading / empty / error+retry with plain-language copy. Never show status codes, tracebacks, provider or path names.

## Quality gates
`dart format .`, `flutter analyze`, `flutter test` clean. No `print`, no TODOs standing in for features, no dead or commented-out code.
