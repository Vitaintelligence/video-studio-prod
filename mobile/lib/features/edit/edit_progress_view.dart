import 'package:flutter/cupertino.dart';
import 'package:go_router/go_router.dart';

import '../../app/routes.dart';
import '../../core/design/app_colors.dart';
import '../../core/design/app_radius.dart';
import '../../core/design/app_spacing.dart';
import '../../core/design/app_typography.dart';
import '../../core/models/api_models.dart';
import '../../core/widgets/buttons.dart';
import '../../core/widgets/state_views.dart';
import '../../core/widgets/step_list.dart';
import 'edit_controller.dart';

const _steps = ['Understanding footage', 'Finding strongest moments', 'Building your edit', 'Finalizing'];

/// Position of the backend's current stage in [_steps]; -1 before work starts.
int stageIndex(String? displayStage) => switch (displayStage) {
  'Understanding footage' => 0,
  'Finding strongest moments' => 1,
  'Building your edit' || 'Adding captions' || 'Adding B-roll' => 2,
  'Finalizing' => 3,
  _ => -1,
};

/// Shown until the first version is ready. Stages come from the backend; no invented percentages.
class EditProgressView extends StatelessWidget {
  const EditProgressView({super.key, required this.state, required this.controller});

  final EditState state;
  final EditController controller;

  Future<void> _confirmCancel(BuildContext context) async {
    final confirmed = await showCupertinoDialog<bool>(
      context: context,
      builder: (dialogContext) => CupertinoAlertDialog(
        title: const Text('Cancel this cut?'),
        content: const Text('The work done so far will be discarded.'),
        actions: [
          CupertinoDialogAction(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Keep going'),
          ),
          CupertinoDialogAction(
            isDestructiveAction: true,
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Cancel cut'),
          ),
        ],
      ),
    );
    if (confirmed == true) controller.cancel();
  }

  @override
  Widget build(BuildContext context) {
    final job = state.job!;

    if (job.status == EditStatus.failed) {
      return MessageView(
        icon: CupertinoIcons.exclamationmark_circle,
        title: "We couldn't finish this cut",
        message: job.error?.message.isNotEmpty == true ? job.error!.message : 'Try again with a new recording.',
        actionLabel: 'Record again',
        onAction: () => context.pushReplacement(Routes.camera),
        secondaryLabel: 'Back home',
        onSecondary: () => context.go(Routes.home),
      );
    }
    if (job.status == EditStatus.cancelled) {
      return MessageView(
        icon: CupertinoIcons.minus_circle,
        title: 'Cut cancelled',
        message: 'Nothing was produced. You can record or upload again any time.',
        actionLabel: 'Back home',
        onAction: () => context.go(Routes.home),
      );
    }

    final waiting = job.status == EditStatus.queued;
    final cancelling = job.status == EditStatus.cancelRequested;
    final current = stageIndex(job.displayStage);
    final steps = [
      for (var i = 0; i < _steps.length; i++)
        (
          _steps[i],
          waiting || current < 0
              ? StepStatus.pending
              : i < current
              ? StepStatus.done
              : i == current
              ? StepStatus.active
              : StepStatus.pending,
        ),
    ];

    return ListView(
      padding: const EdgeInsets.all(AppSpacing.gutter),
      children: [
        if (state.isReconnecting) ...[
          const Text('Reconnecting…', style: AppTypography.caption),
          const SizedBox(height: AppSpacing.xs),
        ],
        const Text('Cleaning your recording', style: AppTypography.display),
        const SizedBox(height: AppSpacing.sm),
        Semantics(
          liveRegion: true,
          child: Text(
            cancelling
                ? 'Cancelling…'
                : waiting
                ? 'Waiting to start'
                : (job.displayStage ?? 'Getting started'),
            style: AppTypography.bodySecondary,
          ),
        ),
        const SizedBox(height: AppSpacing.xl),
        DecoratedBox(
          decoration: const BoxDecoration(color: AppColors.surface, borderRadius: AppRadius.mediumAll),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: AppSpacing.xs),
            child: StepList(steps: steps),
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        const Text('You can leave. We will keep working.', style: AppTypography.bodySecondary),
        const SizedBox(height: AppSpacing.xl),
        SecondaryButton(
          label: 'Cancel',
          isLoading: state.isCancelling,
          onPressed: cancelling ? null : () => _confirmCancel(context),
        ),
      ],
    );
  }
}
