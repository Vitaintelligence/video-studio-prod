import 'dart:convert';

import 'package:adcut_mobile/core/api/adcut_api.dart';
import 'package:adcut_mobile/core/api/api_client.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

/// In-memory stand-in for the AdCut backend contract (same JSON shapes as the real API).
class FakeBackend {
  final Map<String, Map<String, dynamic>> assets = {};
  final Map<String, Map<String, dynamic>> edits = {};
  final Map<String, String> idempotency = {}; // key -> edit id
  final List<http.BaseRequest> requests = [];
  final List<Map<String, dynamic>> editBodies = [];
  final List<Map<String, dynamic>> instructionBodies = [];
  final List<Map<String, dynamic>> restoreBodies = [];
  final List<String> uploadAuthHeaders = [];
  int editCreations = 0;
  int getEditCalls = 0;

  /// Create the edit but lose the response once (simulates a client timeout after the server acted).
  bool dropNextEditResponse = false;
  bool failGetEdit = false; // simulate connectivity loss while polling
  bool failProjects = false;
  bool failNextStorage = false; // storage rejects the upload
  int polls = 0;
  bool editingEnabled = true;
  bool variantsEnabled = true;
  bool revisionsEnabled = true;
  bool brollEnabled = false;
  bool captionsEnabled = false;

  /// Holds running jobs at a fixed mid-progress state (for screenshots).
  bool freezeProgress = false;

  /// Length reported for finished outputs.
  double outputSeconds = 17;
  int stepsToComplete = 3;

  static const token = 'test-token';
  static const outputUrl = 'https://cdn.test/generations/out.mp4';

  http.Client client() => MockClient.streaming((req, body) async {
    final bytes = await body.toBytes();
    requests.add(req);
    final r = _route(req, bytes);
    return http.StreamedResponse(
      Stream.value(utf8.encode(r.$2)),
      r.$1,
      headers: {'content-type': 'application/json', 'x-request-id': 'req-test'},
    );
  });

  AdCutApi api() =>
      AdCutApi(ApiClient(httpClient: client(), baseUrl: 'https://api.test', token: token, debugLog: false));

  (int, String) _json(int status, Object body) => (status, jsonEncode(body));
  (int, String) _err(int status, String code, String msg) => _json(status, {
    'error': {'code': code, 'message': msg},
  });

  Map<String, dynamic> _editJson(Map<String, dynamic> e) {
    final done = e['status'] == 'completed';
    return {
      'id': e['id'],
      'project_id': e['project_id'],
      'kind': e['kind'],
      'parent_id': e['parent_id'],
      'version': e['version'],
      'status': e['status'],
      'progress': done ? 100 : e['progress'],
      'stage': done ? 'complete' : e['stage'],
      'display_stage': done ? 'Ready' : e['display_stage'],
      'instruction': e['instruction'],
      'platform': 'tiktok',
      'aspect_ratio': '9:16',
      'duration_target_seconds': 30,
      'duration_seconds': done ? outputSeconds : null,
      'variant': e['variant'],
      'output_url': done ? outputUrl : null,
      'thumbnail_url': done ? 'https://cdn.test/generations/thumb.jpg' : null,
      'warnings': e['warnings'] ?? <String>[],
      'insights': e['insights'] ?? <String, dynamic>{},
      'kept_ranges': e['kept_ranges'] ?? <Map<String, dynamic>>[],
      'error': e['error'],
      'versions': _versionsOf(e),
      'created_at': '2025-09-20T10:00:00Z',
      'updated_at': '2025-09-20T10:00:05Z',
    };
  }

  /// Like the real API: an edit and its revisions both report the full version history of the root edit.
  List<Map<String, dynamic>> _versionsOf(Map<String, dynamic> e) {
    if (e['kind'] == 'variant') return [];
    final root = e['kind'] == 'edit' ? e : edits[e['parent_id']]!;
    Map<String, dynamic> version(Map<String, dynamic> x) {
      final done = x['status'] == 'completed';
      return {
        'id': x['id'],
        'version': x['version'],
        'instruction': x['instruction'],
        'status': x['status'],
        'progress': done ? 100 : x['progress'],
        'output_url': done ? outputUrl : null,
        'thumbnail_url': null,
        'kept_ranges': x['kept_ranges'] ?? <Map<String, dynamic>>[],
        'created_at': '2025-09-20T10:00:00Z',
      };
    }

    return [
      version(root),
      for (final r in edits.values.where((x) => x['parent_id'] == root['id'] && x['kind'] == 'revision')) version(r),
    ];
  }

  Map<String, dynamic> newEditForTest(String instruction) => _newEdit('edit', instruction);

