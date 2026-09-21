import 'dart:io';

import 'package:flutter/cupertino.dart';
import 'package:video_player/video_player.dart';

import '../../core/design/app_colors.dart';
import '../../core/design/app_radius.dart';
import '../../core/design/app_spacing.dart';
import '../../core/design/app_typography.dart';
import '../../core/format.dart';
import '../../core/widgets/buttons.dart';

/// Plays a finished edit with minimal chrome: tap to play/pause and a scrubbable progress bar.
class VideoResultPlayer extends StatefulWidget {
  const VideoResultPlayer({
    super.key,
    required this.source,
    required this.aspectRatio,
    this.startAt,
    this.stopAt,
    this.autoPlay = false,
    this.onDownload,
    this.downloadProgress,
  });

  /// An http(s) URL, or a local file path.
  final String source;

  /// width / height of the output (e.g. 9 / 16).
  final double aspectRatio;
  final double? startAt;
  final double? stopAt;
  final bool autoPlay;
  final VoidCallback? onDownload;
  final double? downloadProgress;

  @override
  State<VideoResultPlayer> createState() => _VideoResultPlayerState();
}

class _VideoResultPlayerState extends State<VideoResultPlayer> {
  VideoPlayerController? _controller;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _open();
  }

  @override
  void didUpdateWidget(VideoResultPlayer old) {
    super.didUpdateWidget(old);
    if (old.source != widget.source || old.startAt != widget.startAt || old.stopAt != widget.stopAt) _open();
  }

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  Future<void> _open() async {
    final previous = _controller;
    final controller = widget.source.startsWith('http')
        ? VideoPlayerController.networkUrl(Uri.parse(widget.source))
        : VideoPlayerController.file(File(widget.source));
    _controller = controller;
    _failed = false;
    if (previous != null) {
      setState(() {});
      await previous.dispose();
    }
    try {
      await controller.initialize();
      await controller.setLooping(widget.stopAt == null);
      if (widget.startAt != null) await controller.seekTo(Duration(milliseconds: (widget.startAt! * 1000).round()));
      controller.addListener(_enforceClipEnd);
      if (widget.autoPlay) await controller.play();
      if (mounted && _controller == controller) setState(() {});
    } on Object {
      if (mounted && _controller == controller) setState(() => _failed = true);
    }
  }

  void _enforceClipEnd() {
    final controller = _controller;
    final stop = widget.stopAt;
    if (controller == null || stop == null || !controller.value.isPlaying) return;
    if (controller.value.position.inMilliseconds >= (stop * 1000).round()) controller.pause();
  }

  Future<void> _toggle(VideoPlayerController c) async {
    if (c.value.isPlaying) {
      await c.pause();
      return;
    }
    final stop = widget.stopAt;
    if (stop != null && c.value.position.inMilliseconds >= (stop * 1000).round() - 80) {
      await c.seekTo(Duration(milliseconds: ((widget.startAt ?? 0) * 1000).round()));
    }
    await c.play();
  }

  @override
  Widget build(BuildContext context) {
    final controller = _controller;
    final ready = controller != null && controller.value.isInitialized && !_failed;
    return LayoutBuilder(
      builder: (context, constraints) {
        final largeText = MediaQuery.textScalerOf(context).scale(1) > 1.2;
        final maxHeight = MediaQuery.sizeOf(context).height * (largeText ? 0.36 : 0.48);
        final height = (constraints.maxWidth / widget.aspectRatio).clamp(0.0, maxHeight);
        return ClipRRect(
          borderRadius: AppRadius.largeAll,
          child: ColoredBox(
            color: AppColors.videoBackdrop,
            child: SizedBox(
              height: height,
              width: double.infinity,
              child: _failed
                  ? _PlayerError(onRetry: _open)
                  : !ready
                  ? const Center(child: CupertinoActivityIndicator(radius: 12))
                  : _PlayerSurface(
                      controller: controller,
                      onToggle: () => _toggle(controller),
                      clipStart: widget.startAt,
                      clipEnd: widget.stopAt,
                      onDownload: widget.onDownload,
                      downloadProgress: widget.downloadProgress,
                    ),
            ),
          ),
        );
      },
    );
  }
}

