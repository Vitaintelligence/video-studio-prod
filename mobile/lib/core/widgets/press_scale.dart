import 'package:flutter/widgets.dart';

import '../design/app_motion.dart';

/// A subtle shared press response used by onboarding choices and the bottom navigation.
class PressScale extends StatefulWidget {
  const PressScale({super.key, required this.onTap, required this.child, this.pressedScale = 0.94});

  final VoidCallback? onTap;
  final Widget child;
  final double pressedScale;

  @override
  State<PressScale> createState() => _PressScaleState();
}

class _PressScaleState extends State<PressScale> {
  bool _pressed = false;

  void _set(bool value) {
    if (_pressed != value) setState(() => _pressed = value);
  }

  @override
  Widget build(BuildContext context) => GestureDetector(
    behavior: HitTestBehavior.opaque,
    onTapDown: widget.onTap == null ? null : (_) => _set(true),
    onTapUp: widget.onTap == null ? null : (_) => _set(false),
    onTapCancel: widget.onTap == null ? null : () => _set(false),
    onTap: widget.onTap,
    child: AnimatedScale(
      scale: _pressed ? widget.pressedScale : 1,
      duration: AppMotion.allowed(context, AppMotion.quick),
      curve: AppMotion.enter,
      child: widget.child,
    ),
  );
}
