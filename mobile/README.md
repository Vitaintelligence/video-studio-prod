# AdCut mobile

Flutter client for the hosted AdCut/OpenMontage backend.

## Run on a phone

Copy `dart_defines.example.json` to `dart_defines.local.json`, fill in the development token, then run:

```powershell
flutter run --dart-define-from-file=dart_defines.local.json
```

`dart_defines.local.json` is gitignored. Never commit the development bearer token or any provider/storage keys. The production backend URL is also the app's built-in default, so only `API_TOKEN` is required for the current development authentication mode.

The app talks only to the REST API described in `../README.md`. Provider credentials stay in the Railway worker and are never shipped to the phone.
