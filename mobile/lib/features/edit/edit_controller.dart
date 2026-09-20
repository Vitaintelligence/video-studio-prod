import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import '../../app/providers.dart';
import '../../core/api/api_exception.dart';
import '../../core/models/api_models.dart';
import '../../core/polling/poller.dart';

class EditState {
  const EditState({
    this.job,
    this.loadError,
    this.isReconnecting = false,
    this.selectedVersionId,
    this.isSendingInstruction = false,
    this.isCancelling = false,
    this.instructionError,
  });

  /// Latest server view of the job being watched (the original edit or its active revision).
  final EditJob? job;
  final ApiException? loadError;
  final bool isReconnecting;
  final String? selectedVersionId;
  final bool isSendingInstruction;
  final bool isCancelling;
  final ApiException? instructionError;

  bool get isLoading => job == null && loadError == null;

  List<EditRevision> get versions => job?.versions ?? const [];

  List<EditRevision> get completedVersions => [
    for (final v in versions)
      if (v.status == EditStatus.completed && v.outputUrl != null) v,
  ];

  /// A version currently being produced (queued/starting/running), if any.
  EditRevision? get activeVersion {
    for (final v in versions.reversed) {
      if (v.status.isActive) return v;
    }
    return null;
  }

  /// The most recent version that failed or was cancelled, only if it is newer than every completed one.
  EditRevision? get latestFailedVersion {
    if (versions.isEmpty) return null;
    final last = versions.last;
    return last.status == EditStatus.failed || last.status == EditStatus.cancelled ? last : null;
  }

  /// Version shown in the player: the user's pick, else the newest completed one.
  EditRevision? get shownVersion {
    final done = completedVersions;
    if (done.isEmpty) return null;
    for (final v in done) {
      if (v.id == selectedVersionId) return v;
    }
    return done.last;
  }

  bool get isProcessing => activeVersion != null || (job?.status.isActive ?? false);

  EditState copyWith({
    EditJob? job,
    ApiException? loadError,
    bool clearLoadError = false,
    bool? isReconnecting,
    String? selectedVersionId,
    bool clearSelection = false,
    bool? isSendingInstruction,
    bool? isCancelling,
    ApiException? instructionError,
    bool clearInstructionError = false,
  }) => EditState(
    job: job ?? this.job,
    loadError: clearLoadError ? null : (loadError ?? this.loadError),
    isReconnecting: isReconnecting ?? this.isReconnecting,
    selectedVersionId: clearSelection ? null : (selectedVersionId ?? this.selectedVersionId),
    isSendingInstruction: isSendingInstruction ?? this.isSendingInstruction,
    isCancelling: isCancelling ?? this.isCancelling,
    instructionError: clearInstructionError ? null : (instructionError ?? this.instructionError),
  );
}

/// Watches one edit (by its original edit id) and its revisions. Polls the backend only while
/// something is running; polling stops when the job settles or the screen goes away.
class EditController extends Notifier<EditState> {
  EditController(this.editId);

  final String editId;
  final Uuid _uuid = const Uuid();
  late final Poller _poller;
  String _watchedId = '';
  String? _instructionKey;
  String? _instructionText;

  @override
  EditState build() {
    _watchedId = editId;
    _poller = Poller(task: _tick, interval: ref.read(pollIntervalProvider));
    ref.onDispose(_poller.stop);
    _poller.start();
    return const EditState();
  }

  Future<bool> _tick() async {
    try {
      final job = await ref.read(apiProvider).getEdit(_watchedId);
      final active = _activeIdOf(job);
      if (active != null) _watchedId = active;
      state = state.copyWith(job: job, clearLoadError: true, isReconnecting: false);
      return active != null || job.status.isActive;
    } on ApiException catch (e) {
      if (e.isTransient) {
        // Keep whatever we had; keep trying quietly.
        state = state.copyWith(isReconnecting: state.job != null, loadError: state.job == null ? e : null);
        rethrow;
      }
      state = state.copyWith(loadError: e, isReconnecting: false);
      return false;
    }
  }

  /// Id of the newest still-running version other than the watched job's own terminal state.
  String? _activeIdOf(EditJob job) {
    for (final v in job.versions.reversed) {
      if (v.status.isActive) return v.id;
    }
    return job.status.isActive && job.versions.isEmpty ? job.id : null;
  }

  Future<void> retryLoad() async {
    state = state.copyWith(clearLoadError: true);
    _poller.start();
  }

  void selectVersion(String id) => state = state.copyWith(selectedVersionId: id);

  /// Prompt-to-edit: creates a new version. The previous completed version stays available.
  Future<bool> sendInstruction(String instruction) async {
    final text = instruction.trim();
    if (state.isSendingInstruction || text.length < 4 || state.isProcessing) {
      return false;
    }
    state = state.copyWith(isSendingInstruction: true, clearInstructionError: true);
    if (_instructionText != text || _instructionKey == null) {
      _instructionText = text;
      _instructionKey = _uuid.v4();
    }
    try {
      final accepted = await ref.read(apiProvider).addInstruction(editId, text, idempotencyKey: _instructionKey!);
      _instructionKey = null;
      _instructionText = null;
      _watchedId = accepted.id;
      state = state.copyWith(isSendingInstruction: false, clearSelection: true);
      _poller.start();
      return true;
    } on ApiException catch (e) {
      state = state.copyWith(isSendingInstruction: false, instructionError: e);
      return false;
    }
  }

  Future<void> cancel() async {
    if (state.isCancelling) return;
    state = state.copyWith(isCancelling: true);
    try {
      final job = await ref.read(apiProvider).cancelEdit(_watchedId);
      state = state.copyWith(job: job, isCancelling: false);
      _poller.start();
    } on ApiException catch (e) {
      state = state.copyWith(isCancelling: false, instructionError: e);
    }
  }
}

final editControllerProvider = NotifierProvider.autoDispose.family<EditController, EditState, String>(
  EditController.new,
);