  Map<String, dynamic> _newEdit(
    String kind,
    String instruction, {
    String? parent,
    int? version,
    Map<String, dynamic>? variant,
    List<Map<String, dynamic>>? keptRanges,
  }) {
    final id = 'edit-${edits.length + 1}';
    final e = {
      'id': id,
      'project_id': 'proj-1',
      'kind': kind,
      'parent_id': parent,
      'version': version ?? 1,
      'status': 'queued',
      'progress': 0,
      'stage': null,
      'display_stage': null,
      'instruction': instruction,
      'variant': variant,
      'kept_ranges':
          keptRanges ??
          [
            {'source': 0, 'start': 2.0, 'end': 8.0},
            {'source': 0, 'start': 12.0, 'end': 23.0},
          ],
      'steps': 0,
    };
    edits[id] = e;
    return e;
  }

  void _advance(Map<String, dynamic> e) {
    if (freezeProgress) {
      e['status'] = 'running';
      e['progress'] = 45;
      e['stage'] = 'edit';
      e['display_stage'] = 'Building your edit';
      return;
    }
    if (e['status'] == 'completed' || e['status'] == 'failed' || e['status'] == 'cancelled') return;
    e['steps'] = (e['steps'] as int) + 1;
    final s = e['steps'] as int;
    if (s >= stepsToComplete) {
      e['status'] = 'completed';
    } else {
      e['status'] = 'running';
      e['progress'] = 20 + s * 25;
      e['stage'] = 'edit';
      e['display_stage'] = 'Building your edit';
    }
  }

