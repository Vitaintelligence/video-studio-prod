import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/routes.dart';
import '../../core/design/app_spacing.dart';
import '../../core/design/app_typography.dart';
import '../../core/models/api_models.dart';
import '../../core/widgets/buttons.dart';
import '../../core/widgets/state_views.dart';
import 'project_tile.dart';
import 'projects_controller.dart';

/// Real projects from the backend, with loading, empty, error and pull-to-refresh states.
class ProjectsScreen extends ConsumerWidget {
  const ProjectsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final projects = ref.watch(projectsProvider);
    final controller = ref.read(projectsProvider.notifier);

    final Widget body = projects.when(
      skipLoadingOnReload: true,
      loading: () => const LoadingView(),
      error: (error, _) => MessageView(
        icon: CupertinoIcons.wifi_slash,
        title: "Couldn't load projects",
        message: 'Check your connection and try again.',
        actionLabel: 'Try again',
        onAction: () => ref.invalidate(projectsProvider),
      ),
      data: (items) {
        final visible = [
          for (final p in items)
            if (p.latestEdit != null) p,
        ];
        if (visible.isEmpty) {
          return MessageView(
            icon: CupertinoIcons.film,
            title: 'No projects yet',
            message: 'Upload your first UGC clip and tell AI how you want it edited.',
            actionLabel: 'Create an edit',
            onAction: () => context.go(Routes.home),
          );
        }
        return RefreshIndicator(
          onRefresh: controller.refresh,
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.fromLTRB(AppSpacing.gutter, 0, AppSpacing.gutter, AppSpacing.floatingBarOffset),
            children: [
              for (final (heading, group) in [
                (
                  'In progress',
                  [
                    for (final p in visible)
                      if (p.latestEdit!.status.isActive) p,
                  ],
                ),
                (
                  'Ready',
                  [
                    for (final p in visible)
                      if (p.latestEdit!.status == EditStatus.completed) p,
                  ],
                ),
                (
                  "Didn't finish",
                  [
                    for (final p in visible)
                      if (!p.latestEdit!.status.isActive && p.latestEdit!.status != EditStatus.completed) p,
                  ],
                ),
              ])
                if (group.isNotEmpty) ...[
                  Padding(
                    padding: const EdgeInsets.only(top: AppSpacing.sm, bottom: AppSpacing.xs),
                    child: Semantics(header: true, child: Text(heading, style: AppTypography.heading)),
                  ),
                  for (final p in group) ...[
                    ProjectTile(project: p, onTap: () => context.push(Routes.edit(p.latestEdit!.id))),
                    const SizedBox(height: AppSpacing.xs),
                  ],
                ],
            ],
          ),
        );
      },
    );

    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.only(left: AppSpacing.gutter),
              child: SizedBox(
                height: 56,
                child: Row(
                  children: [
                    const Expanded(child: Text('Projects', style: AppTypography.title)),
                    AppIconButton(
                      icon: CupertinoIcons.person_crop_circle,
                      label: 'Account',
                      onPressed: () => context.push(Routes.account),
                    ),
                  ],
                ),
              ),
            ),
            Expanded(child: body),
          ],
        ),
      ),
    );
  }
}
