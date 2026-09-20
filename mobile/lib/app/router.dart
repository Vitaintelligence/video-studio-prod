import 'package:flutter/widgets.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../features/account/account_screen.dart';
import '../features/camera/camera_screen.dart';
import '../features/clean/upload_screen.dart';
import '../features/edit/edit_screen.dart';
import '../features/edit/variants_screen.dart';
import '../features/home/home_screen.dart';
import '../features/onboarding/onboarding_controller.dart';
import '../features/onboarding/onboarding_screen.dart';
import '../features/projects/projects_screen.dart';
import '../features/status/status_screen.dart';
import 'app_shell.dart';
import 'routes.dart';

final GlobalKey<NavigatorState> _rootKey = GlobalKey<NavigatorState>(debugLabel: 'root');

/// First launch goes through onboarding once; everything else starts at Home.
GoRouter buildRouter(SharedPreferences prefs, {String initialLocation = Routes.home}) => GoRouter(
  navigatorKey: _rootKey,
  initialLocation: initialLocation,
  redirect: (context, state) {
    final done = prefs.getBool(onboardingDoneKey) ?? false;
    if (!done && state.matchedLocation != Routes.onboarding) return Routes.onboarding;
    return null;
  },
  routes: [
    StatefulShellRoute.indexedStack(
      builder: (context, state, shell) => AppShell(shell: shell),
      branches: [
        StatefulShellBranch(
          routes: [GoRoute(path: Routes.home, builder: (_, _) => const HomeScreen())],
        ),
        StatefulShellBranch(
          routes: [GoRoute(path: Routes.projects, builder: (_, _) => const ProjectsScreen())],
        ),
      ],
    ),
    GoRoute(path: Routes.onboarding, parentNavigatorKey: _rootKey, builder: (_, _) => const OnboardingScreen()),
    GoRoute(path: Routes.camera, parentNavigatorKey: _rootKey, builder: (_, _) => const CameraScreen()),
    GoRoute(path: Routes.upload, parentNavigatorKey: _rootKey, builder: (_, _) => const UploadScreen()),
    GoRoute(path: Routes.account, parentNavigatorKey: _rootKey, builder: (_, _) => const AccountScreen()),
    GoRoute(path: Routes.status, parentNavigatorKey: _rootKey, builder: (_, _) => const StatusScreen()),
    GoRoute(
      path: Routes.editPattern,
      parentNavigatorKey: _rootKey,
      builder: (_, state) => EditScreen(editId: state.pathParameters['id']!),
    ),
    GoRoute(
      path: Routes.variantsPattern,
      parentNavigatorKey: _rootKey,
      builder: (_, state) => VariantsScreen(editId: state.pathParameters['id']!),
    ),
  ],
);
