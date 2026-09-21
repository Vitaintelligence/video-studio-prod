import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../app/routes.dart';
import '../../core/api/api_exception.dart';
import '../../core/design/app_colors.dart';
import '../../core/design/app_spacing.dart';
import '../../core/design/app_typography.dart';
import '../../core/format.dart';
import '../../core/widgets/app_selector.dart';
import '../../core/widgets/app_sheet.dart';
import '../../core/widgets/buttons.dart';
import '../clean/clean_controller.dart';
import '../settings/ad_options.dart';
import 'edit_controller.dart';
import 'export_service.dart';
import 'video_result_player.dart';

/// The payoff: the finished cut, what it saved, and one clear next step.
class ResultView extends ConsumerStatefulWidget {
  const ResultView({
    super.key,
    required this.editId,
    required this.state,
    required this.controller,
    required this.onAdjust,
  });

  final String editId;
  final EditState state;
  final EditController controller;
  final VoidCallback onAdjust;

  @override
  ConsumerState<ResultView> createState() => _ResultViewState();
}

class _ResultViewState extends ConsumerState<ResultView> {
  bool _exporting = false;
  bool _showRaw = false;

  Future<void> _useCut(String url, int version) async {
    if (_exporting) return;
    final target = await showAppSheet<ExportTarget>(
      context,
      title: 'Use this cut',
      builder: (sheetContext) => Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          _ExportRow(
            icon: CupertinoIcons.photo,
            label: 'Save to Photos',
            onTap: () => Navigator.of(sheetContext).pop(ExportTarget.photos),
          ),
          _ExportRow(
            icon: CupertinoIcons.share,
            label: 'Share…',
            onTap: () => Navigator.of(sheetContext).pop(ExportTarget.share),
          ),
        ],
      ),
    );
    if (target == null || !mounted) return;
    setState(() => _exporting = true);
    try {
      await ref.read(exportServiceProvider).export(url: url, fileName: 'adcut-v$version.mp4', target: target);
      if (mounted && target == ExportTarget.photos) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Saved to Photos')));
      }
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.userMessage)));
    } on Object {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(const ApiException(code: 'EXPORT_FAILED', message: '').userMessage),
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _exporting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = widget.state;
    final shown = state.shownVersion!;
    final job = state.job!;
    final caps = ref.watch(capabilitiesProvider).value;
    final raw = ref.watch(rawSecondsProvider(widget.editId));
    final result = job.durationSeconds;
    final done = state.completedVersions;
    final parts = AdFormat.fromId(job.aspectRatio).id.split(':');
    final ratio = double.parse(parts[0]) / double.parse(parts[1]);
    final rawPath = ref.watch(rawPathProvider(widget.editId));
    final saved = raw != null && result != null ? Format.saved(raw, result) : null;

    return Column(
      children: [
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(AppSpacing.gutter, 0, AppSpacing.gutter, AppSpacing.xl),
            children: [
              const Text('Your cut is ready', style: AppTypography.display),
              const SizedBox(height: AppSpacing.md),
              if (result != null)
                Semantics(
                  container: true,
                  label: raw != null
                      ? 'Raw ${Format.duration(raw)}, ready ${Format.duration(result)}${saved != null ? ', $saved' : ''}'
                      : 'Ready ${Format.duration(result)}',
                  excludeSemantics: true,
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.baseline,
                    textBaseline: TextBaseline.alphabetic,
                    children: [
                      if (raw != null) ...[
                        Text(Format.duration(raw), style: AppTypography.title.copyWith(color: AppColors.textMuted)),
                        const SizedBox(width: AppSpacing.xs),
                        const Icon(CupertinoIcons.arrow_right, size: 18, color: AppColors.textSecondary),
                        const SizedBox(width: AppSpacing.xs),
                      ],
                      Text(Format.duration(result), style: AppTypography.title),
                      if (saved != null) ...[
                        const SizedBox(width: AppSpacing.sm),
                        Text(saved, style: AppTypography.label.copyWith(color: AppColors.success)),
                      ],
                    ],
                  ),
                ),
              const SizedBox(height: AppSpacing.md),
              if (rawPath != null) ...[
                SegmentedChoice<bool>(
                  label: 'Video',
                  value: _showRaw,
                  choices: const [
                    Choice(value: false, label: 'Cut'),
                    Choice(value: true, label: 'Raw'),
                  ],
                  onChanged: (v) => setState(() => _showRaw = v),
                ),
                const SizedBox(height: AppSpacing.xs),
              ],
              VideoResultPlayer(source: _showRaw && rawPath != null ? rawPath : shown.outputUrl!, aspectRatio: ratio),
              if (done.length > 1) ...[
                const SizedBox(height: AppSpacing.sm),
                AppSelector<String>(
                  label: 'Version',
                  value: shown.id,
                  choices: [for (final v in done) Choice(value: v.id, label: 'Version ${v.version}')],
                  onChanged: widget.controller.selectVersion,
                ),
              ],
            ],
          ),
        ),
        DecoratedBox(
          decoration: const BoxDecoration(
            color: AppColors.background,
            border: Border(top: BorderSide(color: AppColors.divider)),
          ),
          child: SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.all(AppSpacing.gutter),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  PrimaryButton(
                    label: 'Use this cut',
                    leadingIcon: CupertinoIcons.share,
                    isLoading: _exporting,
                    onPressed: () => _useCut(shown.outputUrl!, shown.version),
                  ),
                  if ((caps?.revisions ?? false) || (caps?.variants ?? false)) ...[
                    const SizedBox(height: AppSpacing.xs),
                    Row(
                      children: [
                        if (caps?.revisions ?? false)
                          Expanded(
                            child: SecondaryButton(label: 'Adjust', onPressed: widget.onAdjust),
                          ),
                        if ((caps?.revisions ?? false) && (caps?.variants ?? false))
                          const SizedBox(width: AppSpacing.xs),
                        if (caps?.variants ?? false)
                          Expanded(
                            child: SecondaryButton(
                              label: 'Create variants',
                              onPressed: () => context.push(Routes.variants(widget.editId)),
                            ),
                          ),
                      ],
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _ExportRow extends StatelessWidget {
  const _ExportRow({required this.icon, required this.label, required this.onTap});

  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Semantics(
    button: true,
    label: label,
    excludeSemantics: true,
    onTap: onTap,
    child: GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onTap,
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 56),
        child: Row(
          children: [
            Icon(icon, size: 22, color: AppColors.textSecondary),
            const SizedBox(width: AppSpacing.sm),
            Expanded(child: Text(label, style: AppTypography.body)),
          ],
        ),
      ),
    ),
  );
}
