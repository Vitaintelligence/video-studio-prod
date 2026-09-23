# App icon

Drop the logo here as `icon.png` (this exact filename - referenced by `flutter_launcher_icons` config
in `pubspec.yaml`):

- **1024x1024px**, PNG, square.
- Keep the actual mark within the inner ~66% of the canvas (roughly a 670px-diameter circle centered
  in the image). Android's adaptive icon system crops this image to a circle, squircle, rounded square
  or other shape depending on the device's launcher, so anything outside that safe zone can get clipped.
- A transparent background is fine for `icon.png` itself - it's also used as the adaptive icon's
  *foreground* layer, composited over `adaptive_icon_background` (set in `pubspec.yaml`, currently the
  app's dark background token) for Android 8+. Older Android and iOS use `icon.png` as-is, so avoid
  relying on transparency being visible: a version that also looks right flattened onto a solid dark
  background is safest.

Then generate every platform's actual icon files in one step:

```
flutter pub get
dart run flutter_launcher_icons
```

This writes the Android `mipmap-*/ic_launcher*.png` (incl. adaptive icon XML) and iOS `AppIcon.appiconset`
files directly - nothing else to place by hand. Re-run it any time `icon.png` changes.
