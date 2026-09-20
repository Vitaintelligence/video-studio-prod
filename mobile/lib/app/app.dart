import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'providers.dart';

import '../core/design/app_colors.dart';
import '../core/design/app_theme.dart';
import 'router.dart';

class AdCutApp extends ConsumerStatefulWidget {
  const AdCutApp({super.key, this.router});

  /// Injected by tests; production builds the real router.
  final GoRouter? router;

  @override
  ConsumerState<AdCutApp> createState() => _AdCutAppState();
}

class _AdCutAppState extends ConsumerState<AdCutApp> {
  late final GoRouter _router = widget.router ?? buildRouter(ref.read(preferencesProvider));

  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(
      title: 'AdCut',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.dark,
      darkTheme: AppTheme.dark,
      themeMode: ThemeMode.dark,
      routerConfig: _router,
      builder: (context, child) => AnnotatedRegion<SystemUiOverlayStyle>(
        value: const SystemUiOverlayStyle(
          statusBarColor: Colors.transparent,
          statusBarIconBrightness: Brightness.light,
          systemNavigationBarColor: AppColors.background,
          systemNavigationBarIconBrightness: Brightness.light,
        ),
        child: child ?? const SizedBox.shrink(),
      ),
    );
  }
}
