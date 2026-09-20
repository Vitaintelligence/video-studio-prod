import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import '../../core/models/api_models.dart';
import '../../core/polling/poller.dart';

/// The user's real projects from the backend, newest first. Refreshes itself while any edit is running.
class ProjectsController extends AsyncNotifier<List<ApiProject>> {
  late Poller _poller;

  @override
  Future<List<ApiProject>> build() async {
    // A notifier instance survives rebuilds (invalidate), so the poller is recreated each time.
    _poller = Poller(
      task: _poll,
      interval: ref.read(pollIntervalProvider) * 2,
      maxInterval: const Duration(seconds: 30),
    );
    ref.onDispose(_poller.stop);
    final projects = await ref.watch(apiProvider).listProjects();
    _syncPolling(projects);
    return projects;
  }

  Future<void> refresh() async {
    final projects = await AsyncValue.guard(() => ref.read(apiProvider).listProjects());
    projects.whenData(_syncPolling);
    // Keep showing the previous list if a refresh fails after a successful load.
    if (projects.hasError && state.hasValue) return;
    state = projects;
  }

  Future<bool> _poll() async {
    final projects = await ref.read(apiProvider).listProjects();
    state = AsyncData(projects);
    return _hasRunning(projects);
  }

  void _syncPolling(List<ApiProject> projects) {
    if (_hasRunning(projects)) {
      _poller.start();
    } else {
      _poller.stop();
    }
  }

  bool _hasRunning(List<ApiProject> projects) => projects.any((p) => p.latestEdit?.status.isActive ?? false);
}

final projectsProvider = AsyncNotifierProvider<ProjectsController, List<ApiProject>>(ProjectsController.new);