  (int, String) _route(http.BaseRequest req, List<int> body) {
    final path = req.url.path;
    final m = req.method;
    Map<String, dynamic> j() => body.isEmpty ? {} : jsonDecode(utf8.decode(body)) as Map<String, dynamic>;

    if (req.url.host == 'storage.test') {
      uploadAuthHeaders.add(req.headers['authorization'] ?? '');
      if (failNextStorage) return (500, '');
      final id = path.split('/').last;
      assets[id]?['stored'] = body.length;
      return (200, '');
    }
    if (req.headers['authorization'] != 'Bearer $token') {
      return _err(401, 'UNAUTHORIZED', 'Missing or invalid credentials.');
    }

    if (m == 'GET' && path == '/v1/capabilities') {
      return _json(200, {
        'status': 'ok',
        'generation_available': false,
        'editing': editingEnabled,
        'ai_broll': brollEnabled,
        'video_generation': false,
        'variants': variantsEnabled,
        'revisions': revisionsEnabled,
        'pipelines': [],
        'features': {'captions': captionsEnabled},
        'limits': {'uploads': true},
      });
    }
    if (m == 'POST' && path == '/v1/uploads/presign') {
      final b = j();
      final id = 'asset-${assets.length + 1}';
      assets[id] = {'id': id, 'filename': b['filename'], 'content_type': b['content_type'], 'status': 'pending'};
      return _json(200, {
        'upload_id': id,
        'asset_id': id,
        'method': 'PUT',
        'url': 'https://storage.test/upload/$id?sig=SECRET',
        'headers': {'Content-Type': b['content_type']},
        'key': 'uploads/dev/$id',
        'expires_in': 900,
        'max_bytes': 524288000,
      });
    }
    final complete = RegExp(r'^/v1/uploads/([^/]+)/complete$').firstMatch(path);
    if (m == 'POST' && complete != null) {
      final a = assets[complete.group(1)];
      if (a == null || a['stored'] == null) return _err(409, 'INVALID_REQUEST', 'The file has not finished uploading.');
      a['status'] = 'uploaded';
      return _json(200, {
        'id': a['id'],
        'project_id': null,
        'filename': a['filename'],
        'content_type': a['content_type'],
        'purpose': 'source_video',
        'size_bytes': a['stored'],
        'status': 'uploaded',
        'created_at': '2025-09-20T10:00:00Z',
      });
    }
    if (m == 'POST' && path == '/v1/edits') {
      final key = req.headers['Idempotency-Key'];
      if (key != null && idempotency.containsKey(key)) {
        final e = edits[idempotency[key]]!;
        return _json(202, {
          'id': e['id'],
          'project_id': 'proj-1',
          'status': e['status'],
          'progress': 0,
          'poll_url': '/v1/edits/${e['id']}',
        });
      }
      final b = j();
      editBodies.add(b);
      final ids = (b['asset_ids'] as List).cast<String>();
      if (ids.any((i) => assets[i]?['status'] != 'uploaded')) {
        return _err(422, 'INVALID_REQUEST', 'One or more source files were not found.');
      }
      editCreations++;
      final e = _newEdit('edit', b['instruction'] as String);
      if (key != null) idempotency[key] = e['id'] as String;
      if (dropNextEditResponse) {
        dropNextEditResponse = false;
        throw http.ClientException('connection lost');
      }
      return _json(202, {
        'id': e['id'],
        'project_id': 'proj-1',
        'status': 'queued',
        'progress': 0,
        'poll_url': '/v1/edits/${e['id']}',
      });
    }
    final one = RegExp(r'^/v1/edits/([^/]+)$').firstMatch(path);
    if (m == 'GET' && one != null) {
      getEditCalls++;
      if (failGetEdit) throw http.ClientException('offline');
      final e = edits[one.group(1)];
      if (e == null) return _err(404, 'NOT_FOUND', 'Edit not found.');
      _advance(e);
      return _json(200, _editJson(e));
    }
    final cancel = RegExp(r'^/v1/edits/([^/]+)/cancel$').firstMatch(path);
    if (m == 'POST' && cancel != null) {
      final e = edits[cancel.group(1)]!;
      e['status'] = 'cancelled';
      return _json(200, _editJson(e));
    }
    final instr = RegExp(r'^/v1/edits/([^/]+)/instructions$').firstMatch(path);
    if (m == 'POST' && instr != null) {
      final root = edits[instr.group(1)]!;
      if (root['status'] != 'completed') {
        return _err(409, 'INVALID_REQUEST', 'Wait for this version to finish before revising it.');
      }
      final n = edits.values.where((x) => x['parent_id'] == root['id'] && x['kind'] == 'revision').length + 2;
      instructionBodies.add(j());
      final r = _newEdit('revision', j()['instruction'] as String, parent: root['id'] as String, version: n);
      return _json(202, {
        'id': r['id'],
        'project_id': 'proj-1',
        'status': 'queued',
        'progress': 0,
        'poll_url': '/v1/edits/${r['id']}',
      });
    }
    final restore = RegExp(r'^/v1/edits/([^/]+)/restore$').firstMatch(path);
    if (m == 'POST' && restore != null) {
      final root = edits[restore.group(1)]!;
      if (root['status'] != 'completed') {
        return _err(409, 'INVALID_REQUEST', 'Wait for this version to finish before restoring footage.');
      }
      final body = j();
      restoreBodies.add(body);
      final ranges = [
        for (final range in (root['kept_ranges'] as List)) Map<String, dynamic>.from(range as Map),
        Map<String, dynamic>.from(body),
      ];
      final n = edits.values.where((x) => x['parent_id'] == root['id'] && x['kind'] == 'revision').length + 2;
      final revision = _newEdit(
        'revision',
        'Restore removed footage',
        parent: root['id'] as String,
        version: n,
        keptRanges: ranges,
      );
      return _json(202, {
        'id': revision['id'],
        'project_id': 'proj-1',
        'status': 'queued',
        'progress': 0,
        'poll_url': '/v1/edits/${revision['id']}',
      });
    }
    final vars = RegExp(r'^/v1/edits/([^/]+)/variants$').firstMatch(path);
    if (vars != null) {
      final root = edits[vars.group(1)]!;
      if (m == 'POST') {
        final labels = ['Problem Hook', 'Curiosity Hook', 'Benefit Hook', 'Testimonial Hook', 'Product-first Hook'];
        final count = j()['count'] as int;
        for (var i = 0; i < count; i++) {
          _newEdit(
            'variant',
            root['instruction'] as String,
            parent: root['id'] as String,
            variant: {'strategy': 'v$i', 'label': labels[i]},
          );
        }
      }
      final items = edits.values.where((x) => x['parent_id'] == root['id'] && x['kind'] == 'variant').map((x) {
        _advance(x);
        return _editJson(x);
      }).toList();
      return _json(m == 'POST' ? 202 : 200, {'items': items});
    }
    if (m == 'GET' && path == '/v1/projects') {
      if (failProjects) return _err(503, 'PIPELINE_UNAVAILABLE', 'Editing is temporarily unavailable.');
      final roots = edits.values.where((x) => x['kind'] == 'edit').toList();
      return _json(200, {
        'items': [
          if (roots.isNotEmpty)
            {
              'id': 'proj-1',
              'name': 'UGC Test',
              'created_at': '2025-09-20T10:00:00Z',
              'updated_at': '2025-09-20T10:00:05Z',
              'edit_count': roots.length,
              'latest_edit': _editJson(roots.last),
            },
        ],
      });
    }
    final proj = RegExp(r'^/v1/projects/([^/]+)$').firstMatch(path);
    if (m == 'GET' && proj != null) {
      final roots = edits.values.where((x) => x['kind'] == 'edit').toList();
      return _json(200, {
        'id': 'proj-1',
        'name': 'UGC Test',
        'created_at': '2025-09-20T10:00:00Z',
        'updated_at': '2025-09-20T10:00:05Z',
        'edit_count': roots.length,
        'latest_edit': roots.isEmpty ? null : _editJson(roots.last),
        'assets': [],
        'edits': [],
      });
    }
    return _err(404, 'NOT_FOUND', 'Not found.');
  }
}
