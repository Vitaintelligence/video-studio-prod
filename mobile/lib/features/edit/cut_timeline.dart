import 'package:flutter/cupertino.dart';
import 'package:flutter/services.dart';

import '../../core/design/app_colors.dart';
import '../../core/design/app_motion.dart';
import '../../core/design/app_radius.dart';
import '../../core/design/app_spacing.dart';
import '../../core/design/app_typography.dart';
import '../../core/format.dart';
import '../../core/models/api_models.dart';
import '../../core/widgets/press_scale.dart';

class CutSlice {
  const CutSlice({required this.range, required this.kept});

  final CutRange range;
  final bool kept;
}

List<CutSlice> buildCutSlices(double totalSeconds, List<CutRange> ranges) {
  if (totalSeconds <= 0) return const [];
  final kept =
      ranges
          .where((range) => range.source == 0 && range.end > range.start)
          .map(
            (range) =>
                CutRange(source: 0, start: range.start.clamp(0, totalSeconds), end: range.end.clamp(0, totalSeconds)),
          )
          .where((range) => range.duration > 0.02)
          .toList()
        ..sort((a, b) => a.start.compareTo(b.start));
  if (kept.isEmpty) return const [];

  final merged = <CutRange>[];
  for (final range in kept) {
    if (merged.isNotEmpty && range.start <= merged.last.end + 0.02) {
      final last = merged.removeLast();
      merged.add(CutRange(source: 0, start: last.start, end: range.end > last.end ? range.end : last.end));
    } else {
      merged.add(range);
    }
  }

  final slices = <CutSlice>[];
  var cursor = 0.0;
  for (final range in merged) {
    if (range.start > cursor + 0.02) {
      slices.add(
        CutSlice(
          range: CutRange(source: 0, start: cursor, end: range.start),
          kept: false,
        ),
      );
    }
    slices.add(CutSlice(range: range, kept: true));
    cursor = range.end;
  }
  if (cursor < totalSeconds - 0.02) {
    slices.add(
      CutSlice(
        range: CutRange(source: 0, start: cursor, end: totalSeconds),
        kept: false,
      ),
    );
  }
  return slices;
}

class CutTimeline extends StatelessWidget {
  const CutTimeline({
    super.key,
    required this.totalSeconds,
    required this.keptRanges,
    required this.selected,
    required this.onRemovedTap,
  });

  final double totalSeconds;
  final List<CutRange> keptRanges;
  final CutRange? selected;
  final ValueChanged<CutRange> onRemovedTap;

  @override
  Widget build(BuildContext context) {
    final slices = buildCutSlices(totalSeconds, keptRanges);
    final removed = slices.where((slice) => !slice.kept).length;
    if (slices.isEmpty || removed == 0) return const SizedBox.shrink();

    return Semantics(
      container: true,
      label: '$removed removed ${removed == 1 ? 'clip' : 'clips'}. Tap one to preview it.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Wrap(
            alignment: WrapAlignment.spaceBetween,
            runSpacing: AppSpacing.xxs,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              const Text('What AdCut changed', style: AppTypography.heading),
              Text('$removed removed', style: AppTypography.caption.copyWith(color: AppColors.destructive)),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          SizedBox(
            height: 44,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                for (final slice in slices)
                  Expanded(
                    flex: (slice.range.duration * 100).round().clamp(1, 100000),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 1),
                      child: slice.kept
                          ? _TimelineBlock(slice: slice, selected: false)
                          : Semantics(
                              button: true,
                              label:
                                  'Preview removed clip ${Format.duration(slice.range.start)} to ${Format.duration(slice.range.end)}',
                              onTap: () => onRemovedTap(slice.range),
                              child: PressScale(
                                pressedScale: 0.9,
                                onTap: () {
                                  HapticFeedback.selectionClick();
                                  onRemovedTap(slice.range);
                                },
                                child: _TimelineBlock(slice: slice, selected: _sameRange(selected, slice.range)),
                              ),
                            ),
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.xs),
          Wrap(
            spacing: AppSpacing.md,
            runSpacing: AppSpacing.xxs,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              const _Legend(color: AppColors.accentSecondary, label: 'Kept'),
              const _Legend(color: AppColors.destructive, label: 'Removed · tap to review'),
              Text('Source ${Format.duration(totalSeconds)}', style: AppTypography.caption),
            ],
          ),
        ],
      ),
    );
  }
}

bool _sameRange(CutRange? a, CutRange b) =>
    a != null && a.source == b.source && (a.start - b.start).abs() < 0.01 && (a.end - b.end).abs() < 0.01;

class _TimelineBlock extends StatelessWidget {
  const _TimelineBlock({required this.slice, required this.selected});

  final CutSlice slice;
  final bool selected;

  @override
  Widget build(BuildContext context) => AnimatedContainer(
    duration: AppMotion.allowed(context, AppMotion.standard),
    curve: AppMotion.enter,
    decoration: BoxDecoration(
      color: slice.kept ? AppColors.accentSecondary : AppColors.destructive,
      borderRadius: AppRadius.smallAll,
      border: selected ? Border.all(color: AppColors.textPrimary, width: 2) : null,
    ),
    child: slice.kept
        ? null
        : Center(
            child: Icon(
              selected ? CupertinoIcons.play_fill : CupertinoIcons.scissors,
              size: 15,
              color: AppColors.onDestructive,
            ),
          ),
  );
}

class _Legend extends StatelessWidget {
  const _Legend({required this.color, required this.label});

  final Color color;
  final String label;

  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Container(
        width: 8,
        height: 8,
        decoration: BoxDecoration(color: color, shape: BoxShape.circle),
      ),
      const SizedBox(width: AppSpacing.xxs),
      Text(label, style: AppTypography.caption),
    ],
  );
}
