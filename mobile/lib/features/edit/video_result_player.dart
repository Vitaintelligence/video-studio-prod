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
  const VideoResultPlayer({super.key, required this.source, required this.aspectRatio});

  /// An http(s) URL, or a local file path.
  final String source;

  /// width / height of the output (e.g. 9 / 16).
  final double aspectRatio;

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
    if (old.source != widget.source) _open();
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
      await controller.setLooping(true);
      if (mounted && _controller == controller) setState(() {});
    } on Object {
      if (mounted && _controller == controller) setState(() => _failed = true);
    }
  }

  void _toggle(VideoPlayerController c) {
    c.value.isPlaying ? c.pause() : c.play();
  }

  @override
  Widget build(BuildContext context) {
    final controller = _controller;
    final ready = controller != null && controller.value.isInitialized && !_failed;
    return LayoutBuilder(
      builder: (context, constraints) {
        final maxHeight = MediaQuery.sizeOf(context).height * 0.55;
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
                  : _PlayerSurface(controller: controller, onToggle: () => _toggle(controller)),
            ),
          ),
        );
      },
    );
  }
}

class _PlayerSurface extends StatelessWidget {
  const _PlayerSurface({required this.controller, required this.onToggle});

  final VideoPlayerController controller;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<VideoPlayerValue>(
      valueListenable: controller,
      builder: (context, value, _) {
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
                Positioned(
                  left: AppSpacing.sm,
                  right: AppSpacing.sm,
                  bottom: AppSpacing.xs,
                  child: Row(
                    children: [
                      Text(
                        Format.duration(value.position.inMilliseconds / 1000),
                        style: AppTypography.caption.copyWith(color: AppColors.textPrimary),
                      ),
                      const SizedBox(width: AppSpacing.xs),
                      Expanded(
                        child: VideoProgressIndicator(
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
                        Format.duration(value.duration.inMilliseconds / 1000),
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
