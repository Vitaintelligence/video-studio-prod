/// Spacing scale. Use these instead of literal paddings.
abstract final class AppSpacing {
  static const double xxs = 4;
  static const double xs = 8;
  static const double sm = 12;
  static const double md = 16;
  static const double lg = 20;
  static const double xl = 24;
  static const double xxl = 32;
  static const double xxxl = 40;
  static const double huge = 48;

  /// Screen edge inset.
  static const double gutter = md;

  /// Minimum comfortable tap target (iOS HIG: 44pt).
  static const double minTap = 44;

  /// Control heights.
  static const double buttonHeight = 52;
  static const double fieldHeight = 52;

  /// Bottom scroll offset to clear the floating navigation pill.
  static const double floatingBarOffset = 100;
}
