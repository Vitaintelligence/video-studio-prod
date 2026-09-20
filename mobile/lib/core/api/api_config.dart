/// Central backend configuration. The base URL lives here and nowhere else.
///
/// Override at build/run time:
///   flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000 --dart-define=API_TOKEN=...
///
/// SECURITY: `API_TOKEN` is a DEVELOPMENT-ONLY stand-in for real per-user authentication.
/// Never build a release/TestFlight binary with a backend master token; replace this with
/// a per-user credential before shipping. Provider keys (OpenRouter, R2, Anthropic, ...)
/// must never appear in this app.
abstract final class ApiConfig {
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'https://video-studio-prod-production.up.railway.app',
  );

  /// Development bearer token (see the security note above). Empty when not provided.
  static const String devToken = String.fromEnvironment('API_TOKEN');

  static const Duration requestTimeout = Duration(seconds: 30);
  static const Duration uploadTimeout = Duration(minutes: 30);

  /// Client-side size guard (the server enforces its own limit too).
  static const int maxUploadBytes = 500 * 1024 * 1024;

  static const List<String> allowedVideoExtensions = ['mp4', 'mov', 'm4v'];

  static const Map<String, String> contentTypeByExtension = {
    'mp4': 'video/mp4',
    'mov': 'video/quicktime',
    'm4v': 'video/x-m4v',
  };
}
