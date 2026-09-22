/// Typed models for the backend contract (hand-written; the surface is small).
///
/// Parsing is defensive: unknown fields are ignored, missing optional fields become null.
library;

enum EditStatus {
  queued,
  starting,
  running,
  completed,
  failed,
  cancelRequested,
  cancelled;

  static EditStatus parse(String? raw) {
    switch (raw) {
      case 'queued':
        return EditStatus.queued;
      case 'starting':
        return EditStatus.starting;
      case 'running':
        return EditStatus.running;
      case 'completed':
        return EditStatus.completed;
      case 'failed':
        return EditStatus.failed;
      case 'cancel_requested':
        return EditStatus.cancelRequested;
      case 'cancelled':
        return EditStatus.cancelled;
      default:
        return EditStatus.queued;
    }
  }

  bool get isTerminal => this == EditStatus.completed || this == EditStatus.failed || this == EditStatus.cancelled;
  bool get isActive => !isTerminal;
}

DateTime _date(Object? v) => v is String ? (DateTime.tryParse(v) ?? DateTime.now()) : DateTime.now();
DateTime? _dateOrNull(Object? v) => v is String ? DateTime.tryParse(v) : null;
String? _str(Object? v) => v is String ? v : null;
int _int(Object? v, [int d = 0]) => v is num ? v.toInt() : d;

class ApiErrorInfo {
  final String code;
  final String message;
  const ApiErrorInfo({required this.code, required this.message});

  factory ApiErrorInfo.fromJson(Map<String, dynamic> j) =>
      ApiErrorInfo(code: _str(j['code']) ?? 'GENERATION_FAILED', message: _str(j['message']) ?? '');
}

class Capabilities {
  final bool editing;
  final bool aiBroll;
  final bool videoGeneration;
  final bool variants;
  final bool revisions;

  /// The backend has no clip-extraction capability yet; stays false until it reports one.
  final bool videoToClips;

  /// Real caption burn-in (not just an installed-but-unused tool). Gates the "Add captions" suggestion.
  final bool captions;
  final bool uploads;
  final String status;

  const Capabilities({
    this.editing = false,
    this.aiBroll = false,
    this.videoGeneration = false,
    this.variants = false,
    this.revisions = false,
    this.videoToClips = false,
    this.captions = false,
    this.uploads = false,
    this.status = 'unknown',
  });

  /// Optimistic default used before the first successful call: don't block the UI on an
  /// unreachable capabilities endpoint; the server still enforces everything.
  static const Capabilities unknown = Capabilities(editing: true, variants: true, revisions: true, uploads: true);

  factory Capabilities.fromJson(Map<String, dynamic> j) {
    final limits = j['limits'] is Map ? Map<String, dynamic>.from(j['limits'] as Map) : const <String, dynamic>{};
    final features = j['features'] is Map ? Map<String, dynamic>.from(j['features'] as Map) : const <String, dynamic>{};
    return Capabilities(
      editing: j['editing'] == true,
      aiBroll: j['ai_broll'] == true,
      videoGeneration: j['video_generation'] == true,
      variants: j['variants'] == true,
      revisions: j['revisions'] == true,
      videoToClips: j['video_to_clips'] == true,
      captions: features['captions'] == true,
      uploads: limits['uploads'] == true,
      status: _str(j['status']) ?? 'unknown',
    );
  }
}

class ApiAsset {
  final String id;
  final String? projectId;
  final String filename;
  final String contentType;
  final int? sizeBytes;
  final bool uploaded;

  const ApiAsset({
    required this.id,
    required this.projectId,
    required this.filename,
    required this.contentType,
    required this.sizeBytes,
    required this.uploaded,
  });

  factory ApiAsset.fromJson(Map<String, dynamic> j) => ApiAsset(
    id: _str(j['id']) ?? '',
    projectId: _str(j['project_id']),
    filename: _str(j['filename']) ?? 'footage',
    contentType: _str(j['content_type']) ?? 'video/mp4',
    sizeBytes: j['size_bytes'] is num ? (j['size_bytes'] as num).toInt() : null,
    uploaded: j['status'] == 'uploaded',
  );
}

