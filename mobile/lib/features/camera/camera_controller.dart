import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/intents/edit_intent.dart';
import '../clean/clean_controller.dart';
import '../clean/footage_picker.dart';
import 'camera_gateway.dart';

enum CameraPhase { opening, ready, recording, saving, permissionDenied, unavailable, failed }

class CameraState {
  const CameraState({
    this.phase = CameraPhase.opening,
    this.elapsed = Duration.zero,
    this.front = false,
    this.torch = false,
    this.canFlip = false,
    this.hasTorch = false,
  });

  final CameraPhase phase;
  final Duration elapsed;
  final bool front;
  final bool torch;
  final bool canFlip;
  final bool hasTorch;

  bool get isRecording => phase == CameraPhase.recording;
  bool get canRecord => phase == CameraPhase.ready;

  CameraState copyWith({
    CameraPhase? phase,
    Duration? elapsed,
    bool? front,
    bool? torch,
    bool? canFlip,
    bool? hasTorch,
  }) => CameraState(
    phase: phase ?? this.phase,
    elapsed: elapsed ?? this.elapsed,
    front: front ?? this.front,
    torch: torch ?? this.torch,
    canFlip: canFlip ?? this.canFlip,
    hasTorch: hasTorch ?? this.hasTorch,
  );
}

/// Recording length cap: keeps files well under the upload limit.
const maxRecording = Duration(minutes: 5);

/// Drives the camera screen: open, record, stop, and hand the file to Clean.
class CameraSession extends Notifier<CameraState> {
  Timer? _ticker;
  final Stopwatch _clock = Stopwatch();
  late final CameraGateway _camera;
  Future<void>? _opening;

  @override
  CameraState build() {
    // Watching (rather than reading) keeps the auto-disposed hardware gateway
    // alive for the entire camera session. Otherwise it can be disposed between
    // initialization and the first preview frame on slower Android devices.
    _camera = ref.watch(cameraGatewayProvider);
    ref.onDispose(() => _ticker?.cancel());
    return const CameraState();
  }

  Future<void> open({bool? front}) async {
    // Lifecycle callbacks can race the initial Android permission dialog. Share
    // the in-flight open instead of closing and reopening the camera underneath it.
    final inFlight = _opening;
    if (inFlight != null) return inFlight;

    final useFront = front ?? state.front;
    state = state.copyWith(phase: CameraPhase.opening, front: useFront, torch: false);
    final operation = _openCamera(useFront);
    _opening = operation;
    try {
      await operation;
    } finally {
      if (identical(_opening, operation)) _opening = null;
    }
  }

  Future<void> _openCamera(bool useFront) async {
    try {
      await _camera.open(front: useFront);
      if (!ref.mounted) return;
      state = state.copyWith(phase: CameraPhase.ready, canFlip: _camera.canFlip, hasTorch: _camera.hasTorch);
    } on CameraFailure catch (e) {
      if (!ref.mounted) return;
      state = state.copyWith(
        phase: switch (e.kind) {
          CameraFailureKind.permissionDenied => CameraPhase.permissionDenied,
          CameraFailureKind.unavailable => CameraPhase.unavailable,
          CameraFailureKind.failed => CameraPhase.failed,
        },
      );
    }
  }

  Future<void> flip() async {
    if (!state.canRecord || !state.canFlip) return;
    await open(front: !state.front);
  }

  Future<void> toggleTorch() async {
    if (!state.hasTorch || state.phase == CameraPhase.opening) return;
    final next = !state.torch;
    try {
      await _camera.setTorch(next);
      state = state.copyWith(torch: next);
    } on CameraFailure {
      state = state.copyWith(torch: false);
    }
  }

  Future<void> startRecording() async {
    if (!state.canRecord) return;
    try {
      await _camera.startRecording();
    } on CameraFailure {
      state = state.copyWith(phase: CameraPhase.failed);
      return;
    }
    _clock
      ..reset()
      ..start();
    state = state.copyWith(phase: CameraPhase.recording, elapsed: Duration.zero);
    _ticker = Timer.periodic(const Duration(milliseconds: 250), (_) {
      if (!state.isRecording) return;
      state = state.copyWith(elapsed: _clock.elapsed);
      if (_clock.elapsed >= maxRecording) unawaited(stopAndClean());
    });
  }

  /// Stops recording and starts cleaning the file. Returns true when a clean was started.
  Future<bool> stopAndClean() async {
    if (!state.isRecording) return false;
    _ticker?.cancel();
    _clock.stop();
    final length = _clock.elapsed;
    state = state.copyWith(phase: CameraPhase.saving, elapsed: length);
    try {
      final video = await _camera.stopRecording();
      if (video.sizeBytes <= 0) {
        state = state.copyWith(phase: CameraPhase.failed);
        return false;
      }
      unawaited(
        ref
            .read(cleanControllerProvider.notifier)
            .start(
              PickedFootage(path: video.path, name: video.path.split(RegExp(r'[\/]')).last, sizeBytes: video.sizeBytes),
              intent: EditIntent.recordClean,
              rawSeconds: length.inMilliseconds / 1000,
            ),
      );
      return true;
    } on CameraFailure {
      state = state.copyWith(phase: CameraPhase.failed);
      return false;
    }
  }

  /// The app left the foreground: keep what was recorded rather than losing it, then free the camera.
  Future<bool> handleInterruption() async {
    if (state.isRecording) return stopAndClean();
    // A system permission sheet can pause Android while open() is still
    // initializing. Let that operation finish instead of disposing it midway.
    if (state.phase == CameraPhase.opening || state.phase == CameraPhase.saving) return false;
    await _camera.close();
    if (ref.mounted && state.phase == CameraPhase.ready) {
      state = state.copyWith(phase: CameraPhase.opening, torch: false);
    }
    return false;
  }
}

final cameraSessionProvider = NotifierProvider.autoDispose<CameraSession, CameraState>(CameraSession.new);
