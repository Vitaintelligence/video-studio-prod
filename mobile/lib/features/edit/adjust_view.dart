import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/design/app_colors.dart';
import '../../core/design/app_radius.dart';
import '../../core/design/app_spacing.dart';
import '../../core/design/app_typography.dart';
import '../../core/models/api_models.dart';
import '../../core/widgets/app_progress_bar.dart';
import '../../core/widgets/app_selector.dart';
import '../../core/widgets/buttons.dart';
import '../../core/widgets/prompt_field.dart';
import '../settings/ad_options.dart';
import 'edit_controller.dart';
import 'video_result_player.dart';

class _SuggestionText {
  const _SuggestionText(this.label, this.text);
  final String label;
  final String text;
}

/// Suggestions the backend's edit planner understands. Tapping one fills the composer.
const _suggestions = [
  _SuggestionText('Shorter', 'Make it shorter and tighter.'),
  _SuggestionText('Stronger hook', 'Make the opening faster and punchier.'),
  _SuggestionText('Remove more pauses', 'Remove more awkward pauses.'),
  _SuggestionText('Add captions', 'Add bold captions.'),
];

/// Adjust: the player, a compact version selector, and Prompt-to-Edit. Each instruction makes a new version.
class AdjustView extends ConsumerStatefulWidget {
  const AdjustView({super.key, required this.editId, required this.state, required this.controller});

  final String editId;
  final EditState state;
  final EditController controller;

  @override
  ConsumerState<AdjustView> createState() => _AdjustViewState();
}

class _AdjustViewState extends ConsumerState<AdjustView> {
  final TextEditingController _instruction = TextEditingController();

  @override
  void dispose() {
    _instruction.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    FocusScope.of(context).unfocus();
    final ok = await widget.controller.sendInstruction(_instruction.text);
    if (ok) _instruction.clear();
  }

  void _addSuggestion(String text) {
    final current = _instruction.text.trim();
    final next = current.isEmpty ? text : '$current $text';
    _instruction.value = TextEditingValue(
      text: next,
      selection: TextSelection.collapsed(offset: next.length),
    );
    setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final state = widget.state;
    final shown = state.shownVersion!;
    final job = state.job!;
    final capabilities = ref.watch(capabilitiesProvider).value;
    final canRevise = capabilities?.revisions ?? false;
    final done = state.completedVersions;
    final active = state.activeVersion;
    final failed = state.latestFailedVersion;
    final aspect = AdFormat.fromId(job.aspectRatio);
    final parts = aspect.id.split(':');
    final ratio = double.parse(parts[0]) / double.parse(parts[1]);
    final latestDone = done.last;

    return Column(
      children: [
        Expanded(
          child: ListView(
            keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
            padding: const EdgeInsets.fromLTRB(AppSpacing.gutter, 0, AppSpacing.gutter, AppSpacing.xl),
            children: [
              const Text('Ask AI to change anything', style: AppTypography.title),
              const SizedBox(height: AppSpacing.sm),
              VideoResultPlayer(url: shown.outputUrl!, aspectRatio: ratio),
              const SizedBox(height: AppSpacing.sm),
              Semantics(
                liveRegion: true,
                child: Text(
                  done.length > 1
                      ? 'Version ${shown.version}${shown.id == latestDone.id ? ' · latest' : ''}'
                      : 'Version ${shown.version}',
                  style: AppTypography.label,
                ),
              ),
              const SizedBox(height: AppSpacing.xxs),
              Text(shown.instruction, style: AppTypography.caption, maxLines: 3, overflow: TextOverflow.ellipsis),
              if (done.length > 1) ...[
                const SizedBox(height: AppSpacing.sm),
                AppSelector<String>(
                  label: 'Version',
                  value: shown.id,
                  choices: [for (final v in done) Choice(value: v.id, label: 'Version ${v.version}')],
                  onChanged: widget.controller.selectVersion,
                ),
              ],
              if (active != null) ...[
                const SizedBox(height: AppSpacing.md),
                _RevisionProgress(
                  version: active,
                  job: job,
                  onCancel: widget.controller.cancel,
                  isCancelling: state.isCancelling,
                ),
              ] else if (failed != null) ...[
                const SizedBox(height: AppSpacing.md),
                _Notice(
                  icon: CupertinoIcons.exclamationmark_circle_fill,
                  message: failed.status == EditStatus.cancelled
                      ? 'That change was cancelled. Version ${latestDone.version} is unchanged.'
                      : "We couldn't apply that change. Version ${latestDone.version} is unchanged.",
                ),
              ],
              if (state.instructionError != null) ...[
                const SizedBox(height: AppSpacing.md),
                _Notice(icon: CupertinoIcons.exclamationmark_circle_fill, message: state.instructionError!.userMessage),
              ],
              const SizedBox(height: AppSpacing.lg),
              if (canRevise) ...[
                const SizedBox(height: AppSpacing.xl),
                const Text('Suggestions', style: AppTypography.caption),
                const SizedBox(height: AppSpacing.xxs),
                Wrap(
                  spacing: AppSpacing.xs,
                  children: [
                    for (final q in _suggestions) _Suggestion(label: q.label, onTap: () => _addSuggestion(q.text)),
                    if (capabilities?.aiBroll ?? false)
                      _Suggestion(
                        label: 'Add B-roll',
                        onTap: () => _addSuggestion('Generate a b-roll shot of the product.'),
                      ),
                  ],
                ),
              ],
            ],
          ),
        ),
        if (canRevise)
          _ComposerBar(
            controller: _instruction,
            busy: state.isSendingInstruction,
            locked: state.isProcessing,
            onChanged: (_) => setState(() {}),
            onSend: _instruction.text.trim().length >= 4 ? _send : null,
          ),
      ],
    );
  }
}

