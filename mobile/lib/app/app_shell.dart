import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';

import '../core/design/app_colors.dart';
import '../core/design/app_motion.dart';
import '../core/design/app_radius.dart';
import '../core/design/app_spacing.dart';
import '../core/widgets/press_scale.dart';
import 'active_work_bar.dart';
import 'routes.dart';

/// Root scaffold with a compact, floating three-action navigation pill.
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
          : Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const ActiveWorkBar(),
                SafeArea(
                  top: false,
                  minimum: const EdgeInsets.only(bottom: AppSpacing.xs),
                  child: SizedBox(
                    height: 62,
                    child: Center(
                      child: Container(
                        width: 210,
                        height: 56,
                        padding: const EdgeInsets.all(5),
                        decoration: BoxDecoration(
                          color: AppColors.surfaceRaised,
                          borderRadius: AppRadius.pillAll,
                          border: Border.all(color: AppColors.surfaceBorder),
                          boxShadow: const [BoxShadow(color: Color(0x99000000), blurRadius: 22, offset: Offset(0, 8))],
                        ),
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
                ),
              ],
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
        child: PressScale(
          onTap: open,
          child: Center(
            child: Container(
              width: 50,
              height: 46,
              decoration: const BoxDecoration(color: AppColors.accent, borderRadius: AppRadius.pillAll),
              child: const Icon(CupertinoIcons.camera_fill, size: 22, color: AppColors.onAccent),
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
    final color = selected ? AppColors.textPrimary : AppColors.textMuted;
    return Expanded(
      child: Semantics(
        button: true,
        selected: selected,
        label: label,
        excludeSemantics: true,
        onTap: onTap,
        child: PressScale(
          onTap: () {
            HapticFeedback.selectionClick();
            onTap();
          },
          child: Center(
            child: AnimatedContainer(
              duration: AppMotion.allowed(context, AppMotion.standard),
              curve: AppMotion.enter,
              width: 50,
              height: 46,
              decoration: BoxDecoration(
                color: selected ? AppColors.accentSoft : AppColors.surfaceRaised,
                borderRadius: AppRadius.pillAll,
              ),
              child: AnimatedSwitcher(
                duration: AppMotion.allowed(context, AppMotion.standard),
                switchInCurve: AppMotion.emphasis,
                switchOutCurve: AppMotion.enter,
                transitionBuilder: (child, animation) => ScaleTransition(
                  scale: Tween<double>(begin: 0.72, end: 1).animate(animation),
                  child: FadeTransition(opacity: animation, child: child),
                ),
                child: Icon(selected ? selectedIcon : icon, key: ValueKey(selected), size: 21, color: color),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
