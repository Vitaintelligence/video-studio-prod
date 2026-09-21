import 'dart:io';

import '../models/api_models.dart';
import 'api_client.dart';
import 'api_config.dart';
import 'api_exception.dart';

/// Typed endpoints for the AdCut backend (`/v1/...`). No screen builds URLs or JSON by hand.
class AdCutApi {
  final ApiClient client;
  AdCutApi(this.client);

  Future<bool> health() async {
    final j = await client.getJson('/health');
    return j['status'] == 'ok';
  }

  Future<Capabilities> capabilities() async => Capabilities.fromJson(await client.getJson('/v1/capabilities'));

  // -- projects ------------------------------------------------------------------
  Future<ApiProject> createProject(String name) async =>
      ApiProject.fromJson(await client.postJson('/v1/projects', body: {'name': name}));

  Future<List<ApiProject>> listProjects() async {
    final j = await client.getJson('/v1/projects');
    return [
      for (final p in (j['items'] as List? ?? const []))
        if (p is Map) ApiProject.fromJson(Map<String, dynamic>.from(p)),
    ];
  }

  Future<ApiProject> getProject(String id) async => ApiProject.fromJson(await client.getJson('/v1/projects/$id'));

  // -- uploads -------------------------------------------------------------------
  Future<UploadReservation> presign({
    required String filename,
    required String contentType,
    required int sizeBytes,
    String? projectId,
  }) async => UploadReservation.fromJson(
    await client.postJson(
      '/v1/uploads/presign',
      body: {
        'filename': filename,
        'content_type': contentType,
        'purpose': 'source_video',
        'size_bytes': sizeBytes,
        'project_id': ?projectId,
      },
    ),
  );

  Future<ApiAsset> completeUpload(String assetId) async =>
      ApiAsset.fromJson(await client.postJson('/v1/uploads/$assetId/complete'));

  /// Presign -> stream the file straight to storage -> tell the backend it finished.
  /// The file is read as a stream; it is never loaded into memory.
  Future<ApiAsset> uploadFootage({
    required File file,
    required String filename,
    required String contentType,
    String? projectId,
    void Function(int sent, int total)? onProgress,
    UploadCancelToken? cancel,
  }) async {
    final length = await file.length();
    if (length <= 0) {
      throw const ApiException.invalidMedia('That file is empty.');
    }
    if (length > ApiConfig.maxUploadBytes) {
      throw const ApiException.invalidMedia('That video is too large. Try a clip under 500 MB.');
    }
    final reservation = await presign(
      filename: filename,
      contentType: contentType,
      sizeBytes: length,
      projectId: projectId,
    );
    await client.putStream(
      url: reservation.url,
      stream: file.openRead(),
      length: length,
      headers: reservation.headers,
      onProgress: onProgress,
      cancel: cancel,
    );
    return completeUpload(reservation.assetId);
  }

  // -- edits ---------------------------------------------------------------------
  /// [idempotencyKey] must be generated ONCE per user action and reused on retry, so a timeout
  /// followed by a retry can never create (and pay for) two edits.
  Future<EditAccepted> createEdit({
    String? projectId,
    required List<String> assetIds,
    required String instruction,
    required String platform,
    required String aspectRatio,
    int? durationTargetSeconds,
    required String idempotencyKey,
  }) async => EditAccepted.fromJson(
    await client.postJson(
      '/v1/edits',
      idempotencyKey: idempotencyKey,
      body: {
        'project_id': ?projectId,
        'asset_ids': assetIds,
        'instruction': instruction,
        'platform': platform,
        'aspect_ratio': aspectRatio,
        'duration_target_seconds': ?durationTargetSeconds,
      },
    ),
  );

  Future<EditJob> getEdit(String id) async => EditJob.fromJson(await client.getJson('/v1/edits/$id'));

  Future<EditJob> cancelEdit(String id) async => EditJob.fromJson(await client.postJson('/v1/edits/$id/cancel'));

  Future<EditAccepted> addInstruction(String editId, String instruction, {required String idempotencyKey}) async =>
      EditAccepted.fromJson(
        await client.postJson(
          '/v1/edits/$editId/instructions',
          idempotencyKey: idempotencyKey,
          body: {'instruction': instruction},
        ),
      );

  Future<EditAccepted> restoreRange(String editId, CutRange range, {required String idempotencyKey}) async =>
      EditAccepted.fromJson(
        await client.postJson(
          '/v1/edits/$editId/restore',
          idempotencyKey: idempotencyKey,
          body: {'source': range.source, 'start': range.start, 'end': range.end},
        ),
      );

  Future<List<EditJob>> createVariants(
    String editId, {
    int count = 3,
    String strategy = 'hooks',
    required String idempotencyKey,
  }) async {
    final j = await client.postJson(
      '/v1/edits/$editId/variants',
      idempotencyKey: idempotencyKey,
      body: {'count': count, 'strategy': strategy},
    );
    return _jobs(j);
  }

  Future<List<EditJob>> listVariants(String editId) async => _jobs(await client.getJson('/v1/edits/$editId/variants'));

  List<EditJob> _jobs(Map<String, dynamic> j) => [
    for (final e in (j['items'] as List? ?? const []))
      if (e is Map) EditJob.fromJson(Map<String, dynamic>.from(e)),
  ];
}
