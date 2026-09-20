import 'package:flutter/material.dart';

import 'app_colors.dart';
import 'app_radius.dart';
import 'app_typography.dart';

abstract final class AppTheme {
  static ThemeData get dark {
    const scheme = ColorScheme.dark(
      primary: AppColors.accent,
      onPrimary: AppColors.onAccent,
      surface: AppColors.surface,
      onSurface: AppColors.textPrimary,
      error: AppColors.destructive,
      onError: AppColors.onDestructive,
    );
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: scheme,
      scaffoldBackgroundColor: AppColors.background,
      canvasColor: AppColors.background,
      splashFactory: NoSplash.splashFactory,
      highlightColor: Colors.transparent,
      dividerColor: AppColors.divider,
      textTheme: const TextTheme(
        displayLarge: AppTypography.display,
        headlineMedium: AppTypography.title,
        titleMedium: AppTypography.heading,
        bodyLarge: AppTypography.body,
        bodyMedium: AppTypography.bodySecondary,
        labelLarge: AppTypography.label,
        bodySmall: AppTypography.caption,
      ),
      pageTransitionsTheme: const PageTransitionsTheme(
        builders: {
          TargetPlatform.iOS: CupertinoPageTransitionsBuilder(),
          TargetPlatform.android: CupertinoPageTransitionsBuilder(),
          TargetPlatform.macOS: CupertinoPageTransitionsBuilder(),
        },
      ),
      textSelectionTheme: const TextSelectionThemeData(
        cursorColor: AppColors.accentText,
        selectionColor: AppColors.surfacePressed,
      ),
      snackBarTheme: const SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        backgroundColor: AppColors.surfacePressed,
        contentTextStyle: AppTypography.body,
        shape: RoundedRectangleBorder(borderRadius: AppRadius.mediumAll),
      ),
    );
  }
}
