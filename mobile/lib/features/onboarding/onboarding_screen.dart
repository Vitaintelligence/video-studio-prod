import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/routes.dart';
import '../../core/design/app_colors.dart';
import '../../core/design/app_radius.dart';
import '../../core/design/app_spacing.dart';
import '../../core/design/app_typography.dart';
import '../../core/widgets/app_progress_bar.dart';
import '../../core/widgets/buttons.dart';
import 'onboarding_controller.dart';
import 'onboarding_model.dart';

/// Four short questions, one per screen, then a transparent estimate and the first recording.
class OnboardingScreen extends ConsumerStatefulWidget {
  const OnboardingScreen({super.key});

  @override
  ConsumerState<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends ConsumerState<OnboardingScreen> {
  static const int _questions = 4;
  static const int _estimateStep = 4;
  static const int _startStep = 5;
  int _step = 0;

  void _go(int step) => setState(() => _step = step);

  void _finish({required bool record}) {
    ref.read(onboardingProvider.notifier).complete();
    context.go(Routes.home);
    if (record) context.push(Routes.camera);
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(onboardingProvider);
    final controller = ref.read(onboardingProvider.notifier);

    final Widget page = switch (_step) {
      0 => _Question<Persona>(
        key: const ValueKey(0),
        title: 'What best describes you?',
        values: Persona.values,
        label: (v) => v.label,
        selected: state.persona,
        onSelect: (v) {
          controller.setPersona(v);
          _go(1);
        },
      ),
      1 => _Question<Niche>(
        key: const ValueKey(1),
        title: 'What do you create?',
        values: Niche.values,
        label: (v) => v.label,
        selected: state.niche,
        columns: 2,
        onSelect: (v) {
          controller.setNiche(v);
          _go(2);
        },
      ),
      2 => _Question<WeeklyVolume>(
        key: const ValueKey(2),
        title: 'How many videos do you make each week?',
        values: WeeklyVolume.values,
        label: (v) => v.label,
        selected: state.volume,
        onSelect: (v) {
          controller.setVolume(v);
          _go(3);
        },
      ),
      3 => _Question<EditingTime>(
        key: const ValueKey(3),
        title: 'How long does editing one video usually take?',
        values: EditingTime.values,
        label: (v) => v.label,
        selected: state.time,
        onSelect: (v) {
          controller.setTime(v);
          _go(_estimateStep);
        },
      ),
      _estimateStep => _Estimate(key: const ValueKey(4), state: state, onClaim: () => _go(_startStep)),
      _ => _Start(key: const ValueKey(5), onRecord: () => _finish(record: true), onSkip: () => _finish(record: false)),
    };

    return Scaffold(
      body: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            SizedBox(
              height: 56,
              child: Row(
                children: [
                  if (_step > 0 && _step < _startStep)
                    AppIconButton(icon: CupertinoIcons.back, label: 'Back', onPressed: () => _go(_step - 1))
                  else
                    const SizedBox(width: AppSpacing.minTap),
                  Expanded(
                    child: _step < _estimateStep
                        ? AppProgressBar(
                            value: (_step + 1) / _questions,
                            semanticLabel: 'Question ${_step + 1} of $_questions',
                          )
                        : const SizedBox(),
                  ),
                  const SizedBox(width: AppSpacing.minTap),
                ],
              ),
            ),
            Expanded(
              child: AnimatedSwitcher(duration: const Duration(milliseconds: 200), child: page),
            ),
          ],
        ),
      ),
    );
  }
}

class _Question<T> extends StatelessWidget {
  const _Question({
    super.key,
    required this.title,
    required this.values,
    required this.label,
    required this.selected,
    required this.onSelect,
    this.columns = 1,
  });

  final String title;
  final List<T> values;
  final String Function(T) label;
  final T? selected;
  final ValueChanged<T> onSelect;
  final int columns;

  @override
  Widget build(BuildContext context) {
    Widget option(T v) => _Option(label: label(v), selected: v == selected, onTap: () => onSelect(v));
    return ListView(
      padding: const EdgeInsets.all(AppSpacing.gutter),
      children: [
        Semantics(header: true, child: Text(title, style: AppTypography.display)),
        const SizedBox(height: AppSpacing.xl),
        if (columns == 1)
          for (final v in values) ...[option(v), const SizedBox(height: AppSpacing.xs)]
        else
          Wrap(
            spacing: AppSpacing.xs,
            runSpacing: AppSpacing.xs,
            children: [
              for (final v in values)
                SizedBox(
                  width: (MediaQuery.sizeOf(context).width - AppSpacing.gutter * 2 - AppSpacing.xs) / 2,
                  child: option(v),
                ),
            ],
          ),
      ],
    );
  }
}

class _Option extends StatelessWidget {
  const _Option({required this.label, required this.selected, required this.onTap});

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Semantics(
    button: true,
    selected: selected,
    label: label,
    excludeSemantics: true,
    onTap: onTap,
    child: GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () {
        HapticFeedback.selectionClick();
        onTap();
      },
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 56),
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: selected ? AppColors.accent : AppColors.surface,
            borderRadius: AppRadius.mediumAll,
          ),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: AppSpacing.sm),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    label,
                    style: AppTypography.label.copyWith(color: selected ? AppColors.onAccent : AppColors.textPrimary),
                  ),
                ),
                if (selected) const Icon(CupertinoIcons.checkmark_alt, size: 20, color: AppColors.onAccent),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}

class _Estimate extends StatelessWidget {
  const _Estimate({super.key, required this.state, required this.onClaim});

  final OnboardingState state;
  final VoidCallback onClaim;

  @override
  Widget build(BuildContext context) {
    final estimate = state.estimate;
    final days = estimate?.workingDays ?? 0;
    return Padding(
      padding: const EdgeInsets.all(AppSpacing.gutter),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Expanded(
            child: ListView(
              children: [
                const SizedBox(height: AppSpacing.xl),
                Text(
                  estimate == null
                      ? 'Editing takes real time.'
                      : 'You spend about ${estimate.roundedHours} hours each month editing.',
                  style: AppTypography.display,
                ),
                const SizedBox(height: AppSpacing.md),
                if (estimate != null) ...[
                  Text(
                    "That's ${days >= 1 ? 'about ${days.toStringAsFixed(days >= 10 ? 0 : 1)} working days' : 'less than a working day'}.",
                    style: AppTypography.heading,
                  ),
                  const SizedBox(height: AppSpacing.lg),
                  Text(
                    'Estimate: ${state.volume!.label} videos a week × ${state.time!.label} each, counted in 8-hour working days.',
                    style: AppTypography.caption,
                  ),
                ],
              ],
            ),
          ),
          PrimaryButton(label: 'Claim your time', onPressed: onClaim),
        ],
      ),
    );
  }
}

class _Start extends StatelessWidget {
  const _Start({super.key, required this.onRecord, required this.onSkip});

  final VoidCallback onRecord;
  final VoidCallback onSkip;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.all(AppSpacing.gutter),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Expanded(
          child: Align(
            alignment: Alignment.centerLeft,
            child: Text('Record one messy take. We will clean it.', style: AppTypography.display),
          ),
        ),
        PrimaryButton(label: 'Start first recording', leadingIcon: CupertinoIcons.camera_fill, onPressed: onRecord),
        const SizedBox(height: AppSpacing.xs),
        Center(
          child: TertiaryButton(label: 'Go to Home', onPressed: onSkip),
        ),
      ],
    ),
  );
}
