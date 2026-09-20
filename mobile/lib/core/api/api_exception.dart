/// Typed API failure. Never carries raw server text beyond the sanitized `message` the
/// backend already vetted, and never a stack trace or credential.
class ApiException implements Exception {
  final String code;
  final String message;
  final int? statusCode;
  final String? requestId;

  const ApiException({required this.code, required this.message, this.statusCode, this.requestId});

  const ApiException.network([String detail = 'network'])
    : code = 'NETWORK_ERROR',
      message = 'No connection to the server.',
      statusCode = null,
      requestId = null;

  const ApiException.uploadFailed()
    : code = 'UPLOAD_FAILED',
      message = 'The upload did not finish.',
      statusCode = null,
      requestId = null;

  const ApiException.invalidMedia(String why)
    : code = 'INVALID_MEDIA',
      message = why,
      statusCode = null,
      requestId = null;

  bool get isNetwork => code == 'NETWORK_ERROR' || code == 'TIMEOUT_CLIENT';

  /// Worth retrying automatically (transient): network, timeouts, 429, 5xx.
  bool get isTransient =>
      isNetwork || statusCode == 429 || (statusCode != null && statusCode! >= 500) || code == 'QUEUE_UNAVAILABLE';

  bool get isUnauthorized => statusCode == 401 || code == 'UNAUTHORIZED';

  /// Consumer-facing copy. Never mentions infrastructure or providers.
  String get userMessage {
    switch (code) {
      case 'NETWORK_ERROR':
      case 'TIMEOUT_CLIENT':
        return "Can't reach AdCut right now. Check your connection and try again.";
      case 'PHOTOS_DENIED':
        return 'Allow AdCut to save to Photos in Settings, then try again.';
      case 'EXPORT_FAILED':
        return 'Export failed. Try again.';
      case 'UPLOAD_FAILED':
        return "We couldn't upload your footage. Please try again.";
      case 'INVALID_MEDIA':
        return message;
      case 'UNAUTHORIZED':
        return 'Your session is not authorized. Please sign in again.';
      case 'RATE_LIMITED':
        return 'Too many requests. Please wait a moment and try again.';
      case 'PAYLOAD_TOO_LARGE':
        return 'That file is too large. Try a shorter clip.';
      case 'PROVIDER_UNAVAILABLE':
      case 'PIPELINE_UNAVAILABLE':
      case 'QUEUE_UNAVAILABLE':
        return 'Editing is temporarily unavailable. Please try again shortly.';
      case 'BUDGET_EXCEEDED':
        return 'This edit was too complex. Try a shorter or simpler instruction.';
      case 'STORAGE_FAILED':
        return "We couldn't save your video. Please try again.";
      case 'TIMEOUT':
        return 'This edit took too long. Please try again.';
      case 'EDIT_FAILED':
      case 'GENERATION_FAILED':
      case 'OUTPUT_INVALID':
        return "We couldn't finish this edit.";
      case 'INVALID_REQUEST':
      case 'IDEMPOTENCY_CONFLICT':
        return message.isNotEmpty ? message : 'Please check your input and try again.';
      case 'NOT_FOUND':
      case 'GENERATION_NOT_FOUND':
        return "We couldn't find that item.";
      default:
        return statusCode != null && statusCode! >= 500
            ? 'Something went wrong on our side. Please try again.'
            : "We couldn't finish that. Please try again.";
    }
  }

  @override
  String toString() => 'ApiException($code${statusCode != null ? ', $statusCode' : ''})';
}
