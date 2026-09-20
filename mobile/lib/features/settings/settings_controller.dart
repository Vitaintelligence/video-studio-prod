import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import 'ad_options.dart';

class AppSettings {
  const AppSettings({this.platform = AdPlatform.tiktok, this.format = AdFormat.vertical});

  final AdPlatform platform;
  final AdFormat format;
}

const _platformKey = 'settings.platform';
const _formatKey = 'settings.format';

/// Defaults applied to every new edit. Persisted locally.
class SettingsController extends Notifier<AppSettings> {
  @override
  AppSettings build() {
    final prefs = ref.watch(preferencesProvider);
    return AppSettings(
      platform: AdPlatform.fromId(prefs.getString(_platformKey)),
      format: AdFormat.fromId(prefs.getString(_formatKey)),
    );
  }

  void setPlatform(AdPlatform value) {
    state = AppSettings(platform: value, format: state.format);
    unawaited(ref.read(preferencesProvider).setString(_platformKey, value.id));
  }

  void setFormat(AdFormat value) {
    state = AppSettings(platform: state.platform, format: value);
    unawaited(ref.read(preferencesProvider).setString(_formatKey, value.id));
  }
}

final settingsProvider = NotifierProvider<SettingsController, AppSettings>(SettingsController.new);
