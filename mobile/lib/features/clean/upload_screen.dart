import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/routes.dart';
import '../../core/design/app_spacing.dart';
import '../../core/design/app_typography.dart';
import '../../core/format.dart';
import '../../core/widgets/app_progress_bar.dart';
import '../../core/widgets/buttons.dart';
import '../../core/widgets/screen_header.dart';
import '../../core/widgets/state_views.dart';
import 'clean_controller.dart';

/// Shown right after a recording/pick: real upload progress, then straight into the job.
class UploadScreen extends ConsumerWidget {
  const UploadScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(cleanControllerProvider);
    final controller = ref.read(cleanControllerProvider.notifier);

    ref.listen(cleanControllerProvider.select((s) => s.editId), (_, id) {
      if (id != null) {
        controller.reset();
        context.pushReplacement(Routes.edit(id));
      }
    });

    final Widget body;
    if (state.phase == CleanPhase.failed) {
      body = MessageView(
        icon: CupertinoIcons.exclamationmark_circle,
        title: state.error?.code == 'INVALID_MEDIA' ? "This video can't be used" : "We couldn't start your cut",
        message: state.error?.userMessage ?? 'Please try again.',
        actionLabel: state.error?.code == 'INVALID_MEDIA' ? null : 'Try again',
        onAction: controller.retry,
        secondaryLabel: 'Discard',
        onSecondary: () {
          controller.cancel();
          context.go(Routes.home);
        },
      );
    } else if (state.phase == CleanPhase.idle) {
      body = MessageView(
        title: 'Nothing to clean',
        message: 'Record or upload a video to get started.',
        actionLabel: 'Back home',
        onAction: () => context.go(Routes.home),
      );
    } else {
      final uploading = state.phase == CleanPhase.uploading;
      final size = state.footage?.sizeBytes ?? 0;
      body = ListView(
        padding: const EdgeInsets.all(AppSpacing.gutter),
        children: [
          const Text('Uploading your video', style: AppTypography.display),
          const SizedBox(height: AppSpacing.sm),
          const Text('Your cut starts as soon as the upload finishes.', style: AppTypography.bodySecondary),
          const SizedBox(height: AppSpacing.xl),
          AppProgressBar(value: uploading ? state.progress : null, semanticLabel: 'Upload progress'),
          const SizedBox(height: AppSpacing.xs),
          Semantics(
            liveRegion: true,
            child: Text(
              uploading
                  ? '${Format.bytes((size * state.progress).round())} of ${Format.bytes(size)}'
                  : 'Starting your cut',
              style: AppTypography.caption,
            ),
          ),
          const SizedBox(height: AppSpacing.xl),
          if (uploading)
            SecondaryButton(
              label: 'Cancel',
              onPressed: () {
                controller.cancel();
                context.go(Routes.home);
              },
            ),
        ],
      );
    }

    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            ScreenHeader(title: 'Upload', onBack: () => context.go(Routes.home)),
            Expanded(child: body),
          ],
        ),
      ),
    );
  }
}
