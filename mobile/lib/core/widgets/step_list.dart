import 'package:flutter/cupertino.dart';

import '../design/app_colors.dart';
import '../design/app_spacing.dart';
import '../design/app_typography.dart';

enum StepStatus { done, active, pending }

/// Vertical checklist of stages. Status is shown by icon and by accessibility label, not color alone.
class StepList extends StatelessWidget {
  const StepList({super.key, required this.steps});

  final List<(String label, StepStatus status)> steps;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final (label, status) in steps)
          Semantics(
            container: true,
            label:
                '$label, ${switch (status) {
                  StepStatus.done => 'done',
                  StepStatus.active => 'in progress',
                  StepStatus.pending => 'waiting',
                }}',
            excludeSemantics: true,
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs),
              child: Row(
                children: [
                  SizedBox(
                    width: 24,
                    height: 24,
                    child: switch (status) {
                      StepStatus.done => const Icon(
                        CupertinoIcons.checkmark_circle_fill,
                        size: 22,
                        color: AppColors.success,
                      ),
                      StepStatus.active => const CupertinoActivityIndicator(radius: 9),
                      StepStatus.pending => const Icon(CupertinoIcons.circle, size: 22, color: AppColors.textMuted),
                    },
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  Expanded(
                    child: Text(
                      label,
                      style: AppTypography.body.copyWith(
                        color: status == StepStatus.pending ? AppColors.textMuted : AppColors.textPrimary,
                        fontWeight: status == StepStatus.active ? FontWeight.w600 : FontWeight.w400,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }
}