class _PlayerSurface extends StatelessWidget {
  const _PlayerSurface({
    required this.controller,
    required this.onToggle,
    required this.clipStart,
    required this.clipEnd,
    required this.onDownload,
    required this.downloadProgress,
  });

  final VideoPlayerController controller;
  final VoidCallback onToggle;
  final double? clipStart;
  final double? clipEnd;
  final VoidCallback? onDownload;
  final double? downloadProgress;

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<VideoPlayerValue>(
      valueListenable: controller,
      builder: (context, value, _) {
        final clip = clipStart != null && clipEnd != null && clipEnd! > clipStart!;
        final shownPosition = clip
            ? (value.position.inMilliseconds / 1000 - clipStart!).clamp(0, clipEnd! - clipStart!)
            : value.position.inMilliseconds / 1000;
        final shownDuration = clip ? clipEnd! - clipStart! : value.duration.inMilliseconds / 1000;
        return Semantics(
          button: true,
          label: value.isPlaying ? 'Pause video' : 'Play video',
          excludeSemantics: true,
          onTap: onToggle,
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: onToggle,
            child: Stack(
              fit: StackFit.expand,
              children: [
                Center(
                  child: AspectRatio(aspectRatio: value.aspectRatio, child: VideoPlayer(controller)),
                ),
                if (!value.isPlaying)
                  const Center(child: Icon(CupertinoIcons.play_circle_fill, size: 64, color: AppColors.textPrimary)),
                if (onDownload != null || downloadProgress != null)
                  Positioned(
                    top: AppSpacing.sm,
                    right: AppSpacing.sm,
                    child: Semantics(
                      button: true,
                      enabled: onDownload != null,
                      label: downloadProgress != null ? 'Saving video' : 'Save video',
                      excludeSemantics: true,
                      onTap: onDownload,
                      child: GestureDetector(
                        behavior: HitTestBehavior.opaque,
                        onTap: onDownload,
                        child: Container(
                          width: 44,
                          height: 44,
                          decoration: BoxDecoration(
                            color: AppColors.scrim,
                            borderRadius: AppRadius.pillAll,
                            border: Border.all(color: AppColors.surfaceBorder),
                          ),
                          child: downloadProgress != null
                              ? const CupertinoActivityIndicator(color: AppColors.textPrimary)
                              : const Icon(CupertinoIcons.arrow_down_to_line, size: 21, color: AppColors.textPrimary),
                        ),
                      ),
                    ),
                  ),
                Positioned(
                  left: AppSpacing.sm,
                  right: AppSpacing.sm,
                  bottom: AppSpacing.xs,
                  child: Row(
                    children: [
                      Text(
                        Format.duration(shownPosition.toDouble()),
                        style: AppTypography.caption.copyWith(color: AppColors.textPrimary),
                      ),
                      const SizedBox(width: AppSpacing.xs),
                      Expanded(
                        child: clip
                            ? CupertinoSlider(
                                value: (value.position.inMilliseconds / 1000).clamp(clipStart!, clipEnd!),
                                min: clipStart!,
                                max: clipEnd!,
                                activeColor: AppColors.accentText,
                                onChanged: (seconds) =>
                                    controller.seekTo(Duration(milliseconds: (seconds * 1000).round())),
                              )
                            : VideoProgressIndicator(
                                controller,
                                allowScrubbing: true,
                                padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
                                colors: const VideoProgressColors(
                                  playedColor: AppColors.accentText,
                                  bufferedColor: AppColors.surfacePressed,
                                  backgroundColor: AppColors.surfaceRaised,
                                ),
                              ),
                      ),
                      const SizedBox(width: AppSpacing.xs),
                      Text(
                        Format.duration(shownDuration),
                        style: AppTypography.caption.copyWith(color: AppColors.textPrimary),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

class _PlayerError extends StatelessWidget {
  const _PlayerError({required this.onRetry});

  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text("This video couldn't be played.", style: AppTypography.bodySecondary),
          TertiaryButton(label: 'Try again', onPressed: onRetry),
        ],
      ),
    );
  }
}
