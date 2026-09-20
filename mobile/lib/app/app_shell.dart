import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';

import '../core/design/app_colors.dart';
import '../core/design/app_radius.dart';
import '../core/design/app_spacing.dart';
import '../core/design/app_typography.dart';
import 'routes.dart';

/// Root scaffold: Home, a dominant Camera action in the center, and Projects. The bar hides while
/// the keyboard is open so primary actions stay directly above it.
class AppShell extends StatelessWidget {
  const AppShell({super.key, required this.shell});

  final StatefulNavigationShell shell;

  @override
  Widget build(BuildContext context) {
    final keyboardOpen = MediaQuery.viewInsetsOf(context).bottom > 0;
    return Scaffold(
      resizeToAvoidBottomInset: false,
      body: shell,
      bottomNavigationBar: keyboardOpen
          ? null
          : DecoratedBox(
              decoration: const BoxDecoration(
                color: AppColors.surface,
                border: Border(top: BorderSide(color: AppColors.surfaceBorder)),
                boxShadow: [BoxShadow(color: Color(0x66000000), blurRadius: 24, offset: Offset(0, -8))],
              ),
              child: SafeArea(
                top: false,
                child: SizedBox(
                  height: 64,
                  child: Row(
                    children: [
                      _NavItem(
                        label: 'Home',
                        icon: CupertinoIcons.house,
                        selectedIcon: CupertinoIcons.house_fill,
                        selected: shell.currentIndex == 0,
                        onTap: () => shell.goBranch(0, initialLocation: shell.currentIndex == 0),
                      ),
                      const _CameraAction(),
                      _NavItem(
                        label: 'Projects',
                        icon: CupertinoIcons.rectangle_stack,
                        selectedIcon: CupertinoIcons.rectangle_stack_fill,
                        selected: shell.currentIndex == 1,
                        onTap: () => shell.goBranch(1, initialLocation: shell.currentIndex == 1),
                      ),
                    ],
                  ),
                ),
              ),
            ),
    );
  }
}

class _CameraAction extends StatelessWidget {
  const _CameraAction();

  @override
  Widget build(BuildContext context) {
    void open() {
      HapticFeedback.mediumImpact();
      context.push(Routes.camera);
    }

    return Expanded(
      child: Semantics(
        button: true,
        label: 'Record',
        excludeSemantics: true,
        onTap: open,
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: open,
          child: Center(
            child: Container(
              width: 64,
              height: 48,
              decoration: const BoxDecoration(
                gradient: AppColors.brandGradient,
                borderRadius: AppRadius.mediumAll,
                boxShadow: [BoxShadow(color: Color(0x66765CF6), blurRadius: 18, offset: Offset(0, 6))],
              ),
              child: const Icon(CupertinoIcons.camera_fill, size: 24, color: AppColors.onAccent),
            ),
          ),
        ),
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({
    required this.label,
    required this.icon,
    required this.selectedIcon,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final IconData icon;
  final IconData selectedIcon;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final color = selected ? AppColors.accentText : AppColors.textMuted;
    return Expanded(
      child: Semantics(
        button: true,
        selected: selected,
        label: label,
        excludeSemantics: true,
        onTap: onTap,
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: onTap,
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(selected ? selectedIcon : icon, size: 24, color: color),
              const SizedBox(height: AppSpacing.xxs),
              Text(label, style: AppTypography.caption.copyWith(color: color)),
            ],
          ),
        ),
      ),
    );
  }
}
