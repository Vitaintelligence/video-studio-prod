import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/api/api_exception.dart';
import '../../core/design/app_colors.dart';
import '../../core/design/app_radius.dart';
import '../../core/design/app_spacing.dart';
import '../../core/design/app_typography.dart';
import '../../core/format.dart';
import '../../core/models/api_models.dart';
import '../../core/widgets/app_progress_bar.dart';
import '../../core/widgets/app_selector.dart';
import '../../core/widgets/app_sheet.dart';
import '../../core/widgets/buttons.dart';
import '../../core/widgets/remote_thumbnail.dart';
import '../../core/widgets/screen_header.dart';
import '../../core/widgets/state_views.dart';
import '../../core/widgets/status_tag.dart';
import '../settings/ad_options.dart';
import 'export_service.dart';
import 'variants_controller.dart';
import 'video_result_player.dart';

/// Hook variants of one edit, for creative testing. Only shown when the backend supports variants.
class VariantsScreen extends ConsumerWidget {
  const VariantsScreen({super.key, required this.editId});

  final String editId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final capabilities = ref.watch(capabilitiesProvider);
    final unavailable = capabilities.hasValue && !capabilities.requireValue.variants;
    final state = ref.watch(variantsControllerProvider(editId));
    final controller = ref.read(variantsControllerProvider(editId).notifier);
    final variants = state.variants;

    final Widget body;
    if (unavailable) {
      body = const MessageView(
        icon: CupertinoIcons.square_on_square,
        title: 'Variants are unavailable',
        message: 'Creating variants is not available right now.',
      );
    } else if (state.isLoading) {
      body = const LoadingView();
    } else if (variants == null) {
      body = MessageView(
        icon: CupertinoIcons.exclamationmark_circle,
        title: "Couldn't load variants",
        message: state.loadError?.userMessage ?? 'Please try again.',
        actionLabel: 'Try again',
        onAction: controller.retryLoad,
      );
    } else if (variants.isEmpty) {
      body = _EmptyVariants(state: state, controller: controller);
    } else {
      body = _VariantList(variants: variants, state: state, controller: controller);
    }

    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            const ScreenHeader(title: 'Variants'),
            if (variants != null && variants.isEmpty && state.createError != null)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.gutter),
                child: Text(
                  state.createError!.userMessage,
                  style: AppTypography.caption.copyWith(color: AppColors.destructive),
                ),
              ),
            Expanded(child: body),
          ],
        ),
      ),
    );
  }
}

class _VariantList extends StatelessWidget {
  const _VariantList({required this.variants, required this.state, required this.controller});

