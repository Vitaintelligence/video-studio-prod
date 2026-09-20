import 'package:flutter/material.dart';

import '../design/app_colors.dart';
import '../design/app_radius.dart';

/// Flat progress bar. `value` is 0..1 from real data; `null` renders an indeterminate bar.
class AppProgressBar extends StatelessWidget {
  const AppProgressBar({super.key, required this.value, this.semanticLabel = 'Progress'});

  final double? value;
  final String semanticLabel;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: semanticLabel,
      value: value == null ? null : '${(value! * 100).round()} percent',
      child: ClipRRect(
        borderRadius: AppRadius.smallAll,
        child: LinearProgressIndicator(
          value: value,
          minHeight: 4,
          backgroundColor: AppColors.surfaceRaised,
          color: AppColors.accent,
        ),
      ),
    );
  }
}
