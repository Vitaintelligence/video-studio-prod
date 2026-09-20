import 'dart:async';

/// Repeats [task] until it reports it is finished or the poller is stopped.
///
/// [task] returns `true` to keep polling, `false` to stop. If it throws, the poller backs off
/// (doubling up to [maxInterval]) and keeps going, so a network drop never ends monitoring.
class Poller {
  Poller({
    required this.task,
    this.interval = const Duration(seconds: 2),
    this.maxInterval = const Duration(seconds: 10),
  });

  final Future<bool> Function() task;
  final Duration interval;
  final Duration maxInterval;

  Timer? _timer;
  bool _stopped = true;
  Duration _current = Duration.zero;

  bool get isRunning => !_stopped;

  /// Starts polling with an immediate first run. No-op if already running.
  void start() {
    if (!_stopped) return;
    _stopped = false;
    _current = interval;
    _schedule(Duration.zero);
  }

  void stop() {
    _stopped = true;
    _timer?.cancel();
    _timer = null;
  }

  void _schedule(Duration delay) {
    _timer?.cancel();
    _timer = Timer(delay, _run);
  }

  Future<void> _run() async {
    if (_stopped) return;
    var keepGoing = true;
    try {
      keepGoing = await task();
      _current = interval;
    } on Object {
      final doubled = _current * 2;
      _current = doubled > maxInterval ? maxInterval : doubled;
    }
    if (_stopped) return;
    if (!keepGoing) {
      stop();
      return;
    }
    _schedule(_current);
  }
}
