# Applied on top of Android's default proguard-android-optimize.txt for release builds
# (isMinifyEnabled/isShrinkResources in build.gradle.kts).
#
# Flutter's own plugin AARs (camera, video_player, gal, image_picker, share_plus, file_picker, ...) each ship
# their own consumer ProGuard rules, which R8 merges in automatically - no per-plugin keep rules needed here.
# This app has no reflection-based JSON/serialization (api_models.dart parses JSON by hand), so there is
# nothing else Dart-side that R8 could break.

# Standard safety net: never strip a class purely because it declares a native (JNI) method - required for
# any plugin bridging to native code, and a no-op otherwise.
-keepclasseswithmembernames class * {
    native <methods>;
}

# Keep annotations: several AndroidX/plugin libraries inspect these at runtime.
-keepattributes *Annotation*
-keepattributes Signature
