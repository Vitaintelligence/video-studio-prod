# AdCut mobile

Flutter client for the hosted AdCut/OpenMontage backend.

## Run on a phone

The production API URL is built in. A fresh install creates an anonymous,
server-signed device session automatically, so the production app does not need
a shared API token:

```powershell
flutter run
```

For a local backend that still uses `AUTH_MODE=dev_token`, copy
`dart_defines.example.json` to `dart_defines.local.json`, fill in the local
development token, then run:

```powershell
flutter run --dart-define-from-file=dart_defines.local.json
```

`dart_defines.local.json` is gitignored. Never commit the development bearer
token or any provider/storage keys.

The app talks only to the REST API described in `../README.md`. Provider credentials stay in the Railway worker and are never shipped to the phone.
