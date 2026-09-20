import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/design/app_colors.dart';
import '../../core/design/app_radius.dart';
import '../../core/design/app_spacing.dart';
import '../../core/design/app_typography.dart';
import '../../core/models/api_models.dart';
import '../../core/widgets/screen_header.dart';
import '../../core/widgets/state_views.dart';

/// Live service status: is the backend reachable, and which features it currently offers.
class StatusScreen extends ConsumerWidget {
  const StatusScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final capabilities = ref.watch(capabilitiesProvider);
    final health = ref.watch(healthProvider);

    final Widget body = capabilities.when(
      loading: () => const LoadingView(),
      error: (error, _) => MessageView(
        icon: CupertinoIcons.wifi_slash,
        title: "Can't reach AdCut",
        message: 'Check your connection and try again.',
        actionLabel: 'Try again',
        onAction: () {
          ref.invalidate(capabilitiesProvider);
          ref.invalidate(healthProvider);
        },
      ),
      data: (caps) => ListView(
        padding: const EdgeInsets.all(AppSpacing.gutter),
        children: [
          _Row(
            label: 'Service',
            available: health.value == true,
            availableText: 'Online',
            unavailableText: 'Unreachable',
          ),
          const SizedBox(height: AppSpacing.xl),
          const Text('Features', style: AppTypography.heading),
          const SizedBox(height: AppSpacing.xs),
          ..._features(caps),
        ],
      ),
    );

    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            const ScreenHeader(title: 'Service status'),
            Expanded(child: body),
          ],
        ),
      ),
    );
  }

  List<Widget> _features(Capabilities caps) => [
    _Row(label: 'AI editing', available: caps.editing),
    const SizedBox(height: AppSpacing.xs),
    _Row(label: 'Prompt revisions', available: caps.revisions),
    const SizedBox(height: AppSpacing.xs),
    _Row(label: 'Variants', available: caps.variants),
    const SizedBox(height: AppSpacing.xs),
    _Row(label: 'AI B-roll', available: caps.aiBroll),
  ];
}

class _Row extends StatelessWidget {
  const _Row({
    required this.label,
    required this.available,
    this.availableText = 'Available',
    this.unavailableText = 'Unavailable',
  });

  final String label;
  final bool available;
  final String availableText;
  final String unavailableText;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      container: true,
      label: '$label, ${available ? availableText : unavailableText}',
      excludeSemantics: true,
      child: DecoratedBox(
        decoration: const BoxDecoration(color: AppColors.surface, borderRadius: AppRadius.mediumAll),
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: AppSpacing.fieldHeight),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
            child: Row(
              children: [
                Expanded(child: Text(label, style: AppTypography.body)),
                Icon(
                  available ? CupertinoIcons.checkmark_circle_fill : CupertinoIcons.minus_circle_fill,
                  size: 18,
                  color: available ? AppColors.success : AppColors.textMuted,
                ),
                const SizedBox(width: AppSpacing.xs),
                Text(available ? availableText : unavailableText, style: AppTypography.bodySecondary),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
