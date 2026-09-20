import 'package:flutter/painting.dart';

/// Semantic color tokens for AdCut's dark, creator-focused visual language.
/// Feature code never uses raw colors.
abstract final class AppColors {
  static const Color background = Color(0xFF08090E);
  static const Color surface = Color(0xFF11141C);
  static const Color surfaceRaised = Color(0xFF181D29);
  static const Color surfacePressed = Color(0xFF22293A);
  static const Color divider = Color(0xFF2A3142);
  static const Color surfaceBorder = Color(0xFF252B3A);

  static const Color textPrimary = Color(0xFFF7F8FC);
  static const Color textSecondary = Color(0xFFAAB1C0);
  static const Color textMuted = Color(0xFF747D91);

  static const Color accent = Color(0xFF765CF6);
  static const Color accentPressed = Color(0xFF6449DC);
  static const Color onAccent = Color(0xFFFFFFFF);
  static const Color onAccentMuted = Color(0xFFDCD5FF);
  static const Color accentText = Color(0xFFB9AAFF);
  static const Color accentSecondary = Color(0xFF24D2B3);
  static const Color accentSoft = Color(0xFF211C3C);
  static const Color accentDisabled = Color(0xFF242938);

  static const Color success = Color(0xFF40D48A);
  static const Color warning = Color(0xFFF2B84B);
  static const Color destructive = Color(0xFFFF526F);
  static const Color destructivePressed = Color(0xFFE34460);
  static const Color onDestructive = Color(0xFFFFFFFF);

  static const Color scrim = Color(0xB3000000);
  static const Color videoBackdrop = Color(0xFF000000);

  static const LinearGradient brandGradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFF8468FF), Color(0xFF5D5CEB), Color(0xFF3879E9)],
  );

  static const LinearGradient brandGlow = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0x33765CF6), Color(0x0024D2B3)],
  );
}
