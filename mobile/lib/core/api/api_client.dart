import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import 'api_config.dart';
import 'api_exception.dart';

/// Cancels an in-flight streamed upload.
class UploadCancelToken {
  bool _cancelled = false;
  bool get isCancelled => _cancelled;
  void cancel() => _cancelled = true;
}

/// The single place that talks HTTP to the backend.
///
/// * one base URL / one auth header (API calls only - never sent to presigned upload URLs)
/// * JSON in/out, typed [ApiException]s, request timeouts
/// * debug logging that never prints tokens or presigned URL credentials
class ApiClient {
  final http.Client _http;
  final Uri _base;
  String? _token;
  final Future<String?> Function()? _refreshToken;
  Future<String?>? _refreshingToken;
  final Duration timeout;
  final bool debugLog;

  ApiClient({
    http.Client? httpClient,
    String? baseUrl,
    String? token,
    Future<String?> Function()? refreshToken,
    this.timeout = ApiConfig.requestTimeout,
    bool? debugLog,
  }) : _http = httpClient ?? http.Client(),
       _base = Uri.parse(baseUrl ?? ApiConfig.baseUrl),
       _token = (token ?? ApiConfig.devToken).isEmpty ? null : (token ?? ApiConfig.devToken),
       _refreshToken = refreshToken,
       debugLog = debugLog ?? kDebugMode;

  String get baseUrl => _base.toString();
  bool get hasToken => _token != null;

  Uri _uri(String path, [Map<String, String>? query]) {
    final p = path.startsWith('/') ? path : '/$path';
    return _base.replace(
      path: '${_base.path.endsWith('/') ? _base.path.substring(0, _base.path.length - 1) : _base.path}$p',
      queryParameters: query == null || query.isEmpty ? null : query,
    );
  }

  Map<String, String> _headers({String? idempotencyKey, bool json = false}) => {
    'Accept': 'application/json',
    if (json) 'Content-Type': 'application/json',
    'Authorization': ?(_token == null ? null : 'Bearer $_token'),
    'Idempotency-Key': ?idempotencyKey,
  };

  void _log(String msg) {
    if (debugLog) debugPrint('[api] $msg');
  }

  Future<Map<String, dynamic>> getJson(String path, {Map<String, String>? query}) => _send('GET', path, query: query);

  Future<Map<String, dynamic>> postJson(String path, {Object? body, String? idempotencyKey}) =>
      _send('POST', path, body: body ?? const <String, dynamic>{}, idempotencyKey: idempotencyKey);

  Future<Map<String, dynamic>> _send(
    String method,
    String path, {
    Map<String, String>? query,
    Object? body,
    String? idempotencyKey,
    bool refreshOnUnauthorized = true,
  }) async {
    final uri = _uri(path, query);
    final sw = Stopwatch()..start();
    try {
      final req = http.Request(method, uri)
        ..headers.addAll(_headers(idempotencyKey: idempotencyKey, json: body != null));
      if (body != null) req.body = jsonEncode(body);
      final streamed = await _http.send(req).timeout(timeout);
      final resp = await http.Response.fromStream(streamed).timeout(timeout);
      _log('$method $path -> ${resp.statusCode} (${sw.elapsedMilliseconds} ms)');
      if (resp.statusCode == 401 && refreshOnUnauthorized && _refreshToken != null) {
        final refreshed = await _refreshAuthToken();
        if (refreshed != null && refreshed.isNotEmpty) {
          _token = refreshed;
          return _send(
            method,
            path,
            query: query,
            body: body,
            idempotencyKey: idempotencyKey,
            refreshOnUnauthorized: false,
          );
        }
      }
      return _decode(resp);
    } on ApiException {
      rethrow;
    } on TimeoutException {
      _log('$method $path timed out');
      throw const ApiException(code: 'TIMEOUT_CLIENT', message: 'The request timed out.');
    } on http.ClientException catch (_) {
      _log('$method $path network error');
      throw const ApiException.network();
    } on FormatException {
      throw const ApiException(code: 'BAD_RESPONSE', message: 'Unexpected response from the server.');
    } catch (e) {
      // dart:io SocketException / HandshakeException etc.
      if (e.runtimeType.toString().contains('Socket') || e.runtimeType.toString().contains('Handshake')) {
        _log('$method $path network error');
        throw const ApiException.network();
      }
      rethrow;
    }
  }

