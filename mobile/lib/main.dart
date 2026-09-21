import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'app/app.dart';
import 'app/providers.dart';
import 'core/api/device_session.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setSystemUIOverlayStyle(SystemUiOverlayStyle.light);
  final prefs = await SharedPreferences.getInstance();
  final token = await DeviceSession.resolve(prefs);
  runApp(
    ProviderScope(
      // Failed loads surface as explicit error states with a retry button, not silent auto-retries.
      retry: (retryCount, error) => null,
      overrides: [preferencesProvider.overrideWithValue(prefs), apiTokenProvider.overrideWithValue(token)],
      child: const AdCutApp(),
    ),
  );
}
