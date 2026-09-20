import 'package:flutter/cupertino.dart';
import 'package:flutter/services.dart';

import '../design/app_colors.dart';
import '../design/app_radius.dart';
import '../design/app_spacing.dart';
import '../design/app_typography.dart';
import 'app_sheet.dart';

/// One choice in a selector.
class Choice<T> {
  const Choice({required this.value, required this.label, this.detail});

  final T value;
  final String label;
  final String? detail;
}

/// A labelled field showing the current choice; tapping opens a bottom sheet of options.
class AppSelector<T> extends StatelessWidget {
  const AppSelector({
    super.key,
    required this.label,
    required this.value,
    required this.choices,
    required this.onChanged,
  });

  final String label;
  final T value;
  final List<Choice<T>> choices;
  final ValueChanged<T> onChanged;

  Choice<T> get _current => choices.firstWhere((c) => c.value == value, orElse: () => choices.first);

  Future<void> _open(BuildContext context) async {
    final picked = await showAppSheet<T>(
      context,
      title: label,
      builder: (sheetContext) => ListView(
        shrinkWrap: true,
        children: [
          for (final choice in choices)
            _OptionRow(
              choice: choice,
              selected: choice.value == value,
              onTap: () => Navigator.of(sheetContext).pop(choice.value),
            ),
        ],
      ),
    );
    if (picked != null && picked != value) onChanged(picked);
  }

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: '$label, ${_current.label}',
      hint: 'Double tap to change',
      excludeSemantics: true,
      onTap: () => _open(context),
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () {
          HapticFeedback.selectionClick();
          _open(context);
        },
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: AppSpacing.fieldHeight),
          child: DecoratedBox(
            decoration: const BoxDecoration(color: AppColors.surface, borderRadius: AppRadius.mediumAll),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: AppSpacing.sm),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(label, style: AppTypography.caption, maxLines: 1, overflow: TextOverflow.ellipsis),
                        const SizedBox(height: AppSpacing.xxs),
                        Text(_current.label, style: AppTypography.label, maxLines: 1, overflow: TextOverflow.ellipsis),
                      ],
                    ),
                  ),
                  const SizedBox(width: AppSpacing.xs),
                  const Icon(CupertinoIcons.chevron_up_chevron_down, size: 16, color: AppColors.textSecondary),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _OptionRow<T> extends StatelessWidget {
  const _OptionRow({required this.choice, required this.selected, required this.onTap});

  final Choice<T> choice;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      selected: selected,
      label: choice.label,
      excludeSemantics: true,
      onTap: onTap,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onTap,
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: AppSpacing.minTap + AppSpacing.xs),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(choice.label, style: AppTypography.body),
                    if (choice.detail != null) Text(choice.detail!, style: AppTypography.caption),
                  ],
                ),
              ),
              if (selected) const Icon(CupertinoIcons.checkmark_alt, size: 20, color: AppColors.accentText),
            ],
          ),
        ),
      ),
    );
  }
}

/// Segmented control for two to four short options; each segment is a real tap target.
class SegmentedChoice<T> extends StatelessWidget {
  const SegmentedChoice({
    super.key,
    required this.label,
    required this.value,
    required this.choices,
    required this.onChanged,
  });

  final String label;
  final T value;
  final List<Choice<T>> choices;
  final ValueChanged<T> onChanged;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      container: true,
      label: label,
      child: DecoratedBox(
        decoration: const BoxDecoration(color: AppColors.surface, borderRadius: AppRadius.mediumAll),
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xxs),
          child: Row(
            children: [
              for (final choice in choices)
                Expanded(
                  child: Semantics(
                    button: true,
                    selected: choice.value == value,
                    label: choice.label,
                    excludeSemantics: true,
                    onTap: () => onChanged(choice.value),
                    child: GestureDetector(
                      behavior: HitTestBehavior.opaque,
                      onTap: () {
                        HapticFeedback.selectionClick();
                        onChanged(choice.value);
                      },
                      child: AnimatedContainer(
                        duration: const Duration(milliseconds: 150),
                        constraints: const BoxConstraints(minHeight: AppSpacing.minTap),
                        alignment: Alignment.center,
                        decoration: BoxDecoration(
                          color: choice.value == value ? AppColors.surfacePressed : AppColors.surface,
                          borderRadius: AppRadius.smallAll,
                        ),
                        child: Text(
                          choice.label,
                          style: AppTypography.label.copyWith(
                            color: choice.value == value ? AppColors.textPrimary : AppColors.textSecondary,
                          ),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
