import 'package:flutter/cupertino.dart';

import '../design/app_colors.dart';
import '../design/app_radius.dart';
import '../design/app_spacing.dart';
import '../design/app_typography.dart';
import '../models/api_models.dart';

/// Small status tag. Status is always conveyed by icon and text, never color alone.
class StatusTag extends StatelessWidget {
  const StatusTag({super.key, required this.status});

  final EditStatus status;

  @override
  Widget build(BuildContext context) {
    final (label, icon, color) = switch (status) {
      EditStatus.completed => ('Ready', CupertinoIcons.checkmark_circle_fill, AppColors.success),
      EditStatus.failed => ('Failed', CupertinoIcons.exclamationmark_circle_fill, AppColors.destructive),
      EditStatus.cancelled => ('Cancelled', CupertinoIcons.minus_circle_fill, AppColors.textSecondary),
      EditStatus.cancelRequested => ('Cancelling', CupertinoIcons.clock_fill, AppColors.textSecondary),
      EditStatus.queued => ('Queued', CupertinoIcons.clock_fill, AppColors.warning),
      EditStatus.starting || EditStatus.running => ('Editing', CupertinoIcons.time_solid, AppColors.accentText),
    };
    return DecoratedBox(
      decoration: const BoxDecoration(color: AppColors.surfaceRaised, borderRadius: AppRadius.pillAll),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xs, vertical: AppSpacing.xxs),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 14, color: color),
            const SizedBox(width: AppSpacing.xxs),
            Text(label, style: AppTypography.caption.copyWith(color: AppColors.textPrimary)),
          ],
        ),
      ),
    );
  }
}
