import 'package:flutter/cupertino.dart';
import 'package:flutter/services.dart';

import '../design/app_colors.dart';
import '../design/app_radius.dart';
import '../design/app_spacing.dart';
import '../design/app_typography.dart';

enum _ButtonKind { primary, secondary, danger }

/// Solid filled button shell shared by [PrimaryButton], [SecondaryButton] and [DangerButton].
/// Keeps its size while loading and ignores taps when loading or disabled.
class _SolidButton extends StatefulWidget {
  const _SolidButton({
    required this.kind,
    required this.label,
    required this.onPressed,
    required this.isLoading,
    required this.leadingIcon,
    required this.expand,
  });

  final _ButtonKind kind;
  final String label;
  final VoidCallback? onPressed;
  final bool isLoading;
  final IconData? leadingIcon;
  final bool expand;

  @override
  State<_SolidButton> createState() => _SolidButtonState();
}

class _SolidButtonState extends State<_SolidButton> {
  bool _pressed = false;

  bool get _enabled => widget.onPressed != null && !widget.isLoading;
  bool get _disabledLook => widget.onPressed == null && !widget.isLoading;

  Color get _fill {
    if (_disabledLook) return AppColors.accentDisabled;
    return switch (widget.kind) {
      _ButtonKind.primary => _pressed ? AppColors.accentPressed : AppColors.accent,
      _ButtonKind.secondary => _pressed ? AppColors.surfacePressed : AppColors.surfaceRaised,
      _ButtonKind.danger => _pressed ? AppColors.destructivePressed : AppColors.destructive,
    };
  }

  Color get _foreground {
    if (_disabledLook) return AppColors.textMuted;
    return switch (widget.kind) {
      _ButtonKind.primary => AppColors.onAccent,
      _ButtonKind.secondary => AppColors.textPrimary,
      _ButtonKind.danger => AppColors.onDestructive,
    };
  }

  void _tap() {
    HapticFeedback.selectionClick();
    widget.onPressed!();
  }

  @override
  Widget build(BuildContext context) {
    final content = Row(
      mainAxisSize: MainAxisSize.min,
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        if (widget.leadingIcon != null) ...[
          Icon(widget.leadingIcon, size: 20, color: _foreground),
          const SizedBox(width: AppSpacing.xs),
        ],
        Flexible(
          child: Text(
            widget.label,
            style: AppTypography.label.copyWith(color: _foreground),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
        ),
      ],
    );
    return Semantics(
      container: true,
      button: true,
      enabled: _enabled,
      label: widget.isLoading ? '${widget.label}, in progress' : widget.label,
      excludeSemantics: true,
      onTap: _enabled ? _tap : null,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTapDown: _enabled ? (_) => setState(() => _pressed = true) : null,
        onTapUp: _enabled ? (_) => setState(() => _pressed = false) : null,
        onTapCancel: _enabled ? () => setState(() => _pressed = false) : null,
        onTap: _enabled ? _tap : null,
        child: ConstrainedBox(
          constraints: BoxConstraints(
            minHeight: AppSpacing.buttonHeight,
            minWidth: widget.expand ? double.infinity : 0,
          ),
          child: DecoratedBox(
            decoration: BoxDecoration(color: _fill, borderRadius: AppRadius.mediumAll),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg, vertical: AppSpacing.sm),
              child: Stack(
                alignment: Alignment.center,
                children: [
                  Visibility(
                    visible: !widget.isLoading,
                    maintainSize: true,
                    maintainAnimation: true,
                    maintainState: true,
                    child: content,
                  ),
                  if (widget.isLoading) CupertinoActivityIndicator(color: _foreground),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// The single dominant action on a screen: solid accent fill.
class PrimaryButton extends StatelessWidget {
  const PrimaryButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.isLoading = false,
    this.leadingIcon,
    this.expand = true,
  });

  final String label;

  /// `null` disables the button.
  final VoidCallback? onPressed;
  final bool isLoading;
  final IconData? leadingIcon;
  final bool expand;

  @override
  Widget build(BuildContext context) => _SolidButton(
    kind: _ButtonKind.primary,
    label: label,
    onPressed: onPressed,
    isLoading: isLoading,
    leadingIcon: leadingIcon,
    expand: expand,
  );
}

/// Supporting action: solid raised neutral surface.
class SecondaryButton extends StatelessWidget {
  const SecondaryButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.isLoading = false,
    this.leadingIcon,
    this.expand = true,
  });

  final String label;
  final VoidCallback? onPressed;
  final bool isLoading;
  final IconData? leadingIcon;
  final bool expand;

  @override
  Widget build(BuildContext context) => _SolidButton(
    kind: _ButtonKind.secondary,
    label: label,
    onPressed: onPressed,
    isLoading: isLoading,
    leadingIcon: leadingIcon,
    expand: expand,
  );
}

/// Destructive action (cancel a running job).
class DangerButton extends StatelessWidget {
  const DangerButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.isLoading = false,
    this.leadingIcon,
    this.expand = true,
  });

  final String label;
  final VoidCallback? onPressed;
  final bool isLoading;
  final IconData? leadingIcon;
  final bool expand;

  @override
  Widget build(BuildContext context) => _SolidButton(
    kind: _ButtonKind.danger,
    label: label,
    onPressed: onPressed,
    isLoading: isLoading,
    leadingIcon: leadingIcon,
    expand: expand,
  );
}

/// Low-emphasis text action.
class TertiaryButton extends StatelessWidget {
  const TertiaryButton({super.key, required this.label, required this.onPressed, this.leadingIcon});

  final String label;
  final VoidCallback? onPressed;
  final IconData? leadingIcon;

  @override
  Widget build(BuildContext context) {
    final color = onPressed == null ? AppColors.textMuted : AppColors.accentText;
    return Semantics(
      container: true,
      button: true,
      enabled: onPressed != null,
      label: label,
      excludeSemantics: true,
      onTap: onPressed,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onPressed,
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: AppSpacing.minTap, minWidth: AppSpacing.minTap),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xs),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                if (leadingIcon != null) ...[
                  Icon(leadingIcon, size: 18, color: color),
                  const SizedBox(width: AppSpacing.xxs),
                ],
                Flexible(
                  child: Text(label, style: AppTypography.label.copyWith(color: color)),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Icon-only action with a full-size hit area and a required accessibility label.
class AppIconButton extends StatelessWidget {
  const AppIconButton({super.key, required this.icon, required this.label, required this.onPressed, this.color});

  final IconData icon;
  final String label;
  final VoidCallback? onPressed;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      container: true,
      button: true,
      enabled: onPressed != null,
      label: label,
      excludeSemantics: true,
      onTap: onPressed,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onPressed,
        child: SizedBox(
          width: AppSpacing.minTap,
          height: AppSpacing.minTap,
          child: Icon(icon, size: 22, color: color ?? AppColors.textPrimary),
        ),
      ),
    );
  }
}
