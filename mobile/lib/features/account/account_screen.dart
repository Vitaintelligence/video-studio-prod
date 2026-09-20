import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/routes.dart';
import '../../core/design/app_colors.dart';
import '../../core/design/app_radius.dart';
import '../../core/design/app_spacing.dart';
import '../../core/design/app_typography.dart';
import '../../core/widgets/app_selector.dart';
import '../../core/widgets/screen_header.dart';
import '../onboarding/onboarding_controller.dart';
import '../settings/ad_options.dart';
import '../settings/settings_controller.dart';

/// Preferences that apply to every new cut, plus the way to check service status.
class AccountScreen extends ConsumerWidget {
  const AccountScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(settingsProvider);
    final controller = ref.read(settingsProvider.notifier);
    final onboarding = ref.watch(onboardingProvider);
    final estimate = onboarding.estimate;

    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            const ScreenHeader(title: 'Account'),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(AppSpacing.gutter, AppSpacing.xs, AppSpacing.gutter, AppSpacing.xl),
                children: [
                  if (onboarding.persona != null) Text(onboarding.persona!.label, style: AppTypography.title),
                  if (estimate != null) ...[
                    const SizedBox(height: AppSpacing.xxs),
                    Text(
                      'About ${estimate.roundedHours} hours a month spent editing',
                      style: AppTypography.bodySecondary,
                    ),
                  ],
                  const SizedBox(height: AppSpacing.xl),
                  const Text('New cuts', style: AppTypography.heading),
                  const SizedBox(height: AppSpacing.xs),
                  AppSelector<AdPlatform>(
                    label: 'Default platform',
                    value: settings.platform,
                    choices: [for (final p in AdPlatform.values) Choice(value: p, label: p.label)],
                    onChanged: controller.setPlatform,
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  SegmentedChoice<AdFormat>(
                    label: 'Default format',
                    value: settings.format,
                    choices: [for (final f in AdFormat.values) Choice(value: f, label: f.ratio)],
                    onChanged: controller.setFormat,
                  ),
                  const SizedBox(height: AppSpacing.xl),
                  const Text('Support', style: AppTypography.heading),
                  const SizedBox(height: AppSpacing.xs),
                  _LinkRow(label: 'Service status', onTap: () => context.push(Routes.status)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _LinkRow extends StatelessWidget {
  const _LinkRow({required this.label, required this.onTap});

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
        constraints: const BoxConstraints(minHeight: AppSpacing.fieldHeight),
        child: DecoratedBox(
          decoration: const BoxDecoration(color: AppColors.surface, borderRadius: AppRadius.mediumAll),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
            child: Row(
              children: [
                Expanded(child: Text(label, style: AppTypography.body)),
                const Icon(CupertinoIcons.chevron_right, size: 16, color: AppColors.textMuted),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}
