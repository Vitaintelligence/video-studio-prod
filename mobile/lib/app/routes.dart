/// Central route paths. Screens navigate through these helpers only.
abstract final class Routes {
  static const String onboarding = '/onboarding';
  static const String home = '/home';
  static const String projects = '/projects';
  static const String camera = '/camera';
  static const String upload = '/upload';
  static const String account = '/account';
  static const String status = '/status';

  static const String editPattern = '/edits/:id';
  static const String variantsPattern = '/edits/:id/variants';

  static String edit(String id) => '/edits/$id';
  static String variants(String id) => '/edits/$id/variants';
}
