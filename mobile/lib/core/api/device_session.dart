import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';

import 'api_config.dart';

/// Bootstraps an anonymous, server-signed session for this app installation.
///
/// The install ID is only an identifier. The bearer token is what proves the
/// session was issued by the backend; no shared backend secret ships in the APK.
abstract final class DeviceSession {
  static const _installIdKey = 'auth.install_id';
  static const _tokenKey = 'auth.device_token';
  static const _expiresAtKey = 'auth.device_token_expires_at';
  static const _refreshSkew = Duration(hours: 24);

  static Future<String?> resolve(
    SharedPreferences preferences, {
    http.Client? httpClient,
    String baseUrl = ApiConfig.baseUrl,
    String fallbackToken = ApiConfig.devToken,
    DateTime Function()? now,
  }) async {
    final clock = now ?? DateTime.now;
    final current = clock();
    final cachedToken = preferences.getString(_tokenKey);
    final cachedExpiry = preferences.getInt(_expiresAtKey);
    if (cachedToken != null &&
        cachedToken.isNotEmpty &&
        cachedExpiry != null &&
        DateTime.fromMillisecondsSinceEpoch(cachedExpiry).isAfter(current.add(_refreshSkew))) {
      return cachedToken;
    }

    var installId = preferences.getString(_installIdKey);
    if (installId == null || installId.isEmpty) {
      installId = const Uuid().v4();
      await preferences.setString(_installIdKey, installId);
    }

    final ownsClient = httpClient == null;
    final client = httpClient ?? http.Client();
    try {
      final base = Uri.parse(baseUrl);
      final normalizedPath = base.path.endsWith('/') ? base.path.substring(0, base.path.length - 1) : base.path;
      final uri = base.replace(path: '$normalizedPath/v1/auth/device-session');
      final response = await client
          .post(
            uri,
            headers: const {'Accept': 'application/json', 'Content-Type': 'application/json'},
            body: jsonEncode({'install_id': installId}),
          )
          .timeout(ApiConfig.requestTimeout);
      if (response.statusCode >= 200 && response.statusCode < 300) {
        final body = jsonDecode(utf8.decode(response.bodyBytes));
        if (body is Map) {
          final token = body['access_token']?.toString() ?? '';
          final expiresIn = int.tryParse(body['expires_in']?.toString() ?? '') ?? 0;
          if (token.isNotEmpty && expiresIn > 0) {
            await preferences.setString(_tokenKey, token);
            await preferences.setInt(_expiresAtKey, current.add(Duration(seconds: expiresIn)).millisecondsSinceEpoch);
            return token;
          }
        }
      }
    } on TimeoutException {
      // Fall through to the last usable credential so offline startup still works.
    } on http.ClientException {
      // Fall through to the last usable credential so offline startup still works.
    } on FormatException {
      // An old or incompatible backend can still use the development fallback.
    } catch (_) {
      // Session bootstrap must never prevent the app from opening.
    } finally {
      if (ownsClient) client.close();
    }

    if (cachedToken != null && cachedToken.isNotEmpty && cachedExpiry != null) {
      if (DateTime.fromMillisecondsSinceEpoch(cachedExpiry).isAfter(current)) return cachedToken;
    }
    return fallbackToken.isEmpty ? null : fallbackToken;
  }
}
