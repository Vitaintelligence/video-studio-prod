import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../app/providers.dart';
import '../../app/routes.dart';
import '../../core/design/app_colors.dart';
import '../../core/design/app_radius.dart';
import '../../core/design/app_spacing.dart';
import '../../core/design/app_typography.dart';
import '../../core/intents/edit_intent.dart';
import '../../core/models/api_models.dart';
import '../../core/widgets/app_sheet.dart';
import '../../core/widgets/buttons.dart';
import '../clean/clean_controller.dart';
import '../clean/footage_picker.dart';
import '../onboarding/onboarding_controller.dart';
import '../onboarding/onboarding_model.dart';
import '../projects/project_tile.dart';
import '../projects/projects_controller.dart';

class _IntentInfo {
  const _IntentInfo(this.title, this.subtitle, this.icon);
  final String title;
  final String subtitle;
  final IconData icon;
}

const _info = {
  EditIntent.recordClean: _IntentInfo(
    'Record & Clean',
    'Record normally. AI removes the mess.',
    CupertinoIcons.camera_fill,
  ),
  EditIntent.uploadClean: _IntentInfo(
    'Upload & Clean',
    'Pick a video. AI removes the mess.',
    CupertinoIcons.arrow_up_circle_fill,
  ),
  EditIntent.adVariants: _IntentInfo(
    'Make Ad Variants',
    'Test different hooks of a finished cut.',
    CupertinoIcons.square_on_square,
  ),
  EditIntent.videoToClips: _IntentInfo(
    'Video to Clips',
    'Find the best moments in a long video.',
    CupertinoIcons.scissors,
  ),
};

/// Intent-first Home: what are you making today, then real recent work.
class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  Future<void> _upload(BuildContext context, WidgetRef ref) async {
    final picker = ref.read(footagePickerProvider);
    final source = await showAppSheet<bool>(
      context,
      title: 'Upload from',
      builder: (sheetContext) => Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          _SheetRow(icon: CupertinoIcons.photo, label: 'Photos', onTap: () => Navigator.of(sheetContext).pop(true)),
          _SheetRow(icon: CupertinoIcons.folder, label: 'Files', onTap: () => Navigator.of(sheetContext).pop(false)),
        ],
      ),
    );
    if (source == null || !context.mounted) return;
    try {
      final footage = source ? await picker.pickFromPhotos() : await picker.pickFromFiles();
      if (footage == null || !context.mounted) return;
      final seconds = await picker.durationOf(footage.path);
      if (!context.mounted) return;
      ref.read(cleanControllerProvider.notifier).start(footage, intent: EditIntent.uploadClean, rawSeconds: seconds);
      context.push(Routes.upload);
    } on PlatformException {
      if (context.mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text("We couldn't open your videos. Check access in Settings.")));
      }
    }
  }

  Future<void> _variants(BuildContext context, List<ApiProject> projects) async {
    final ready = [
      for (final p in projects)
        if (p.latestEdit?.isDone ?? false) p,
    ];
    final picked = await showAppSheet<ApiProject>(
      context,
      title: 'Which cut?',
      builder: (sheetContext) => ready.isEmpty
          ? const Padding(
              padding: EdgeInsets.symmetric(vertical: AppSpacing.md),
              child: Text('Finish a cut first, then create variants of it.', style: AppTypography.bodySecondary),
            )
          : ListView(
              shrinkWrap: true,
              children: [
                for (final p in ready.take(8))
                  _SheetRow(icon: CupertinoIcons.film, label: p.name, onTap: () => Navigator.of(sheetContext).pop(p)),
              ],
            ),
    );
    if (picked != null && context.mounted) context.push(Routes.variants(picked.latestEdit!.id));
  }

  void _run(BuildContext context, WidgetRef ref, EditIntent intent, List<ApiProject> projects) {
    switch (intent) {
      case EditIntent.recordClean:
        context.push(Routes.camera);
      case EditIntent.uploadClean:
        _upload(context, ref);
      case EditIntent.adVariants:
        _variants(context, projects);
      case EditIntent.videoToClips || EditIntent.promptRevision:
        break;
    }
  }

  bool _available(EditIntent intent, Capabilities? caps) => switch (intent) {
    EditIntent.recordClean || EditIntent.uploadClean => caps?.editing ?? true,
    EditIntent.adVariants => caps?.variants ?? false,
    EditIntent.videoToClips => caps?.videoToClips ?? false,
    EditIntent.promptRevision => false,
  };

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final persona = ref.watch(onboardingProvider.select((s) => s.persona));
    final caps = ref.watch(capabilitiesProvider).value;
    final projects = ref.watch(projectsProvider).value ?? const <ApiProject>[];
    final clean = ref.watch(cleanControllerProvider);
    final unavailable = caps != null && !caps.editing;
    final intents = [
      for (final i in intentOrderFor(persona))
        if (_available(i, caps)) i,
    ];
    final recent = [
      for (final p in projects)
        if (p.latestEdit != null) p,
    ].take(3).toList();
    final firstMore = intents
        .skip(1)
        .where((i) => i != EditIntent.recordClean && i != EditIntent.uploadClean)
        .firstOrNull;

    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(AppSpacing.gutter, 0, AppSpacing.gutter, AppSpacing.floatingBarOffset),
          children: [
            SizedBox(
              height: 56,
              child: Row(
                children: [
                  const Expanded(child: Text('AdCut', style: AppTypography.heading)),
                  AppIconButton(
                    icon: CupertinoIcons.person_crop_circle,
                    label: 'Account',
                    onPressed: () => context.push(Routes.account),
                  ),
                ],
              ),
            ),
            const SizedBox(height: AppSpacing.sm),
            const Text('What are you making today?', style: AppTypography.display),
            const SizedBox(height: AppSpacing.xl),
            if (clean.isBusy) ...[
              _Notice(
                icon: CupertinoIcons.arrow_up_circle,
                message: 'Uploading your video',
                onTap: () => context.push(Routes.upload),
              ),
              const SizedBox(height: AppSpacing.sm),
            ],
            if (unavailable)
              const _Notice(
                icon: CupertinoIcons.exclamationmark_triangle_fill,
                message: 'Editing is unavailable right now. Please try again shortly.',
              )
            else if (intents.isNotEmpty) ...[
              _PrimaryIntent(info: _info[intents.first]!, onTap: () => _run(context, ref, intents.first, projects)),
              for (final intent in intents.skip(1)) ...[
                if (intent == firstMore) ...[
                  const SizedBox(height: AppSpacing.xl),
                  const Text('Do more', style: AppTypography.heading),
                ],
                const SizedBox(height: AppSpacing.xs),
                _IntentRow(info: _info[intent]!, onTap: () => _run(context, ref, intent, projects)),
              ],
            ],
            const SizedBox(height: AppSpacing.xxl),
            Row(
              children: [
                const Expanded(child: Text('Recent', style: AppTypography.heading)),
                if (recent.isNotEmpty) TertiaryButton(label: 'See all', onPressed: () => context.go(Routes.projects)),
              ],
            ),
            const SizedBox(height: AppSpacing.xs),
            if (recent.isEmpty)
              const Text('Your finished cuts will show up here.', style: AppTypography.bodySecondary)
            else
              for (final p in recent) ...[
                ProjectTile(project: p, onTap: () => context.push(Routes.edit(p.latestEdit!.id))),
                const SizedBox(height: AppSpacing.xs),
              ],
          ],
        ),
      ),
    );
  }
}

