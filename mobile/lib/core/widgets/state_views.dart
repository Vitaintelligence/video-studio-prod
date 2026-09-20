import 'package:flutter/cupertino.dart';

import '../design/app_colors.dart';
import '../design/app_spacing.dart';
import '../design/app_typography.dart';
import 'buttons.dart';

/// Centered activity indicator for first loads.
class LoadingView extends StatelessWidget {
  const LoadingView({super.key, this.label});

  final String? label;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Semantics(
        label: label ?? 'Loading',
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const CupertinoActivityIndicator(radius: 12),
            if (label != null) ...[
              const SizedBox(height: AppSpacing.sm),
              Text(label!, style: AppTypography.bodySecondary),
            ],
          ],
        ),
      ),
    );
  }
}

/// Message state with optional actions. Used for empty and error states.
class MessageView extends StatelessWidget {
  const MessageView({
    super.key,
    required this.title,
    required this.message,
    this.icon,
    this.actionLabel,
    this.onAction,
    this.secondaryLabel,
    this.onSecondary,
  });

  final String title;
  final String message;
  final IconData? icon;
  final String? actionLabel;
  final VoidCallback? onAction;
  final String? secondaryLabel;
  final VoidCallback? onSecondary;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(AppSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (icon != null) ...[
              Icon(icon, size: 32, color: AppColors.textSecondary),
              const SizedBox(height: AppSpacing.md),
            ],
            Text(title, style: AppTypography.heading, textAlign: TextAlign.center),
            const SizedBox(height: AppSpacing.xs),
            Text(message, style: AppTypography.bodySecondary, textAlign: TextAlign.center),
            if (actionLabel != null && onAction != null) ...[
              const SizedBox(height: AppSpacing.lg),
              PrimaryButton(label: actionLabel!, onPressed: onAction, expand: false),
            ],
            if (secondaryLabel != null && onSecondary != null) ...[
              const SizedBox(height: AppSpacing.xs),
              TertiaryButton(label: secondaryLabel!, onPressed: onSecondary),
            ],
          ],
        ),
      ),
    );
  }
}
