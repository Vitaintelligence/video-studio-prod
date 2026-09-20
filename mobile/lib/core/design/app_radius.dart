import 'package:flutter/painting.dart';

/// Three corner radii. Pills (`pill`) are for small tags only.
abstract final class AppRadius {
  static const double small = 8;
  static const double medium = 12;
  static const double large = 16;
  static const double media = 18;
  static const double sheet = 24;
  static const double pill = 999;

  static const BorderRadius smallAll = BorderRadius.all(Radius.circular(small));
  static const BorderRadius mediumAll = BorderRadius.all(Radius.circular(medium));
  static const BorderRadius largeAll = BorderRadius.all(Radius.circular(large));
  static const BorderRadius mediaAll = BorderRadius.all(Radius.circular(media));
  static const BorderRadius pillAll = BorderRadius.all(Radius.circular(pill));
}
