import 'package:flutter/material.dart';

import '../design/app_colors.dart';
import '../design/app_radius.dart';
import '../design/app_spacing.dart';
import '../design/app_typography.dart';

/// iOS-style bottom sheet with a grabber and title, used for option pickers.
Future<T?> showAppSheet<T>(BuildContext context, {required String title, required WidgetBuilder builder}) {
  return showModalBottomSheet<T>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    backgroundColor: AppColors.surface,
    barrierColor: AppColors.scrim,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.sheet))),
    builder: (context) => SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(AppSpacing.md, AppSpacing.sm, AppSpacing.md, AppSpacing.md),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Center(
              child: Container(
                width: 36,
                height: 4,
                decoration: const BoxDecoration(color: AppColors.surfacePressed, borderRadius: AppRadius.pillAll),
              ),
            ),
            const SizedBox(height: AppSpacing.md),
            Semantics(header: true, child: Text(title, style: AppTypography.heading)),
            const SizedBox(height: AppSpacing.sm),
            Flexible(child: builder(context)),
          ],
        ),
      ),
    ),
  );
}