  final List<EditJob> variants;
  final VariantsState state;
  final VariantsController controller;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Expanded(
          child: ListView.separated(
            padding: const EdgeInsets.all(AppSpacing.gutter),
            itemCount: variants.length,
            separatorBuilder: (_, _) => const SizedBox(height: AppSpacing.sm),
            itemBuilder: (context, i) => VariantCard(variant: variants[i]),
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
                  if (state.createError != null) ...[
                    Text(
                      state.createError!.userMessage,
                      style: AppTypography.caption.copyWith(color: AppColors.destructive),
                    ),
                    const SizedBox(height: AppSpacing.xs),
                  ],
                  _CountPicker(state: state, controller: controller),
                  const SizedBox(height: AppSpacing.xs),
                  PrimaryButton(
                    label: 'Create more variants',
                    isLoading: state.isCreating,
                    onPressed: controller.createMore,
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

/// One hook variant: preview, direction, duration, status, and actions once it is ready.
class VariantCard extends ConsumerStatefulWidget {
  const VariantCard({super.key, required this.variant});

  final EditJob variant;

  @override
  ConsumerState<VariantCard> createState() => _VariantCardState();
}

class _VariantCardState extends ConsumerState<VariantCard> {
  bool _exporting = false;

  double get _ratio {
    final parts = AdFormat.fromId(widget.variant.aspectRatio).id.split(':');
    return double.parse(parts[0]) / double.parse(parts[1]);
  }

  Future<void> _preview() {
    return showAppSheet<void>(
      context,
      title: widget.variant.variant?.label ?? 'Variant',
      builder: (_) => Padding(
        padding: const EdgeInsets.only(bottom: AppSpacing.sm),
        child: VideoResultPlayer(url: widget.variant.outputUrl!, aspectRatio: _ratio),
      ),
    );
  }

  Future<void> _export() async {
    if (_exporting) return;
    setState(() => _exporting = true);
    try {
      await ref
          .read(exportServiceProvider)
          .export(url: widget.variant.outputUrl!, fileName: 'adcut-${widget.variant.id}.mp4');
    } on ApiException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.userMessage)));
      }
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
    final v = widget.variant;
    final ready = v.isDone;
    final details = [
      if (v.durationSeconds != null) Format.duration(v.durationSeconds!) else '${v.durationTargetSeconds} sec target',
    ].join(' · ');
    return DecoratedBox(
      decoration: const BoxDecoration(color: AppColors.surface, borderRadius: AppRadius.mediumAll),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.sm),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                RemoteThumbnail(url: v.thumbnailUrl, width: 72, height: 96),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(v.variant?.label ?? 'Variant', style: AppTypography.heading),
                      const SizedBox(height: AppSpacing.xxs),
                      Text(details, style: AppTypography.caption),
                      const SizedBox(height: AppSpacing.xs),
                      StatusTag(status: v.status),
                    ],
                  ),
                ),
              ],
            ),
            if (v.status.isActive) ...[
              const SizedBox(height: AppSpacing.sm),
              Text(v.displayStage ?? 'Waiting to start', style: AppTypography.caption),
              const SizedBox(height: AppSpacing.xs),
              AppProgressBar(value: v.progress > 0 ? v.progressFraction : null, semanticLabel: 'Variant progress'),
            ] else if (v.status == EditStatus.failed) ...[
              const SizedBox(height: AppSpacing.sm),
              Text(
                v.error?.message.isNotEmpty == true ? v.error!.message : "We couldn't finish this variant.",
                style: AppTypography.caption,
              ),
            ],
            if (ready) ...[
              const SizedBox(height: AppSpacing.sm),
              Row(
                children: [
                  Expanded(
                    child: SecondaryButton(
                      label: 'Preview',
                      leadingIcon: CupertinoIcons.play_fill,
                      onPressed: _preview,
                    ),
                  ),
                  const SizedBox(width: AppSpacing.xs),
                  Expanded(
                    child: SecondaryButton(
                      label: 'Export',
                      leadingIcon: CupertinoIcons.share,
                      isLoading: _exporting,
                      onPressed: _export,
                    ),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _CountPicker extends StatelessWidget {
  const _CountPicker({required this.state, required this.controller});

  final VariantsState state;
  final VariantsController controller;

  @override
  Widget build(BuildContext context) => SegmentedChoice<int>(
    label: 'Number of variants',
    value: state.count,
    choices: const [
      Choice(value: 3, label: '3 variants'),
      Choice(value: 5, label: '5 variants'),
    ],
    onChanged: controller.setCount,
  );
}

class _EmptyVariants extends StatelessWidget {
  const _EmptyVariants({required this.state, required this.controller});

  final VariantsState state;
  final VariantsController controller;

  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.all(AppSpacing.gutter),
    children: [
      const Text('What do you want to test?', style: AppTypography.display),
      const SizedBox(height: AppSpacing.sm),
      const Text(
        'Each variant opens with a different hook. Everything after the hook stays the same.',
        style: AppTypography.bodySecondary,
      ),
      const SizedBox(height: AppSpacing.xl),
      _CountPicker(state: state, controller: controller),
      if (state.createError != null) ...[
        const SizedBox(height: AppSpacing.sm),
        Text(state.createError!.userMessage, style: AppTypography.caption.copyWith(color: AppColors.destructive)),
      ],
      const SizedBox(height: AppSpacing.lg),
      PrimaryButton(label: 'Create variants', isLoading: state.isCreating, onPressed: controller.createMore),
    ],
  );
}
