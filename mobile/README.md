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

## Release build (Android)

Application ID: `com.vitaintelligence.adcut`. This is the Play Store's permanent identity for the app -
free to change up until the first real upload to Play Console, never after.

**Signing.** `android/app/build.gradle.kts` reads the release signing config from `android/key.properties`
(git-ignored - never commit it, see `android/key.properties.example` for the format). A release keystore
(`android/app/upload-keystore.jks`, also git-ignored, 2048-bit RSA, ~27 year validity) has already been
generated once. **Back up that `.jks` file and the passwords in `key.properties` somewhere durable (a
password manager, not this repo) before this machine's copy is the only one that exists** - losing it
means the app can never be updated again under this Play Store listing. Without `key.properties` present,
release builds silently fall back to the debug key (fine for local testing, never for Play Store or real
testers).

To generate a fresh keystore instead of reusing the existing one:

```powershell
keytool -genkeypair -v -keystore android/app/upload-keystore.jks `
  -keyalg RSA -keysize 2048 -validity 10000 -alias adcut-upload
```

(Modern `keytool` defaults to PKCS12, which requires the store and key passwords to match - use the same
value for both `storePassword` and `keyPassword` in `key.properties`.)

**Build.** Release builds are minified and resource-shrunk (`isMinifyEnabled` / `isShrinkResources`,
`android/app/proguard-rules.pro`) - materially smaller and harder to reverse-engineer than a debug build.

```powershell
flutter build appbundle --release   # Play Store upload format (.aab)
flutter build apk --release         # direct-install / sideload testing (.apk)
```

Never pass `--dart-define=API_TOKEN` on a release build - the production backend runs
`AUTH_MODE=device_session`, so the app needs no bearer token baked in at all. See the "Run on a phone"
section above: `API_TOKEN` is a *development-only* stand-in for a local backend running the older
`dev_token` auth mode.

**App icon.** See `assets/icon/README.md` - drop the logo there and run `dart run flutter_launcher_icons`
to regenerate every platform's icon files in one step.
