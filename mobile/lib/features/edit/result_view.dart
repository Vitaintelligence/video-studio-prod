import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart' show ScaffoldMessenger, SnackBar;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../app/routes.dart';
import '../../core/api/api_exception.dart';
import '../../core/design/app_colors.dart';
import '../../core/design/app_motion.dart';
import '../../core/design/app_radius.dart';
import '../../core/design/app_spacing.dart';
import '../../core/design/app_typography.dart';
import '../../core/format.dart';
import '../../core/models/api_models.dart';
import '../../core/widgets/app_selector.dart';
import '../../core/widgets/buttons.dart';
import '../clean/clean_controller.dart';
import '../settings/ad_options.dart';
import 'cut_timeline.dart';
import 'edit_controller.dart';
import 'export_service.dart';
import 'video_result_player.dart';

/// The payoff: preview the finished cut, inspect every removal, restore footage, and export.
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
  ExportTarget? _activeExport;
  double? _exportProgress;
  bool _showRaw = false;
  CutRange? _selectedRemoved;

  Future<void> _export(String url, int version, ExportTarget target) async {
    if (_activeExport != null) return;
    setState(() {
      _activeExport = target;
      _exportProgress = 0;
    });
    try {
      await ref
          .read(exportServiceProvider)
          .export(
            url: url,
            fileName: 'adcut-v$version.mp4',
            target: target,
            onProgress: (progress) {
              if (mounted) setState(() => _exportProgress = progress.clamp(0, 1));
            },
          );
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
      if (mounted) {
        setState(() {
          _activeExport = null;
          _exportProgress = null;
        });
      }
    }
  }

  Future<void> _restore(CutRange range) async {
    final started = await widget.controller.restoreRange(range);
    if (!mounted) return;
    if (started) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Restoring clip in a new version')));
    } else if (widget.state.instructionError != null) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(widget.state.instructionError!.userMessage)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = widget.state;
    final shown = state.shownVersion!;
    final job = state.job!;
    final caps = ref.watch(capabilitiesProvider).value;
    final localRawSeconds = ref.watch(rawSecondsProvider(widget.editId));
    final sourceSeconds = (job.insights['source_seconds'] as num?)?.toDouble();
    final rawSeconds = localRawSeconds ?? sourceSeconds;
    final result = job.durationSeconds;
    final done = state.completedVersions;
    final parts = AdFormat.fromId(job.aspectRatio).id.split(':');
    final ratio = double.parse(parts[0]) / double.parse(parts[1]);
    final rawPath = ref.watch(rawPathProvider(widget.editId));
    final saved = rawSeconds != null && result != null ? Format.saved(rawSeconds, result) : null;
    final keptRanges = shown.keptRanges.isNotEmpty ? shown.keptRanges : job.keptRanges;
    final slices = rawSeconds == null ? const <CutSlice>[] : buildCutSlices(rawSeconds, keptRanges);
    final removed = slices.where((slice) => !slice.kept).map((slice) => slice.range).toList();
    // Insights describe the job returned by the API, not every entry in its version list.
    // Omit them while viewing another version rather than attributing the latest claims to it.
    final shownInsights = shown.id == job.id ? job.insights : const <String, Object>{};
    final hasChanges = removed.isNotEmpty || verifiedEditChanges(shownInsights).isNotEmpty;
    final selected = removed.any((range) => _sameRange(range, _selectedRemoved)) ? _selectedRemoved : null;
    final saving = _activeExport == ExportTarget.photos;
    final compactLabels = MediaQuery.textScalerOf(context).scale(1) > 1.2;
    final changeDuration = AppMotion.allowed(context, AppMotion.standard);

    return Column(
      children: [
        Expanded(
          child: ListView(
            padding: const EdgeInsets.only(bottom: AppSpacing.xl),
            children: [
              _Section(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const Text('Your cut is ready', style: AppTypography.display),
                    const SizedBox(height: AppSpacing.md),
                    if (result != null) _TimeSavedSummary(rawSeconds: rawSeconds, resultSeconds: result, saved: saved),
                    if (state.isProcessing) ...[const SizedBox(height: AppSpacing.sm), const _ProcessingNotice()],
                    if (rawPath != null) ...[
                      const SizedBox(height: AppSpacing.md),
                      SegmentedChoice<bool>(
                        label: 'Video',
                        value: _showRaw,
                        choices: const [
                          Choice(value: false, label: 'Cut'),
                          Choice(value: true, label: 'Raw'),
                        ],
                        onChanged: (value) => setState(() {
                          _showRaw = value;
                          _selectedRemoved = null;
                        }),
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(height: AppSpacing.sm),
              VideoResultPlayer(
                source: _showRaw && rawPath != null ? rawPath : shown.outputUrl!,
                aspectRatio: ratio,
                onDownload: _showRaw || _activeExport != null
                    ? null
                    : () => _export(shown.outputUrl!, shown.version, ExportTarget.photos),
                downloadProgress: saving ? _exportProgress : null,
              ),
              if (hasChanges) ...[
                const SizedBox(height: AppSpacing.lg),
                _Section(
                  child: AnimatedSwitcher(
                    duration: changeDuration,
                    switchInCurve: AppMotion.enter,
                    switchOutCurve: AppMotion.exit,
                    transitionBuilder: (child, animation) => FadeTransition(
                      opacity: animation,
                      child: SlideTransition(
                        position: Tween<Offset>(begin: AppMotion.gentleRise, end: Offset.zero).animate(animation),
                        child: child,
                      ),
                    ),
                    child: EditChangesSummary(
                      key: ValueKey(shown.id),
                      insights: shownInsights,
                      totalSeconds: rawSeconds,
                      keptRanges: keptRanges,
                      selected: selected,
                      onRemovedTap: (range) => setState(() {
                        _selectedRemoved = range;
                        _showRaw = false;
                      }),
                    ),
                  ),
                ),
              ],
              if (selected != null) ...[
                const SizedBox(height: AppSpacing.md),
                _Section(
                  child: _RemovedPreview(
                    range: selected,
                    rawPath: rawPath,
                    aspectRatio: ratio,
                    canRestore: (caps?.revisions ?? false) && !state.isProcessing,
                    restoring: state.isSendingInstruction,
                    onRestore: () => _restore(selected),
                  ),
                ),
              ],
              if (done.length > 1) ...[
                const SizedBox(height: AppSpacing.md),
                _Section(
                  child: AppSelector<String>(
                    label: 'Version',
                    value: shown.id,
                    choices: [
                      for (final version in done) Choice(value: version.id, label: 'Version ${version.version}'),
                    ],
                    onChanged: (id) {
                      setState(() => _selectedRemoved = null);
                      widget.controller.selectVersion(id);
                    },
                  ),
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
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.gutter,
                AppSpacing.sm,
                AppSpacing.gutter,
                AppSpacing.gutter,
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      Expanded(
                        flex: compactLabels ? 1 : 2,
                        child: PrimaryButton(
                          label: saving && _exportProgress != null
                              ? 'Saving ${(_exportProgress! * 100).round()}%'
                              : (compactLabels ? 'Save' : 'Save to Photos'),
                          leadingIcon: CupertinoIcons.arrow_down_to_line,
                          isLoading: saving,
                          onPressed: _activeExport == null
                              ? () => _export(shown.outputUrl!, shown.version, ExportTarget.photos)
                              : null,
                        ),
                      ),
                      const SizedBox(width: AppSpacing.xs),
                      Expanded(
                        child: SecondaryButton(
                          label: 'Share',
                          leadingIcon: CupertinoIcons.share,
                          isLoading: _activeExport == ExportTarget.share,
                          onPressed: _activeExport == null
                              ? () => _export(shown.outputUrl!, shown.version, ExportTarget.share)
                              : null,
                        ),
                      ),
                    ],
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
                              label: compactLabels ? 'Variants' : 'Create variants',
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

bool _sameRange(CutRange a, CutRange? b) =>
    b != null && a.source == b.source && (a.start - b.start).abs() < 0.01 && (a.end - b.end).abs() < 0.01;

class _Section extends StatelessWidget {
  const _Section({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(horizontal: AppSpacing.gutter),
    child: child,
  );
}

class _TimeSavedSummary extends StatelessWidget {
  const _TimeSavedSummary({required this.rawSeconds, required this.resultSeconds, required this.saved});

  final double? rawSeconds;
  final double resultSeconds;
  final String? saved;

  @override
  Widget build(BuildContext context) => Semantics(
    container: true,
    label: rawSeconds != null
        ? 'Original ${Format.duration(rawSeconds!)}, ready ${Format.duration(resultSeconds)}${saved != null ? ', $saved' : ''}'
        : 'Ready ${Format.duration(resultSeconds)}',
    excludeSemantics: true,
    child: Wrap(
      spacing: AppSpacing.xs,
      runSpacing: AppSpacing.xs,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        if (rawSeconds != null) ...[
          Text(Format.duration(rawSeconds!), style: AppTypography.title.copyWith(color: AppColors.textMuted)),
          const Icon(CupertinoIcons.arrow_right, size: 18, color: AppColors.textSecondary),
        ],
        Text(Format.duration(resultSeconds), style: AppTypography.title),
        if (saved != null) Text(saved!, style: AppTypography.label.copyWith(color: AppColors.success)),
      ],
    ),
  );
}

class _RemovedPreview extends StatelessWidget {
  const _RemovedPreview({
    required this.range,
    required this.rawPath,
    required this.aspectRatio,
    required this.canRestore,
    required this.restoring,
    required this.onRestore,
  });

  final CutRange range;
  final String? rawPath;
  final double aspectRatio;
  final bool canRestore;
  final bool restoring;
  final VoidCallback onRestore;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(AppSpacing.sm),
    decoration: BoxDecoration(
      color: AppColors.surfaceRaised,
      borderRadius: AppRadius.largeAll,
      border: Border.all(color: AppColors.surfaceBorder),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            const Icon(CupertinoIcons.scissors, size: 18, color: AppColors.destructive),
            const SizedBox(width: AppSpacing.xs),
            Expanded(
              child: Text(
                'Removed ${Format.duration(range.start)}–${Format.duration(range.end)}',
                style: AppTypography.label,
              ),
            ),
            Text('${range.duration.toStringAsFixed(1)}s', style: AppTypography.caption),
          ],
        ),
        const SizedBox(height: AppSpacing.sm),
        if (rawPath != null)
          VideoResultPlayer(
            source: rawPath!,
            aspectRatio: aspectRatio,
            startAt: range.start,
            stopAt: range.end,
            autoPlay: true,
          )
        else
          const Padding(
            padding: EdgeInsets.symmetric(vertical: AppSpacing.md),
            child: Text(
              'The original is no longer on this device, but you can still restore this range from the uploaded footage.',
              style: AppTypography.bodySecondary,
            ),
          ),
        const SizedBox(height: AppSpacing.sm),
        SecondaryButton(
          label: 'Restore this clip',
          leadingIcon: CupertinoIcons.arrow_counterclockwise,
          isLoading: restoring,
          onPressed: canRestore ? onRestore : null,
        ),
      ],
    ),
  );
}

class _ProcessingNotice extends StatelessWidget {
  const _ProcessingNotice();

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm, vertical: AppSpacing.xs),
    decoration: const BoxDecoration(color: AppColors.accentSoft, borderRadius: AppRadius.mediumAll),
    child: const Row(
      children: [
        CupertinoActivityIndicator(color: AppColors.accentText),
        SizedBox(width: AppSpacing.xs),
        Expanded(child: Text('Building your updated cut…', style: AppTypography.bodySecondary)),
      ],
    ),
  );
}
