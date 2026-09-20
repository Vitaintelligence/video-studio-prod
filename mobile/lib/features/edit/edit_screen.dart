import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/routes.dart';
import '../../core/widgets/screen_header.dart';
import '../../core/widgets/state_views.dart';
import '../projects/projects_controller.dart';
import 'adjust_view.dart';
import 'edit_controller.dart';
import 'edit_progress_view.dart';
import 'result_view.dart';

/// One cut, end to end: live progress, then the result, and Adjust for Prompt-to-Edit.
/// Reopening a running or finished project lands here too.
class EditScreen extends ConsumerStatefulWidget {
  const EditScreen({super.key, required this.editId});

  final String editId;

  @override
  ConsumerState<EditScreen> createState() => _EditScreenState();
}

class _EditScreenState extends ConsumerState<EditScreen> {
  bool _adjusting = false;

  @override
  Widget build(BuildContext context) {
    final id = widget.editId;
    final state = ref.watch(editControllerProvider(id));
    final controller = ref.read(editControllerProvider(id).notifier);
    final job = state.job;

    // Keep the project list fresh once something settles.
    ref.listen(editControllerProvider(id).select((s) => s.isProcessing), (was, now) {
      if (was == true && !now) ref.invalidate(projectsProvider);
    });

    final Widget body;
    var title = '';
    VoidCallback? onBack;
    if (state.isLoading) {
      body = const LoadingView(label: 'Loading your cut');
    } else if (job == null) {
      body = MessageView(
        icon: CupertinoIcons.exclamationmark_circle,
        title: state.loadError?.code == 'NOT_FOUND' ? 'Cut not found' : "Couldn't load this cut",
        message: state.loadError?.userMessage ?? 'Please try again.',
        actionLabel: 'Try again',
        onAction: controller.retryLoad,
        secondaryLabel: 'Back home',
        onSecondary: () => context.go(Routes.home),
      );
    } else if (state.shownVersion != null && _adjusting) {
      title = 'Adjust';
      onBack = () => setState(() => _adjusting = false);
      body = AdjustView(editId: id, state: state, controller: controller);
    } else if (state.shownVersion != null) {
      body = ResultView(
        editId: id,
        state: state,
        controller: controller,
        onAdjust: () => setState(() => _adjusting = true),
      );
    } else {
      body = EditProgressView(state: state, controller: controller);
    }

    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            ScreenHeader(title: title, onBack: onBack),
            Expanded(child: body),
          ],
        ),
      ),
    );
  }
}