class UploadReservation {
  final String assetId;
  final String method;
  final Uri url;
  final Map<String, String> headers;
  final int maxBytes;

  const UploadReservation({
    required this.assetId,
    required this.method,
    required this.url,
    required this.headers,
    required this.maxBytes,
  });

  factory UploadReservation.fromJson(Map<String, dynamic> j) => UploadReservation(
    assetId: _str(j['asset_id']) ?? '',
    method: _str(j['method']) ?? 'PUT',
    url: Uri.parse(_str(j['url']) ?? ''),
    headers: {
      if (j['headers'] is Map)
        for (final e in (j['headers'] as Map).entries) e.key.toString(): e.value.toString(),
    },
    maxBytes: _int(j['max_bytes'], 500 * 1024 * 1024),
  );

  // Presigned URLs carry credentials: never print them.
  @override
  String toString() => 'UploadReservation(asset: $assetId, host: ${url.host})';
}

class CutRange {
  final int source;
  final double start;
  final double end;

  const CutRange({required this.source, required this.start, required this.end});

  double get duration => end - start;

  factory CutRange.fromJson(Map<String, dynamic> j) => CutRange(
    source: _int(j['source']),
    start: j['start'] is num ? (j['start'] as num).toDouble() : 0,
    end: j['end'] is num ? (j['end'] as num).toDouble() : 0,
  );
}

/// One version of an edit (the original, or a prompt-to-edit revision).
class EditRevision {
  final String id;
  final int version;
  final String instruction;
  final EditStatus status;
  final int progress;
  final String? outputUrl;
  final String? thumbnailUrl;
  final List<CutRange> keptRanges;
  final DateTime createdAt;

  const EditRevision({
    required this.id,
    required this.version,
    required this.instruction,
    required this.status,
    required this.progress,
    required this.outputUrl,
    required this.thumbnailUrl,
    required this.keptRanges,
    required this.createdAt,
  });

  factory EditRevision.fromJson(Map<String, dynamic> j) => EditRevision(
    id: _str(j['id']) ?? '',
    version: _int(j['version'], 1),
    instruction: _str(j['instruction']) ?? '',
    status: EditStatus.parse(_str(j['status'])),
    progress: _int(j['progress']),
    outputUrl: _str(j['output_url']),
    thumbnailUrl: _str(j['thumbnail_url']),
    keptRanges: [
      if (j['kept_ranges'] is List)
        for (final r in (j['kept_ranges'] as List))
          if (r is Map) CutRange.fromJson(Map<String, dynamic>.from(r)),
    ],
    createdAt: _date(j['created_at']),
  );
}

class VariantInfo {
  final String strategy;
  final String label;
  const VariantInfo({required this.strategy, required this.label});
}

/// An edit job: the original edit, a revision, or a variant. All share one shape.
class EditJob {
  final String id;
  final String? projectId;
  final String kind; // edit | revision | variant
  final String? parentId;
  final int? version;
  final EditStatus status;
  final int progress;
  final String? stage;
  final String? displayStage;
  final String instruction;
  final String? platform;
  final String aspectRatio;
  final int durationTargetSeconds;
  final double? durationSeconds;
  final VariantInfo? variant;
  final String? outputUrl;
  final String? thumbnailUrl;
  final List<String> warnings;
  final Map<String, Object> insights;
  final List<CutRange> keptRanges;
  final ApiErrorInfo? error;
  final List<EditRevision> versions;
  final DateTime createdAt;
  final DateTime updatedAt;

  const EditJob({
    required this.id,
    required this.projectId,
    required this.kind,
    required this.parentId,
    required this.version,
    required this.status,
    required this.progress,
    required this.stage,
    required this.displayStage,
    required this.instruction,
    required this.platform,
    required this.aspectRatio,
    required this.durationTargetSeconds,
    required this.durationSeconds,
    required this.variant,
    required this.outputUrl,
    required this.thumbnailUrl,
    required this.warnings,
    required this.insights,
    required this.keptRanges,
    required this.error,
    required this.versions,
    required this.createdAt,
    required this.updatedAt,
  });

