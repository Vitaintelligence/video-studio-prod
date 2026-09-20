import 'dart:async';
import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import '../../app/providers.dart';
import '../../core/api/api_client.dart';
import '../../core/api/api_config.dart';
import '../../core/api/api_exception.dart';
import '../../core/intents/edit_intent.dart';
import '../settings/settings_controller.dart';
import 'footage_picker.dart';

enum CleanPhase { idle, uploading, creating, failed, created }

class CleanState {
  const CleanState({
    this.phase = CleanPhase.idle,
    this.progress = 0,
    this.editId,
    this.error,
    this.footage,
    this.rawSeconds,
  });

  final CleanPhase phase;

  /// Upload progress 0..1, from bytes actually sent.
  final double progress;
  final String? editId;
  final ApiException? error;
  final PickedFootage? footage;

  /// Length of the raw recording, when known. Used to show time saved.
  final double? rawSeconds;

  bool get isBusy => phase == CleanPhase.uploading || phase == CleanPhase.creating;

  CleanState copyWith({
    CleanPhase? phase,
    double? progress,
    String? editId,
    ApiException? error,
    bool clearError = false,
  }) => CleanState(
    phase: phase ?? this.phase,
    progress: progress ?? this.progress,
    editId: editId ?? this.editId,
    error: clearError ? null : (error ?? this.error),
    footage: footage,
    rawSeconds: rawSeconds,
  );
}

String rawDurationKey(String editId) => 'raw_seconds.$editId';
String rawPathKey(String editId) => 'raw_path.$editId';

/// Record/Upload & Clean: uploads the footage, creates the clean edit, and hands back the job id.
/// Lives for the whole app session so an upload keeps going if the user leaves the screen.
class CleanController extends Notifier<CleanState> {
  final Uuid _uuid = const Uuid();
  UploadCancelToken? _cancel;
  String? _idempotencyKey;

  @override
  CleanState build() => const CleanState();

  /// Starts cleaning [footage]. Ignored while another clean is in progress (no double submit).
  Future<void> start(PickedFootage footage, {required EditIntent intent, double? rawSeconds}) async {
    if (state.isBusy) return;
    _idempotencyKey = _uuid.v4();
    state = CleanState(phase: CleanPhase.uploading, footage: footage, rawSeconds: rawSeconds);
    await _run(intent);
  }

  Future<void> retry() async {
    if (state.isBusy || state.footage == null) return;
    state = CleanState(phase: CleanPhase.uploading, footage: state.footage, rawSeconds: state.rawSeconds);
    await _run(EditIntent.uploadClean);
  }

  Future<void> _run(EditIntent intent) async {
    final footage = state.footage!;
    final invalid = _validate(footage);
    if (invalid != null) {
      state = state.copyWith(phase: CleanPhase.failed, error: invalid);
      return;
    }
    final token = UploadCancelToken();
    _cancel = token;
    try {
      final api = ref.read(apiProvider);
      final ext = footage.name.split('.').last.toLowerCase();
      final asset = await api.uploadFootage(
        file: File(footage.path),
        filename: footage.name,
        contentType: ApiConfig.contentTypeByExtension[ext] ?? 'video/mp4',
        cancel: token,
        onProgress: (sent, total) {
          if (ref.mounted && total > 0) state = state.copyWith(progress: sent / total);
        },
      );
      if (token.isCancelled || !ref.mounted) return;
      state = state.copyWith(phase: CleanPhase.creating, progress: 1);
      final settings = ref.read(settingsProvider);
      final accepted = await api.createEdit(
        assetIds: [asset.id],
        instruction: intent.cleanInstruction!,
        platform: settings.platform.id,
        aspectRatio: settings.format.id,
        idempotencyKey: _idempotencyKey!,
      );
      final raw = state.rawSeconds;
      final prefs = ref.read(preferencesProvider);
      if (raw != null) await prefs.setDouble(rawDurationKey(accepted.id), raw);
      await prefs.setString(rawPathKey(accepted.id), footage.path);
      if (!ref.mounted) return;
      state = state.copyWith(phase: CleanPhase.created, editId: accepted.id);
    } on ApiException catch (e) {
      if (!ref.mounted || token.isCancelled) return;
      state = state.copyWith(phase: CleanPhase.failed, error: e);
    } on FileSystemException {
      if (!ref.mounted) return;
      state = state.copyWith(
        phase: CleanPhase.failed,
        error: const ApiException.invalidMedia('We could not read that video.'),
      );
    } finally {
      _cancel = null;
    }
  }

  ApiException? _validate(PickedFootage f) {
    final ext = f.name.contains('.') ? f.name.split('.').last.toLowerCase() : '';
    if (!ApiConfig.allowedVideoExtensions.contains(ext)) {
      return const ApiException.invalidMedia('Use an MP4, MOV or M4V video.');
    }
    if (f.sizeBytes <= 0) return const ApiException.invalidMedia('That video is empty.');
    if (f.sizeBytes > ApiConfig.maxUploadBytes) {
      return const ApiException.invalidMedia('That video is over 500 MB. Try a shorter clip.');
    }
    return null;
  }

  /// Stops an upload in progress and clears the state.
  void cancel() {
    _cancel?.cancel();
    state = const CleanState();
  }

  /// Clears a finished or failed run so a new one can start.
  void reset() {
    if (!state.isBusy) state = const CleanState();
  }
}

final cleanControllerProvider = NotifierProvider<CleanController, CleanState>(CleanController.new);

/// Length of the raw recording behind an edit, if this device recorded or picked it.
final rawSecondsProvider = Provider.family<double?, String>(
  (ref, editId) => ref.watch(preferencesProvider).getDouble(rawDurationKey(editId)),
);

/// Path of the raw recording behind an edit, only while the file still exists on this device.
final rawPathProvider = Provider.family<String?, String>((ref, editId) {
  final path = ref.watch(preferencesProvider).getString(rawPathKey(editId));
  return path != null && File(path).existsSync() ? path : null;
});
