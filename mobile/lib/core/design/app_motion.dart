import 'package:flutter/widgets.dart';

/// Shared motion language for onboarding, navigation, and other high-frequency interactions.
abstract final class AppMotion {
  static const Duration quick = Duration(milliseconds: 140);
  static const Duration standard = Duration(milliseconds: 240);
  static const Duration expressive = Duration(milliseconds: 420);
  static const Curve enter = Curves.easeOutCubic;
  static const Curve emphasis = Curves.easeOutBack;

  static Duration allowed(BuildContext context, Duration duration) =>
      (MediaQuery.maybeOf(context)?.disableAnimations ?? false) ? Duration.zero : duration;
}
