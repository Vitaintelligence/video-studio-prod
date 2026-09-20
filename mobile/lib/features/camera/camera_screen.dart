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
import '../../core/widgets/buttons.dart';
import '../../core/widgets/state_views.dart';
import 'camera_controller.dart';
import 'camera_gateway.dart';

/// Full-screen recorder: live preview, one record/stop control, and only controls that work.
class CameraScreen extends ConsumerStatefulWidget {
  const CameraScreen({super.key});

  @override
  ConsumerState<CameraScreen> createState() => _CameraScreenState();
}

class _CameraScreenState extends ConsumerState<CameraScreen> with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) => ref.read(cameraSessionProvider.notifier).open());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState lifecycle) {
    final session = ref.read(cameraSessionProvider.notifier);
    // Not `inactive`: the system permission prompt also makes the app inactive.
    if (lifecycle == AppLifecycleState.paused) {
      session.handleInterruption().then((started) {
        if (started && mounted) context.pushReplacement(Routes.upload);
      });
    } else if (lifecycle == AppLifecycleState.resumed) {
      final phase = ref.read(cameraSessionProvider).phase;
      if (phase == CameraPhase.opening || phase == CameraPhase.ready) session.open();
    }
  }

  Future<void> _toggleRecord() async {
    final session = ref.read(cameraSessionProvider.notifier);
    final state = ref.read(cameraSessionProvider);
    HapticFeedback.mediumImpact();
    if (state.isRecording) {
      final started = await session.stopAndClean();
      if (started && mounted) context.pushReplacement(Routes.upload);
    } else {
      await session.startRecording();
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(cameraSessionProvider);
    final session = ref.read(cameraSessionProvider.notifier);

    return Scaffold(
      backgroundColor: AppColors.videoBackdrop,
      body: SafeArea(
        child: switch (state.phase) {
          CameraPhase.permissionDenied => _Problem(
            title: 'Camera access is off',
            message: 'Turn on camera and microphone access for AdCut in Settings, then come back.',
            onRetry: session.open,
          ),
          CameraPhase.unavailable => _Problem(
            title: 'No camera found',
            message: 'This device has no usable camera. You can upload a video instead.',
            onRetry: null,
          ),
          CameraPhase.failed => _Problem(
            title: "Recording didn't work",
            message: 'Something went wrong with the camera. Try again.',
            onRetry: session.open,
          ),
          _ => Column(
            children: [
              _TopBar(state: state, onClose: () => context.pop(), onTorch: session.toggleTorch),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xs),
                  child: ClipRRect(
                    borderRadius: AppRadius.mediaAll,
                    child: ColoredBox(
                      color: AppColors.surface,
                      child: state.phase == CameraPhase.opening
                          ? const LoadingView(label: 'Starting camera')
                          : const SizedBox.expand(child: _Preview()),
                    ),
                  ),
                ),
              ),
              _Controls(state: state, onRecord: _toggleRecord, onFlip: session.flip),
            ],
          ),
        },
      ),
    );
  }
}

class _Preview extends ConsumerWidget {
  const _Preview();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final camera = ref.watch(cameraGatewayProvider);
    return camera.preview();
  }
}

class _TopBar extends StatelessWidget {
  const _TopBar({required this.state, required this.onClose, required this.onTorch});

  final CameraState state;
  final VoidCallback onClose;
  final VoidCallback onTorch;

  @override
  Widget build(BuildContext context) {
    final seconds = state.elapsed.inSeconds;
    final time = '${(seconds ~/ 60).toString().padLeft(2, '0')}:${(seconds % 60).toString().padLeft(2, '0')}';
    return SizedBox(
      height: 56,
      child: Row(
        children: [
          AppIconButton(
            icon: CupertinoIcons.xmark,
            label: 'Close camera',
            onPressed: state.isRecording ? null : onClose,
          ),
          Expanded(
            child: Center(
              child: Semantics(
                liveRegion: false,
                label: 'Recording time $time',
                child: Text(
                  state.isRecording || state.phase == CameraPhase.saving ? time : 'Ready',
                  style: AppTypography.heading.copyWith(
                    color: state.isRecording ? AppColors.destructive : AppColors.textPrimary,
                    fontFeatures: const [FontFeature.tabularFigures()],
                  ),
                ),
              ),
            ),
          ),
          state.hasTorch
              ? AppIconButton(
                  icon: state.torch ? CupertinoIcons.bolt_fill : CupertinoIcons.bolt_slash,
                  label: state.torch ? 'Turn light off' : 'Turn light on',
                  onPressed: onTorch,
                )
              : const SizedBox(width: AppSpacing.minTap),
        ],
      ),
    );
  }
}

class _Controls extends StatelessWidget {
  const _Controls({required this.state, required this.onRecord, required this.onFlip});

  final CameraState state;
  final VoidCallback onRecord;
  final VoidCallback onFlip;

  @override
  Widget build(BuildContext context) {
    final enabled = state.canRecord || state.isRecording;
    return SizedBox(
      height: 112,
      child: Row(
        children: [
          const Expanded(child: SizedBox()),
          Semantics(
            button: true,
            enabled: enabled,
            label: state.isRecording ? 'Stop recording' : 'Start recording',
            excludeSemantics: true,
            onTap: enabled ? onRecord : null,
            child: GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTap: enabled ? onRecord : null,
              child: SizedBox(
                width: 80,
                height: 80,
                child: Center(
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 150),
                    width: state.isRecording ? 40 : 72,
                    height: state.isRecording ? 40 : 72,
                    decoration: BoxDecoration(
                      color: enabled ? AppColors.destructive : AppColors.surfacePressed,
                      borderRadius: BorderRadius.circular(state.isRecording ? AppRadius.medium : 36),
                    ),
                  ),
                ),
              ),
            ),
          ),
          Expanded(
            child: state.canFlip && !state.isRecording
                ? AppIconButton(icon: CupertinoIcons.camera_rotate, label: 'Flip camera', onPressed: onFlip)
                : const SizedBox(),
          ),
        ],
      ),
    );
  }
}

class _Problem extends StatelessWidget {
  const _Problem({required this.title, required this.message, required this.onRetry});

  final String title;
  final String message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) => Column(
    children: [
      Align(
        alignment: Alignment.centerLeft,
        child: AppIconButton(icon: CupertinoIcons.xmark, label: 'Close camera', onPressed: () => context.pop()),
      ),
      Expanded(
        child: MessageView(
          icon: CupertinoIcons.camera,
          title: title,
          message: message,
          actionLabel: onRetry == null ? null : 'Try again',
          onAction: onRetry,
          secondaryLabel: 'Close',
          onSecondary: () => context.pop(),
        ),
      ),
    ],
  );
}
