import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import '../../app/providers.dart';
import '../../core/api/api_exception.dart';
import '../../core/models/api_models.dart';
import '../../core/polling/poller.dart';

class VariantsState {
  const VariantsState({this.variants, this.loadError, this.isCreating = false, this.createError, this.count = 3});

  final List<EditJob>? variants;
  final ApiException? loadError;
  final bool isCreating;
  final ApiException? createError;

  /// How many hook variants the next request asks for (3 or 5).
  final int count;

  bool get isLoading => variants == null && loadError == null;
  bool get hasRunning => variants?.any((v) => v.status.isActive) ?? false;

  VariantsState copyWith({
    List<EditJob>? variants,
    ApiException? loadError,
    bool clearLoadError = false,
    bool? isCreating,
    ApiException? createError,
    bool clearCreateError = false,
    int? count,
  }) => VariantsState(
    variants: variants ?? this.variants,
    loadError: clearLoadError ? null : (loadError ?? this.loadError),
    isCreating: isCreating ?? this.isCreating,
    createError: clearCreateError ? null : (createError ?? this.createError),
    count: count ?? this.count,
  );
}

/// Hook variants of one edit. Polls only while a variant is still being produced.
class VariantsController extends Notifier<VariantsState> {
  VariantsController(this.editId);

  final String editId;
  final Uuid _uuid = const Uuid();
  late final Poller _poller;
  String? _requestKey;

  @override
  VariantsState build() {
    _poller = Poller(task: _tick, interval: ref.read(pollIntervalProvider));
    ref.onDispose(_poller.stop);
    _poller.start();
    return const VariantsState();
  }

  Future<bool> _tick() async {
    try {
      final items = await ref.read(apiProvider).listVariants(editId);
      state = state.copyWith(variants: items, clearLoadError: true);
      return state.hasRunning;
    } on ApiException catch (e) {
      if (e.isTransient) {
        if (state.variants == null) state = state.copyWith(loadError: e);
        rethrow;
      }
      state = state.copyWith(loadError: e);
      return false;
    }
  }

  void retryLoad() {
    state = state.copyWith(clearLoadError: true);
    _poller.start();
  }

  /// Asks for more hook variants. The idempotency key is reused if the same request is retried.
  void setCount(int value) => state = state.copyWith(count: value);

  Future<void> createMore() async {
    if (state.isCreating) return;
    state = state.copyWith(isCreating: true, clearCreateError: true);
    _requestKey ??= _uuid.v4();
    try {
      await ref.read(apiProvider).createVariants(editId, count: state.count, idempotencyKey: _requestKey!);
      _requestKey = null;
      state = state.copyWith(isCreating: false);
      _poller.start();
    } on ApiException catch (e) {
      state = state.copyWith(isCreating: false, createError: e);
    }
  }
}

final variantsControllerProvider = NotifierProvider.autoDispose.family<VariantsController, VariantsState, String>(
  VariantsController.new,
);
