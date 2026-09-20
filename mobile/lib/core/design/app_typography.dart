import 'package:flutter/painting.dart';

import 'app_colors.dart';

/// Type scale: three weights (regular / semibold / bold). Sizes scale with the OS text size.
abstract final class AppTypography {
  static const TextStyle display = TextStyle(
    fontSize: 30,
    height: 1.1,
    fontWeight: FontWeight.w700,
    letterSpacing: -0.8,
    color: AppColors.textPrimary,
  );
  static const TextStyle title = TextStyle(
    fontSize: 24,
    height: 1.2,
    fontWeight: FontWeight.w700,
    letterSpacing: -0.5,
    color: AppColors.textPrimary,
  );
  static const TextStyle heading = TextStyle(
    fontSize: 18,
    height: 1.3,
    fontWeight: FontWeight.w600,
    color: AppColors.textPrimary,
  );
  static const TextStyle body = TextStyle(
    fontSize: 16,
    height: 1.4,
    fontWeight: FontWeight.w400,
    color: AppColors.textPrimary,
  );
  static const TextStyle bodySecondary = TextStyle(
    fontSize: 15,
    height: 1.4,
    fontWeight: FontWeight.w400,
    color: AppColors.textSecondary,
  );
  static const TextStyle label = TextStyle(
    fontSize: 15,
    height: 1.25,
    fontWeight: FontWeight.w600,
    color: AppColors.textPrimary,
  );
  static const TextStyle caption = TextStyle(
    fontSize: 13,
    height: 1.3,
    fontWeight: FontWeight.w400,
    color: AppColors.textSecondary,
  );
}
