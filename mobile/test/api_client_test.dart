import 'dart:async';
import 'dart:convert';

import 'package:adcut_mobile/core/api/adcut_api.dart';
import 'package:adcut_mobile/core/api/api_client.dart';
import 'package:adcut_mobile/core/api/api_config.dart';
import 'package:adcut_mobile/core/api/api_exception.dart';
import 'package:adcut_mobile/core/models/api_models.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'support/fake_backend.dart';

void main() {
  test('the base URL is centralized and defaults to the production API', () {
    expect(ApiConfig.baseUrl, 'https://video-studio-prod-production.up.railway.app');
  });

  test('Capabilities.captions reads features.captions honestly (false unless the backend actually reports it)', () {
    expect(Capabilities.fromJson({'status': 'ok', 'generation_available': false}).captions, isFalse);
    expect(Capabilities.fromJson({'status': 'ok', 'generation_available': false, 'features': {}}).captions, isFalse);
    expect(
      Capabilities.fromJson({
        'status': 'ok',
        'generation_available': false,
        'features': {'captions': false},
      }).captions,
      isFalse,
    );
    expect(
      Capabilities.fromJson({
        'status': 'ok',
        'generation_available': false,
        'features': {'captions': true},
      }).captions,
      isTrue,
    );
  });

  test('API calls carry the bearer token; presigned uploads never do', () async {
    final backend = FakeBackend();
    final client = ApiClient(
      httpClient: backend.client(),
      baseUrl: 'https://api.test',
      token: FakeBackend.token,
      debugLog: false,
    );
    final api = AdCutApi(client);

    final caps = await api.capabilities();
    expect(caps.editing, isTrue);
    expect(backend.requests.last.headers['Authorization'], 'Bearer ${FakeBackend.token}');

    final res = await api.presign(filename: 'a.mp4', contentType: 'video/mp4', sizeBytes: 5);
    await client.putStream(url: res.url, stream: Stream.value([1, 2, 3, 4, 5]), length: 5, headers: res.headers);
    expect(backend.uploadAuthHeaders, ['']); // no Authorization sent to the storage URL
    expect(backend.assets[res.assetId]!['stored'], 5);
  });

  test('upload progress is reported and the stream is not buffered by the client', () async {
    final backend = FakeBackend();
    final client = ApiClient(
      httpClient: backend.client(),
      baseUrl: 'https://api.test',
      token: FakeBackend.token,
      debugLog: false,
    );
    final reservation = await AdCutApi(client).presign(filename: 'a.mp4', contentType: 'video/mp4', sizeBytes: 300);
    final seen = <int>[];
    await client.putStream(
      url: reservation.url,
      stream: Stream.fromIterable([List.filled(100, 1), List.filled(100, 2), List.filled(100, 3)]),
      length: 300,
      headers: reservation.headers,
      onProgress: (sent, total) => seen.add(sent),
    );
    expect(seen, [100, 200, 300]);
  });

  test('server error envelope becomes a typed ApiException with a friendly message', () async {
    final client = ApiClient(
      httpClient: MockClient(
        (req) async => http.Response(
          jsonEncode({
            'error': {'code': 'BUDGET_EXCEEDED', 'message': 'internal'},
          }),
          402,
          headers: {'x-request-id': 'abc'},
        ),
      ),
      baseUrl: 'https://api.test',
      token: 't',
      debugLog: false,
    );
    try {
      await client.getJson('/v1/x');
      fail('expected throw');
    } on ApiException catch (e) {
      expect(e.code, 'BUDGET_EXCEEDED');
      expect(e.requestId, 'abc');
      expect(e.userMessage, contains('too complex'));
      expect(e.userMessage, isNot(contains('internal')));
    }
  });

  test('500 with a non-JSON body never leaks server text', () async {
    final client = ApiClient(
      httpClient: MockClient((req) async => http.Response('Traceback (most recent call last): secret', 500)),
      baseUrl: 'https://api.test',
      token: 't',
      debugLog: false,
    );
    try {
      await client.getJson('/v1/x');
      fail('expected throw');
    } on ApiException catch (e) {
      expect(e.statusCode, 500);
      expect(e.isTransient, isTrue);
      expect(e.userMessage, isNot(contains('Traceback')));
      expect(e.userMessage, isNot(contains('500')));
    }
  });

  test('401 maps to unauthorized; network failures are typed and transient', () async {
    final unauthorized = ApiClient(
      httpClient: MockClient((req) async => http.Response('', 401)),
      baseUrl: 'https://api.test',
      debugLog: false,
    );
    await expectLater(
      unauthorized.getJson('/v1/x'),
      throwsA(isA<ApiException>().having((e) => e.isUnauthorized, 'unauthorized', true)),
    );

    final offline = ApiClient(
      httpClient: MockClient((req) async => throw http.ClientException('no route')),
      baseUrl: 'https://api.test',
      debugLog: false,
    );
    await expectLater(
      offline.getJson('/v1/x'),
      throwsA(
        isA<ApiException>()
            .having((e) => e.code, 'code', 'NETWORK_ERROR')
            .having((e) => e.isTransient, 'transient', true),
      ),
    );

    final slow = ApiClient(
      httpClient: MockClient((req) async {
        await Future<void>.delayed(const Duration(milliseconds: 200));
        return http.Response('{}', 200);
      }),
      baseUrl: 'https://api.test',
      timeout: const Duration(milliseconds: 20),
      debugLog: false,
    );
    await expectLater(
      slow.getJson('/v1/x'),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', 'TIMEOUT_CLIENT')),
    );
  });

  test('a stale device token is refreshed once and the request is replayed', () async {
    var calls = 0;
    final seenAuth = <String?>[];
    final client = ApiClient(
      httpClient: MockClient((request) async {
        calls++;
        seenAuth.add(request.headers['Authorization']);
        return calls == 1 ? http.Response('', 401) : http.Response('{}', 200);
      }),
      baseUrl: 'https://api.test',
      token: 'stale-token',
      refreshToken: () async => 'fresh-token',
      debugLog: false,
    );

    await client.getJson('/v1/capabilities');

    expect(calls, 2);
    expect(seenAuth, ['Bearer stale-token', 'Bearer fresh-token']);
  });

  test('idempotency key and JSON body are sent on create', () async {
    late http.Request captured;
    final client = ApiClient(
      httpClient: MockClient((req) async {
        captured = req;
        return http.Response(jsonEncode({'id': 'e1', 'status': 'queued', 'progress': 0}), 202);
      }),
      baseUrl: 'https://api.test',
      token: 't',
      debugLog: false,
    );
    final accepted = await AdCutApi(client).createEdit(
      assetIds: ['a1'],
      instruction: 'Remove pauses and add a CTA',
      platform: 'tiktok',
      aspectRatio: '9:16',
      idempotencyKey: 'key-123',
    );
    expect(accepted.id, 'e1');
    expect(captured.headers['Idempotency-Key'], 'key-123');
    expect(captured.headers['Content-Type'], contains('application/json'));
    expect(jsonDecode(captured.body), containsPair('asset_ids', ['a1']));
  });

  test('debug logging never prints tokens or presigned URL credentials', () async {
    final logs = <String>[];
    final original = debugPrint;
    debugPrint = (String? m, {int? wrapWidth}) => logs.add(m ?? '');
    try {
      final backend = FakeBackend();
      final client = ApiClient(
        httpClient: backend.client(),
        baseUrl: 'https://api.test',
        token: 'SUPER-SECRET-TOKEN',
        debugLog: true,
      );
      // token is wrong for the fake -> 401, but nothing may be logged with it either way
      await expectLater(client.getJson('/v1/capabilities'), throwsA(isA<ApiException>()));
      final res = await AdCutApi(
        ApiClient(httpClient: backend.client(), baseUrl: 'https://api.test', token: FakeBackend.token, debugLog: true),
      ).presign(filename: 'a.mp4', contentType: 'video/mp4', sizeBytes: 1);
      await client.putStream(url: res.url, stream: Stream.value([1]), length: 1, headers: res.headers);
    } finally {
      debugPrint = original;
    }
    final all = logs.join('\n');
    expect(all, isNot(contains('SUPER-SECRET-TOKEN')));
    expect(all, isNot(contains('SECRET')));
    expect(all, isNot(contains('sig=')));
  });

  test('model parsing is defensive and typed', () {
    final job = EditJob.fromJson({
      'id': 'e1',
      'status': 'running',
      'progress': 54,
      'display_stage': 'Building your edit',
      'instruction': 'x',
      'aspect_ratio': '9:16',
      'duration_target_seconds': 25,
      'warnings': ['captions_unavailable', 3],
      'unknown_future_field': {'a': 1},
    });
    expect(job.status, EditStatus.running);
    expect(job.progressFraction, 0.54);
    expect(job.warnings, ['captions_unavailable']);
    expect(job.isDone, isFalse);
    final failed = EditJob.fromJson({
      'id': 'e2',
      'status': 'failed',
      'error': {'code': 'GENERATION_FAILED', 'message': "We couldn't finish this video."},
    });
    expect(failed.error!.code, 'GENERATION_FAILED');
    expect(EditStatus.parse('cancel_requested').isActive, isTrue);
    expect(EditStatus.parse('cancelled').isTerminal, isTrue);
    expect(
      UploadReservation.fromJson({
        'asset_id': 'a',
        'url': 'https://s.test/x?sig=1',
        'headers': {'Content-Type': 'video/mp4'},
      }).toString(),
      isNot(contains('sig')),
    );
  });

  test('error codes map to consumer copy without infrastructure words', () {
    for (final code in [
      'NETWORK_ERROR',
      'UPLOAD_FAILED',
      'PROVIDER_UNAVAILABLE',
      'BUDGET_EXCEEDED',
      'GENERATION_FAILED',
      'OUTPUT_INVALID',
      'TIMEOUT',
      'RATE_LIMITED',
      'WHATEVER',
    ]) {
      final text = ApiException(
        code: code,
        message: '',
        statusCode: code == 'WHATEVER' ? 500 : null,
      ).userMessage.toLowerCase();
      for (final banned in [
        'celery',
        'redis',
        'claude',
        'openrouter',
        'ffmpeg',
        'remotion',
        'openmontage',
        'traceback',
        '500',
      ]) {
        expect(text, isNot(contains(banned)), reason: code);
      }
    }
  });
}
