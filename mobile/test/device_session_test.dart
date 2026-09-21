import 'dart:convert';

import 'package:adcut_mobile/core/api/device_session.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  test('creates and persists a server-signed device session', () async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    late String installId;
    final client = MockClient((request) async {
      expect(request.url.toString(), 'https://api.test/v1/auth/device-session');
      installId = (jsonDecode(request.body) as Map<String, dynamic>)['install_id'] as String;
      return http.Response(jsonEncode({'access_token': 'signed-device-token', 'expires_in': 864000}), 200);
    });

    final token = await DeviceSession.resolve(
      prefs,
      httpClient: client,
      baseUrl: 'https://api.test',
      fallbackToken: '',
      now: () => DateTime.utc(2026, 1, 1),
    );

    expect(token, 'signed-device-token');
    expect(installId, isNotEmpty);
    expect(prefs.getString('auth.install_id'), installId);
  });

  test('reuses a valid session without a network request', () async {
    final now = DateTime.utc(2026, 1, 1);
    SharedPreferences.setMockInitialValues({
      'auth.install_id': 'a6cb1b68-93e3-4b3f-9e5f-c6864ab6ae8b',
      'auth.device_token': 'cached-token',
      'auth.device_token_expires_at': now.add(const Duration(days: 30)).millisecondsSinceEpoch,
    });
    final prefs = await SharedPreferences.getInstance();
    final client = MockClient((_) async => throw StateError('network should not be called'));

    final token = await DeviceSession.resolve(
      prefs,
      httpClient: client,
      baseUrl: 'https://api.test',
      fallbackToken: '',
      now: () => now,
    );

    expect(token, 'cached-token');
  });

  test('falls back to the development token against an older backend', () async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final client = MockClient((_) async => http.Response('{}', 404));

    final token = await DeviceSession.resolve(
      prefs,
      httpClient: client,
      baseUrl: 'https://api.test',
      fallbackToken: 'development-token',
    );

    expect(token, 'development-token');
  });

  test('refresh replaces an unexpired cached token after server key rotation', () async {
    final now = DateTime.utc(2026, 1, 1);
    SharedPreferences.setMockInitialValues({
      'auth.install_id': 'a6cb1b68-93e3-4b3f-9e5f-c6864ab6ae8b',
      'auth.device_token': 'stale-token',
      'auth.device_token_expires_at': now.add(const Duration(days: 30)).millisecondsSinceEpoch,
    });
    final prefs = await SharedPreferences.getInstance();
    final client = MockClient(
      (_) async => http.Response(jsonEncode({'access_token': 'fresh-token', 'expires_in': 864000}), 200),
    );

    final token = await DeviceSession.refresh(
      prefs,
      httpClient: client,
      baseUrl: 'https://api.test',
      fallbackToken: '',
      now: () => now,
    );

    expect(token, 'fresh-token');
    expect(prefs.getString('auth.device_token'), 'fresh-token');
  });
}
