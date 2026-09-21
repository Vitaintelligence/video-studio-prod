import 'dart:async';
import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/intents/edit_intent.dart';
import '../clean/clean_controller.dart';
import '../clean/footage_picker.dart';
import 'camera_gateway.dart';

enum CameraPhase { opening, ready, countdown, recording, saving, permissionDenied, unavailable, failed }

class CameraState {
  const CameraState({
    this.phase = CameraPhase.opening,
    this.elapsed = Duration.zero,
    this.front = false,
    this.torch = false,
    this.canFlip = false,
    this.hasTorch = false,
    this.countdown = 0,
  });

  final CameraPhase phase;
  final Duration elapsed;
  final bool front;
  final bool torch;
  final bool canFlip;
  final bool hasTorch;

  /// Seconds left before recording starts (only during [CameraPhase.countdown]).
  final int countdown;

  bool get isRecording => phase == CameraPhase.recording;
  bool get canRecord => phase == CameraPhase.ready;
  bool get isCountingDown => phase == CameraPhase.countdown;

  CameraState copyWith({
    int? countdown,
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
    countdown: countdown ?? this.countdown,
  );
}

/// Seconds of "get ready" before recording starts. Overridden in tests.
final recordingCountdownProvider = Provider<int>((ref) => 3);

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
    // Keep the auto-disposed hardware gateway alive for the whole camera
    // session, including slow Android permission and initialization flows.
    _camera = ref.watch(cameraGatewayProvider);
    ref.onDispose(() => _ticker?.cancel());
    return const CameraState();
  }

  Future<void> open({bool? front}) async {
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

  Object? _countdownToken;

  /// Counts down (cancellable), then starts recording.
  Future<void> startRecording() async {
    if (!state.canRecord) return;
    final token = _countdownToken = Object();
    for (var n = ref.read(recordingCountdownProvider); n > 0; n--) {
      state = state.copyWith(phase: CameraPhase.countdown, countdown: n);
      await Future<void>.delayed(const Duration(seconds: 1));
      if (!ref.mounted || _countdownToken != token) return;
    }
    _countdownToken = null;
    try {
      await _camera.startRecording();
    } on CameraFailure {
      if (ref.mounted) state = state.copyWith(phase: CameraPhase.failed);
      return;
    }
    if (!ref.mounted) return;
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

  void cancelCountdown() {
    if (!state.isCountingDown) return;
    _countdownToken = null;
    state = state.copyWith(phase: CameraPhase.ready, countdown: 0);
  }

  /// Throws away the take in progress and returns to the ready state for another try.
  Future<void> retake() async {
    if (!state.isRecording) return;
    _ticker?.cancel();
    _clock.stop();
    state = state.copyWith(phase: CameraPhase.saving);
    try {
      final video = await _camera.stopRecording();
      final file = File(video.path);
      if (file.existsSync()) await file.delete();
      state = state.copyWith(phase: CameraPhase.ready, elapsed: Duration.zero);
    } on CameraFailure {
      state = state.copyWith(phase: CameraPhase.failed);
    }
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
      if (!ref.mounted) return false;
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
    _countdownToken = null;
    // A system permission sheet can pause Android while open() is still
    // initializing. Disposing at that point leaves the plugin half-open.
    if (state.phase == CameraPhase.opening || state.phase == CameraPhase.saving) return false;
    await _camera.close();
    if (ref.mounted) state = state.copyWith(phase: CameraPhase.opening, countdown: 0, torch: false);
    return false;
  }
}

final cameraSessionProvider = NotifierProvider.autoDispose<CameraSession, CameraState>(CameraSession.new);
