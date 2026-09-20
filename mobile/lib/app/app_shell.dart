import 'dart:ui' show ImageFilter;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/design/app_colors.dart';
import 'active_work_bar.dart';
import 'routes.dart';

/// Root scaffold: Home, a dominant Camera action in the center, and Projects.
/// Features a centralized, floating pill navigation dock with glassmorphism and energetic cyan accents.
class AppShell extends ConsumerWidget {
  const AppShell({super.key, required this.shell});

  final StatefulNavigationShell shell;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final keyboardOpen = MediaQuery.viewInsetsOf(context).bottom > 0;
    return Scaffold(
      extendBody: true,
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
                  maintainBottomViewPadding: true,
                  child: Padding(
                    padding: const EdgeInsets.only(bottom: 16),
                    child: Center(heightFactor: 1.0, child: _NavPill(shell: shell)),
                  ),
                ),
              ],
            ),
    );
  }
}

class _NavPill extends StatelessWidget {
  const _NavPill({required this.shell});

  final StatefulNavigationShell shell;

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(100),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 20, sigmaY: 20),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
          decoration: BoxDecoration(
            color: const Color(0xE810131B),
            borderRadius: BorderRadius.circular(100),
            border: Border.all(
              color: Colors.white.withValues(alpha: 0.09),
              width: 1,
            ),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.5),
                blurRadius: 28,
                offset: const Offset(0, 10),
              ),
              BoxShadow(
                color: AppColors.accent.withValues(alpha: 0.14),
                blurRadius: 26,
                offset: const Offset(0, 2),
              ),
            ],
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              _NavPillItem(
                label: 'Home',
                icon: Icons.grid_view_rounded,
                selectedIcon: Icons.grid_view_rounded,
                selected: shell.currentIndex == 0,
                onTap: () => shell.goBranch(0, initialLocation: shell.currentIndex == 0),
              ),
              const SizedBox(width: 8),
              const _CenterCameraAction(),
              const SizedBox(width: 8),
              _NavPillItem(
                label: 'Projects',
                icon: Icons.video_library_outlined,
                selectedIcon: Icons.video_library_rounded,
                selected: shell.currentIndex == 1,
                onTap: () => shell.goBranch(1, initialLocation: shell.currentIndex == 1),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _CenterCameraAction extends StatefulWidget {
  const _CenterCameraAction();

  @override
  State<_CenterCameraAction> createState() => _CenterCameraActionState();
}

class _CenterCameraActionState extends State<_CenterCameraAction> {
  bool _hovered = false;
  bool _pressed = false;

  void _open() {
    HapticFeedback.mediumImpact();
    context.push(Routes.camera);
  }

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: 'Record',
      excludeSemantics: true,
      onTap: _open,
      child: MouseRegion(
        cursor: SystemMouseCursors.click,
        onEnter: (_) => setState(() => _hovered = true),
        onExit: (_) => setState(() => _hovered = false),
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTapDown: (_) => setState(() => _pressed = true),
          onTapUp: (_) => setState(() => _pressed = false),
          onTapCancel: () => setState(() => _pressed = false),
          onTap: _open,
          child: AnimatedScale(
            scale: _pressed ? 0.92 : (_hovered ? 1.05 : 1.0),
            duration: const Duration(milliseconds: 150),
            curve: Curves.easeOutCubic,
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              width: 52,
              height: 42,
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                  colors: [
                    Color(0xFF00F5FF),
                    Color(0xFF00BCE6),
                  ],
                ),
                borderRadius: BorderRadius.circular(100),
                border: Border.all(
                  color: Colors.white.withValues(alpha: 0.25),
                  width: 1,
                ),
                boxShadow: [
                  BoxShadow(
                    color: AppColors.accent.withValues(alpha: _hovered ? 0.6 : 0.4),
                    blurRadius: _hovered ? 20 : 14,
                    offset: const Offset(0, 3),
                  ),
                  BoxShadow(
                    color: AppColors.accent.withValues(alpha: 0.2),
                    blurRadius: 24,
                    offset: const Offset(0, 6),
                  ),
                ],
              ),
              child: const Icon(
                Icons.videocam_rounded,
                size: 24,
                color: AppColors.onAccent,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _NavPillItem extends StatefulWidget {
  const _NavPillItem({
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
  State<_NavPillItem> createState() => _NavPillItemState();
}

class _NavPillItemState extends State<_NavPillItem> {
  bool _hovered = false;

  @override
  Widget build(BuildContext context) {
    final active = widget.selected;
    final iconColor = active
        ? AppColors.accent
        : (_hovered ? AppColors.textPrimary : AppColors.textMuted);

    return Semantics(
      button: true,
      selected: active,
      label: widget.label,
      excludeSemantics: true,
      onTap: widget.onTap,
      child: MouseRegion(
        cursor: SystemMouseCursors.click,
        onEnter: (_) => setState(() => _hovered = true),
        onExit: (_) => setState(() => _hovered = false),
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: () {
            HapticFeedback.selectionClick();
            widget.onTap();
          },
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            curve: Curves.easeOutCubic,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            decoration: BoxDecoration(
              color: active
                  ? AppColors.accentSubtle
                  : (_hovered ? AppColors.surfacePressed.withValues(alpha: 0.6) : Colors.transparent),
              borderRadius: BorderRadius.circular(100),
              border: Border.all(
                color: active
                    ? AppColors.accent.withValues(alpha: 0.3)
                    : (_hovered ? Colors.white.withValues(alpha: 0.1) : Colors.transparent),
                width: 1,
              ),
            ),
            child: Icon(
              active ? widget.selectedIcon : widget.icon,
              size: 22,
              color: iconColor,
            ),
          ),
        ),
      ),
    );
  }
}