  Future<String?> _refreshAuthToken() async {
    final active = _refreshingToken;
    if (active != null) return active;
    final operation = _refreshToken!();
    _refreshingToken = operation;
    try {
      return await operation;
    } finally {
      if (identical(_refreshingToken, operation)) _refreshingToken = null;
    }
  }

  Map<String, dynamic> _decode(http.Response resp) {
    final requestId = resp.headers['x-request-id'];
    Object? parsed;
    if (resp.body.isNotEmpty) {
      try {
        parsed = jsonDecode(utf8.decode(resp.bodyBytes));
      } on FormatException {
        parsed = null;
      }
    }
    if (resp.statusCode >= 200 && resp.statusCode < 300) {
      if (parsed is Map<String, dynamic>) return parsed;
      if (resp.body.isEmpty) return <String, dynamic>{};
      throw const ApiException(code: 'BAD_RESPONSE', message: 'Unexpected response from the server.');
    }
    var code = 'HTTP_${resp.statusCode}';
    var message = '';
    if (parsed is Map<String, dynamic> && parsed['error'] is Map) {
      final err = parsed['error'] as Map;
      code = (err['code'] ?? code).toString();
      message = (err['message'] ?? '').toString();
    } else if (resp.statusCode == 401) {
      code = 'UNAUTHORIZED';
    }
    throw ApiException(code: code, message: message, statusCode: resp.statusCode, requestId: requestId);
  }

  /// Streams [stream] to a presigned URL. Never buffers the file: chunks flow straight to the socket.
  /// NO Authorization header is attached (presigned URLs carry their own signature).
  Future<void> putStream({
    required Uri url,
    required Stream<List<int>> stream,
    required int length,
    required Map<String, String> headers,
    void Function(int sent, int total)? onProgress,
    UploadCancelToken? cancel,
    Duration? uploadTimeout,
  }) async {
    final req = http.StreamedRequest('PUT', url)
      ..contentLength = length
      ..headers.addAll(headers);
    var sent = 0;
    late final StreamSubscription<List<int>> sub;
    final done = Completer<void>();
    sub = stream.listen(
      (chunk) {
        if (cancel?.isCancelled == true) {
          sub.cancel();
          req.sink.close();
          if (!done.isCompleted) done.complete();
          return;
        }
        req.sink.add(chunk);
        sent += chunk.length;
        onProgress?.call(sent, length);
      },
      onError: (Object e) {
        req.sink.close();
        if (!done.isCompleted) done.completeError(e);
      },
      onDone: () {
        req.sink.close();
        if (!done.isCompleted) done.complete();
      },
      cancelOnError: true,
    );

    try {
      final future = _http.send(req).timeout(uploadTimeout ?? ApiConfig.uploadTimeout);
      await done.future;
      final resp = await future;
      await resp.stream.drain<void>();
      _log('PUT <presigned> -> ${resp.statusCode} ($sent bytes)');
      if (cancel?.isCancelled == true) {
        throw const ApiException(code: 'UPLOAD_CANCELLED', message: 'Upload cancelled.');
      }
      if (resp.statusCode < 200 || resp.statusCode >= 300) {
        throw ApiException(code: 'UPLOAD_FAILED', message: 'Upload rejected.', statusCode: resp.statusCode);
      }
    } on ApiException {
      rethrow;
    } on TimeoutException {
      throw const ApiException.uploadFailed();
    } on http.ClientException {
      throw const ApiException.uploadFailed();
    } catch (e) {
      if (e.runtimeType.toString().contains('Socket') || e.runtimeType.toString().contains('Handshake')) {
        throw const ApiException.uploadFailed();
      }
      rethrow;
    } finally {
      await sub.cancel();
    }
  }

  void close() => _http.close();
}