  bool get isDone => status == EditStatus.completed && outputUrl != null;
  double get progressFraction => (progress.clamp(0, 100)) / 100.0;

  factory EditJob.fromJson(Map<String, dynamic> j) {
    final v = j['variant'];
    return EditJob(
      id: _str(j['id']) ?? '',
      projectId: _str(j['project_id']),
      kind: _str(j['kind']) ?? 'edit',
      parentId: _str(j['parent_id']),
      version: j['version'] is num ? (j['version'] as num).toInt() : null,
      status: EditStatus.parse(_str(j['status'])),
      progress: _int(j['progress']),
      stage: _str(j['stage']),
      displayStage: _str(j['display_stage']),
      instruction: _str(j['instruction']) ?? '',
      platform: _str(j['platform']),
      aspectRatio: _str(j['aspect_ratio']) ?? '9:16',
      durationTargetSeconds: _int(j['duration_target_seconds'], 30),
      durationSeconds: j['duration_seconds'] is num ? (j['duration_seconds'] as num).toDouble() : null,
      variant: v is Map ? VariantInfo(strategy: _str(v['strategy']) ?? '', label: _str(v['label']) ?? 'Variant') : null,
      outputUrl: _str(j['output_url']),
      thumbnailUrl: _str(j['thumbnail_url']),
      warnings: [
        if (j['warnings'] is List)
          for (final w in (j['warnings'] as List))
            if (w is String) w,
      ],
      insights: {
        if (j['insights'] is Map)
          for (final e in (j['insights'] as Map).entries)
            if (e.value is num || e.value is bool) e.key.toString(): e.value as Object,
      },
      keptRanges: [
        if (j['kept_ranges'] is List)
          for (final r in (j['kept_ranges'] as List))
            if (r is Map) CutRange.fromJson(Map<String, dynamic>.from(r)),
      ],
      error: j['error'] is Map ? ApiErrorInfo.fromJson(Map<String, dynamic>.from(j['error'] as Map)) : null,
      versions: [
        if (j['versions'] is List)
          for (final r in (j['versions'] as List))
            if (r is Map) EditRevision.fromJson(Map<String, dynamic>.from(r)),
      ],
      createdAt: _date(j['created_at']),
      updatedAt: _date(j['updated_at']),
    );
  }
}

class ApiProject {
  final String id;
  final String name;
  final DateTime createdAt;
  final DateTime updatedAt;
  final int editCount;
  final EditJob? latestEdit;
  final List<ApiAsset> assets;

  const ApiProject({
    required this.id,
    required this.name,
    required this.createdAt,
    required this.updatedAt,
    required this.editCount,
    required this.latestEdit,
    this.assets = const [],
  });

  factory ApiProject.fromJson(Map<String, dynamic> j) => ApiProject(
    id: _str(j['id']) ?? '',
    name: _str(j['name']) ?? 'Untitled',
    createdAt: _date(j['created_at']),
    updatedAt: _date(j['updated_at']),
    editCount: _int(j['edit_count']),
    latestEdit: j['latest_edit'] is Map ? EditJob.fromJson(Map<String, dynamic>.from(j['latest_edit'] as Map)) : null,
    assets: [
      if (j['assets'] is List)
        for (final a in (j['assets'] as List))
          if (a is Map) ApiAsset.fromJson(Map<String, dynamic>.from(a)),
    ],
  );
}

/// Accepted-for-processing response of create edit / revision.
class EditAccepted {
  final String id;
  final String? projectId;
  final EditStatus status;
  final int progress;

  const EditAccepted({required this.id, required this.projectId, required this.status, required this.progress});

  factory EditAccepted.fromJson(Map<String, dynamic> j) => EditAccepted(
    id: _str(j['id']) ?? '',
    projectId: _str(j['project_id']),
    status: EditStatus.parse(_str(j['status'])),
    progress: _int(j['progress']),
  );
}

DateTime? parseOptionalDate(Object? v) => _dateOrNull(v);