class _PrimaryIntent extends StatelessWidget {
  const _PrimaryIntent({required this.info, required this.onTap});

  final _IntentInfo info;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Semantics(
    button: true,
    label: '${info.title}. ${info.subtitle}',
    excludeSemantics: true,
    onTap: onTap,
    child: GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () {
        HapticFeedback.selectionClick();
        onTap();
      },
      child: DecoratedBox(
        decoration: const BoxDecoration(color: AppColors.accent, borderRadius: AppRadius.largeAll),
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(info.title, style: AppTypography.title.copyWith(color: AppColors.onAccent)),
                    const SizedBox(height: AppSpacing.xxs),
                    Text(info.subtitle, style: AppTypography.bodySecondary.copyWith(color: AppColors.onAccent)),
                  ],
                ),
              ),
              const SizedBox(width: AppSpacing.md),
              Icon(info.icon, size: 32, color: AppColors.onAccent),
            ],
          ),
        ),
      ),
    ),
  );
}

class _IntentRow extends StatelessWidget {
  const _IntentRow({required this.info, required this.onTap});

  final _IntentInfo info;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Semantics(
    button: true,
    label: '${info.title}. ${info.subtitle}',
    excludeSemantics: true,
    onTap: onTap,
    child: GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onTap,
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 64),
        child: DecoratedBox(
          decoration: const BoxDecoration(color: AppColors.surface, borderRadius: AppRadius.mediumAll),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: AppSpacing.sm),
            child: Row(
              children: [
                Icon(info.icon, size: 24, color: AppColors.accentText),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(info.title, style: AppTypography.label),
                      Text(info.subtitle, style: AppTypography.caption),
                    ],
                  ),
                ),
                const Icon(CupertinoIcons.chevron_right, size: 16, color: AppColors.textMuted),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}

class _SheetRow extends StatelessWidget {
  const _SheetRow({required this.icon, required this.label, required this.onTap});

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
            Expanded(
              child: Text(label, style: AppTypography.body, maxLines: 1, overflow: TextOverflow.ellipsis),
            ),
          ],
        ),
      ),
    ),
  );
}

class _Notice extends StatelessWidget {
  const _Notice({required this.icon, required this.message, this.onTap});

  final IconData icon;
  final String message;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => Semantics(
    button: onTap != null,
    label: message,
    excludeSemantics: true,
    onTap: onTap,
    child: GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onTap,
      child: DecoratedBox(
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
      ),
    ),
  );
}
