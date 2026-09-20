import 'package:flutter/material.dart';

import '../design/app_colors.dart';
import '../design/app_radius.dart';
import '../design/app_spacing.dart';
import '../design/app_typography.dart';

/// Multiline instruction editor. Return inserts a newline; the keyboard is dismissed by tapping
/// outside or scrolling (the surrounding scroll view uses `onDrag` dismissal).
class PromptField extends StatelessWidget {
  const PromptField({
    super.key,
    required this.controller,
    required this.hint,
    required this.semanticLabel,
    this.onChanged,
    this.enabled = true,
    this.minLines = 4,
    this.maxLines = 8,
    this.maxLength = 2000,
  });

  final TextEditingController controller;
  final String hint;
  final String semanticLabel;
  final ValueChanged<String>? onChanged;
  final bool enabled;
  final int minLines;
  final int maxLines;
  final int maxLength;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      textField: true,
      label: semanticLabel,
      child: TextField(
        controller: controller,
        onChanged: onChanged,
        enabled: enabled,
        minLines: minLines,
        maxLines: maxLines,
        maxLength: maxLength,
        keyboardType: TextInputType.multiline,
        textInputAction: TextInputAction.newline,
        textCapitalization: TextCapitalization.sentences,
        scrollPadding: const EdgeInsets.all(AppSpacing.xxxl * 4),
        style: AppTypography.body,
        cursorColor: AppColors.accentText,
        decoration: InputDecoration(
          hintText: hint,
          hintStyle: AppTypography.body.copyWith(color: AppColors.textMuted),
          counterText: '',
          filled: true,
          fillColor: AppColors.surface,
          contentPadding: const EdgeInsets.all(AppSpacing.md),
          border: const OutlineInputBorder(borderRadius: AppRadius.mediumAll, borderSide: BorderSide.none),
          enabledBorder: const OutlineInputBorder(borderRadius: AppRadius.mediumAll, borderSide: BorderSide.none),
          disabledBorder: const OutlineInputBorder(borderRadius: AppRadius.mediumAll, borderSide: BorderSide.none),
          focusedBorder: const OutlineInputBorder(
            borderRadius: AppRadius.mediumAll,
            borderSide: BorderSide(color: AppColors.accent, width: 2),
          ),
        ),
      ),
    );
  }
}
