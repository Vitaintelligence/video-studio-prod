import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/design/app_colors.dart';
import '../core/design/app_radius.dart';
import '../core/design/app_spacing.dart';
import '../core/design/app_typography.dart';
import '../features/clean/clean_controller.dart';
import '../features/projects/projects_controller.dart';
import 'routes.dart';

/// Shows on every top-level screen while a video is uploading or being cleaned, and reopens it on tap.
/// Driven only by real state: the in-progress upload, or a project the backend reports as running.
class ActiveWorkBar extends ConsumerWidget {
  const ActiveWorkBar({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final clean = ref.watch(cleanControllerProvider);
    final projects = ref.watch(projectsProvider).value ?? const [];
    final running = projects.where((p) => p.latestEdit?.status.isActive ?? false).firstOrNull;

    final String label;
    final String route;
    if (clean.isBusy) {
      label = 'Uploading your video';
      route = Routes.upload;
    } else if (running != null) {
      label = 'Cleaning your video';
      route = Routes.edit(running.latestEdit!.id);
    } else {
      return const SizedBox.shrink();
    }

    return Padding(
      padding: const EdgeInsets.fromLTRB(AppSpacing.gutter, 0, AppSpacing.gutter, AppSpacing.xs),
      child: Semantics(
        button: true,
        label: '$label. Tap to view.',
        excludeSemantics: true,
        onTap: () => context.push(route),
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: () => context.push(route),
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: AppSpacing.minTap + AppSpacing.xs),
            child: DecoratedBox(
              decoration: const BoxDecoration(color: AppColors.surfaceRaised, borderRadius: AppRadius.mediumAll),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
                child: Row(
                  children: [
                    const CupertinoActivityIndicator(radius: 9),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(child: Text(label, style: AppTypography.label)),
                    const Text('View', style: AppTypography.caption),
                    const SizedBox(width: AppSpacing.xxs),
                    const Icon(CupertinoIcons.chevron_right, size: 14, color: AppColors.textMuted),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
