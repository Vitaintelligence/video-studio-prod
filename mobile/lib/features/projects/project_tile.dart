import 'package:flutter/cupertino.dart';

import '../../core/design/app_colors.dart';
import '../../core/design/app_radius.dart';
import '../../core/design/app_spacing.dart';
import '../../core/design/app_typography.dart';
import '../../core/format.dart';
import '../../core/models/api_models.dart';
import '../../core/widgets/remote_thumbnail.dart';
import '../../core/widgets/status_tag.dart';

/// A project row: thumbnail, name, status, last update and duration when known.
class ProjectTile extends StatelessWidget {
  const ProjectTile({super.key, required this.project, required this.onTap});

  final ApiProject project;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final edit = project.latestEdit;
    final details = [
      Format.relativeTime(project.updatedAt),
      if (edit?.durationSeconds != null) Format.duration(edit!.durationSeconds!),
    ].join(' · ');
    return Semantics(
      button: true,
      label: '${project.name}. ${edit?.status.name ?? ''}. $details',
      excludeSemantics: true,
      onTap: onTap,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onTap,
        child: DecoratedBox(
          decoration: const BoxDecoration(color: AppColors.surface, borderRadius: AppRadius.mediumAll),
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.sm),
            child: Row(
              children: [
                RemoteThumbnail(url: edit?.thumbnailUrl, width: 56, height: 72),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(project.name, style: AppTypography.label, maxLines: 2, overflow: TextOverflow.ellipsis),
                      const SizedBox(height: AppSpacing.xxs),
                      Text(details, style: AppTypography.caption, maxLines: 1, overflow: TextOverflow.ellipsis),
                      if (edit != null) ...[const SizedBox(height: AppSpacing.xs), StatusTag(status: edit.status)],
                    ],
                  ),
                ),
                const Icon(CupertinoIcons.chevron_right, size: 16, color: AppColors.textMuted),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
