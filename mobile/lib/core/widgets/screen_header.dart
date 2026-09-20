import 'package:flutter/cupertino.dart';
import 'package:go_router/go_router.dart';

import '../../app/routes.dart';

import '../design/app_spacing.dart';
import '../design/app_typography.dart';
import 'buttons.dart';

/// Header for pushed screens: back button, title, optional trailing action.
class ScreenHeader extends StatelessWidget {
  const ScreenHeader({super.key, required this.title, this.trailing, this.onBack});

  final String title;
  final Widget? trailing;

  /// Defaults to popping the route (or going to `fallbackRoute` semantics handled by the caller).
  final VoidCallback? onBack;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 56,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xxs),
        child: Row(
          children: [
            AppIconButton(
              icon: CupertinoIcons.back,
              label: 'Back',
              onPressed: onBack ?? () => context.canPop() ? context.pop() : context.go(Routes.home),
            ),
            Expanded(
              child: Semantics(
                header: true,
                child: Text(title, style: AppTypography.heading, maxLines: 1, overflow: TextOverflow.ellipsis),
              ),
            ),
            ?trailing,
          ],
        ),
      ),
    );
  }
}
