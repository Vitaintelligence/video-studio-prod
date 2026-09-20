import 'package:flutter/painting.dart';

/// Semantic color tokens. Dark-first, one flat accent. Feature code never uses raw colors.
abstract final class AppColors {
  static const Color background = Color(0xFF0B0C0F);
  static const Color surface = Color(0xFF13151A);
  static const Color surfaceRaised = Color(0xFF191C22);
  static const Color surfacePressed = Color(0xFF22262E);
  static const Color divider = Color(0xFF292D35);

  static const Color textPrimary = Color(0xFFF6F7F9);
  static const Color textSecondary = Color(0xFFA1A7B2);
  static const Color textMuted = Color(0xFF767D89);

  static const Color accent = Color(0xFF3D6BF2);
  static const Color accentPressed = Color(0xFF3560DB);
  static const Color onAccent = Color(0xFFFFFFFF);
  static const Color accentText = Color(0xFF8FA9FF);
  static const Color accentDisabled = Color(0xFF22262E);

  static const Color success = Color(0xFF3DBE6B);
  static const Color warning = Color(0xFFE8A93A);
  static const Color destructive = Color(0xFFE5534B);
  static const Color destructivePressed = Color(0xFFC4453E);
  static const Color onDestructive = Color(0xFFFFFFFF);

  static const Color scrim = Color(0xB3000000);
  static const Color videoBackdrop = Color(0xFF000000);
}
