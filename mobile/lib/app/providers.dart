import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/api/adcut_api.dart';
import '../core/api/api_client.dart';
import '../core/models/api_models.dart';

/// Provided in `main()` (and overridden in tests).
final preferencesProvider = Provider<SharedPreferences>((ref) => throw UnimplementedError('preferencesProvider'));

final apiClientProvider = Provider<ApiClient>((ref) {
  final client = ApiClient();
  ref.onDispose(client.close);
  return client;
});

final apiProvider = Provider<AdCutApi>((ref) => AdCutApi(ref.watch(apiClientProvider)));

/// What the backend says it can do right now. Screens gate features on this.
final capabilitiesProvider = FutureProvider<Capabilities>((ref) => ref.watch(apiProvider).capabilities());

/// Backend liveness, shown on the service status screen.
final healthProvider = FutureProvider.autoDispose<bool>((ref) => ref.watch(apiProvider).health());

/// How often running jobs are polled. Overridden in tests.
final pollIntervalProvider = Provider<Duration>((ref) => const Duration(seconds: 2));