class _RevisionProgress extends StatelessWidget {
  const _RevisionProgress({
    required this.version,
    required this.job,
    required this.onCancel,
    required this.isCancelling,
  });

  final EditRevision version;
  final EditJob job;
  final VoidCallback onCancel;
  final bool isCancelling;

  @override
  Widget build(BuildContext context) {
    final stage = job.id == version.id ? job.displayStage : null;
    final label = job.status == EditStatus.cancelRequested
        ? 'Cancelling…'
        : version.status == EditStatus.queued
        ? 'Version ${version.version} is waiting to start'
        : 'Version ${version.version}: ${stage ?? 'Applying your changes'}';
    return DecoratedBox(
      decoration: const BoxDecoration(color: AppColors.surface, borderRadius: AppRadius.mediumAll),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Semantics(liveRegion: true, child: Text(label, style: AppTypography.label)),
            const SizedBox(height: AppSpacing.xs),
            AppProgressBar(
              value: version.status == EditStatus.queued || version.progress <= 0 ? null : version.progress / 100,
              semanticLabel: 'Revision progress',
            ),
            const SizedBox(height: AppSpacing.xxs),
            Row(
              children: [
                const Expanded(
                  child: Text('You can leave this screen. Your edit will continue.', style: AppTypography.caption),
                ),
                TertiaryButton(label: 'Cancel', onPressed: isCancelling ? null : onCancel),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _Notice extends StatelessWidget {
  const _Notice({required this.icon, required this.message});

  final IconData icon;
  final String message;

  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: const BoxDecoration(color: AppColors.surface, borderRadius: AppRadius.mediumAll),
    child: Padding(
      padding: const EdgeInsets.all(AppSpacing.md),
      child: Row(
        children: [
          Icon(icon, size: 20, color: AppColors.warning),
          const SizedBox(width: AppSpacing.sm),
          Expanded(child: Text(message, style: AppTypography.body)),
        ],
      ),
    ),
  );
}

class _Suggestion extends StatelessWidget {
  const _Suggestion({required this.label, required this.onTap});

  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Semantics(
    button: true,
    label: 'Add suggestion: $label',
    excludeSemantics: true,
    onTap: onTap,
    child: GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onTap,
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: AppSpacing.minTap),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.xxs),
          child: DecoratedBox(
            decoration: const BoxDecoration(color: AppColors.surfaceRaised, borderRadius: AppRadius.pillAll),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm, vertical: AppSpacing.xs),
              child: Text(label, style: AppTypography.caption.copyWith(color: AppColors.textPrimary)),
            ),
          ),
        ),
      ),
    ),
  );
}

/// Pinned prompt-to-edit input with an inline send action.
class _ComposerBar extends StatelessWidget {
  const _ComposerBar({
    required this.controller,
    required this.busy,
    required this.locked,
    required this.onChanged,
    required this.onSend,
  });

  final TextEditingController controller;
  final bool busy;
  final bool locked;
  final ValueChanged<String> onChanged;
  final VoidCallback? onSend;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: const BoxDecoration(
        color: AppColors.background,
        border: Border(top: BorderSide(color: AppColors.divider)),
      ),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.sm),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Expanded(
                child: PromptField(
                  controller: controller,
                  onChanged: onChanged,
                  enabled: !busy,
                  minLines: 1,
                  maxLines: 4,
                  semanticLabel: 'Instruction to change this edit',
                  hint: locked ? 'Wait for the current change to finish' : 'Ask AI to change this edit...',
                ),
              ),
              const SizedBox(width: AppSpacing.xs),
              SizedBox(
                width: 96,
                child: PrimaryButton(label: 'Update', isLoading: busy, onPressed: locked ? null : onSend),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
