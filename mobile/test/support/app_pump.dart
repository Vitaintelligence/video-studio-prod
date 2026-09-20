import 'dart:io';

import 'package:adcut_mobile/app/app.dart';
import 'package:adcut_mobile/app/router.dart';
import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'harness.dart';

/// Phone sizes used for layout checks (logical points).
enum Phone {
  compact(Size(375, 667)), // iPhone SE
  standard(Size(393, 852)), // iPhone Pro
  large(Size(430, 932)); // iPhone Pro Max

  const Phone(this.size);
  final Size size;
}

/// Loads real Roboto so screenshots show readable text instead of test-font blocks.
Future<void> loadTestFonts() async {
  final root = Platform.environment['FLUTTER_ROOT'];
  if (root == null) return;
  final dir = '$root/bin/cache/artifacts/material_fonts';
  final loader = FontLoader('Roboto');
  for (final f in ['roboto-regular.ttf', 'roboto-medium.ttf', 'roboto-bold.ttf']) {
    final file = File('$dir/$f');
    if (file.existsSync()) {
      final bytes = file.readAsBytesSync();
      loader.addFont(Future.value(ByteData.sublistView(bytes)));
    }
  }
  await loader.load();
  final icons = FontLoader('packages/cupertino_icons/CupertinoIcons')
    ..addFont(rootBundle.load('packages/cupertino_icons/assets/CupertinoIcons.ttf'));
  await icons.load();
}

SemanticsHandle? _semantics;

/// Pumps the whole app against the fake backend at [phone] size.
Future<void> pumpApp(
  WidgetTester tester,
  Harness harness, {
  String location = '/home',
  Phone phone = Phone.standard,
  double textScale = 1,
}) async {
  tester.view.physicalSize = phone.size * 3;
  tester.view.devicePixelRatio = 3;
  tester.platformDispatcher.textScaleFactorTestValue = textScale;
  _semantics = tester.ensureSemantics();
  addTearDown(tester.view.reset);
  addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
  await tester.pumpWidget(
    ProviderScope(
      retry: (_, _) => null,
      overrides: harness.overrides,
      child: AdCutApp(router: buildRouter(harness.prefs, initialLocation: location)),
    ),
  );
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
}

/// Unmounts the app so timers and controllers are disposed before the test ends.
Future<void> unmount(WidgetTester tester) async {
  _semantics?.dispose();
  _semantics = null;
  await tester.pumpWidget(const SizedBox());
  await tester.pump(const Duration(milliseconds: 50));
}

/// Waits (in real time, pumping the widget tree) for something that depends on real file or socket I/O.
Future<void> pumpUntil(WidgetTester tester, bool Function() condition, {int maxTries = 400}) async {
  for (var i = 0; i < maxTries; i++) {
    if (condition()) return;
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 10)));
    await tester.pump();
  }
  throw StateError('condition not met while pumping');
}
