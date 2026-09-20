import 'dart:io';

import 'package:adcut_mobile/features/camera/camera_controller.dart';
import 'package:adcut_mobile/features/clean/clean_controller.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/app_pump.dart';
import 'support/harness.dart';

Future<void> settle(WidgetTester tester, {int steps = 6}) async {
  for (var i = 0; i < steps; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

void main() {
  setUpAll(loadTestFonts);

  group('camera countdown and retake', () {
    test('counts down before recording starts', () async {
      final h = await Harness.create();
      final c = h.container(countdown: 1);
      addTearDown(c.dispose);
      final phases = <CameraPhase>[];
      c.listen(cameraSessionProvider, (_, s) => phases.add(s.phase));
      final s = c.read(cameraSessionProvider.notifier);
      await s.open();

      await s.startRecording();

      expect(phases, containsAllInOrder([CameraPhase.countdown, CameraPhase.recording]));
      expect(h.camera.startCount, 1);
    });

    test('cancelling the countdown never starts recording', () async {
      final h = await Harness.create();
      final c = h.container(countdown: 2);
      addTearDown(c.dispose);
      c.listen(cameraSessionProvider, (_, _) {});
      final s = c.read(cameraSessionProvider.notifier);
      await s.open();

      final started = s.startRecording();
      await Future<void>.delayed(const Duration(milliseconds: 50));
      expect(c.read(cameraSessionProvider).isCountingDown, isTrue);
      expect(c.read(cameraSessionProvider).countdown, 2);
      s.cancelCountdown();
      await started;

      expect(c.read(cameraSessionProvider).phase, CameraPhase.ready);
      expect(h.camera.startCount, 0);
    });

    test('retake discards the take: file deleted, nothing uploaded, ready again', () async {
      final h = await Harness.create();
      final c = h.container();
      addTearDown(c.dispose);
      c.listen(cameraSessionProvider, (_, _) {});
      final s = c.read(cameraSessionProvider.notifier);
      await s.open();
      await s.startRecording();
      expect(c.read(cameraSessionProvider).isRecording, isTrue);

      await s.retake();

      expect(c.read(cameraSessionProvider).phase, CameraPhase.ready);
      expect(c.read(cameraSessionProvider).elapsed, Duration.zero);
      expect(File(h.camera.lastFile!).existsSync(), isFalse);
      expect(c.read(cleanControllerProvider).phase, CleanPhase.idle);
      expect(h.backend.requests, isEmpty);
    });
  });

  group('raw vs cut', () {
    testWidgets('the toggle appears only when the raw recording is still on the device', (tester) async {
      final raw = await tester.runAsync(() => tempVideo('raw.mp4'));
      final h = await Harness.create(prefs: {'raw_path.edit-1': raw!, 'raw_seconds.edit-1': 77.0});
      h.backend.assets['asset-1'] = {'id': 'asset-1', 'status': 'uploaded'};
      h.backend.newEditForTest('Remove awkward pauses.');
      h.backend.edits['edit-1']!['status'] = 'completed';
      await pumpApp(tester, h, location: '/edits/edit-1');
      await settle(tester);

      expect(find.text('Cut'), findsOneWidget);
      expect(find.text('Raw'), findsOneWidget);
      await tester.tap(find.text('Raw'));
      await settle(tester, steps: 3);
      await tester.tap(find.text('Cut'));
      await settle(tester, steps: 3);
      await unmount(tester);

      final gone = await Harness.create(prefs: {'raw_path.edit-1': '${raw}_missing.mp4'});
      gone.backend.assets['asset-1'] = {'id': 'asset-1', 'status': 'uploaded'};
      gone.backend.newEditForTest('Remove awkward pauses.');
      gone.backend.edits['edit-1']!['status'] = 'completed';
      await pumpApp(tester, gone, location: '/edits/edit-1');
      await settle(tester);
      expect(find.text('Raw'), findsNothing, reason: 'never offer a raw video that is gone');
      await unmount(tester);
    });

    test('a clean remembers the raw file path for the result screen', () async {
      final h = await Harness.create();
      final c = h.container();
      addTearDown(c.dispose);
      c.listen(cameraSessionProvider, (_, _) {});
      final s = c.read(cameraSessionProvider.notifier);
      await s.open();
      await s.startRecording();
      await s.stopAndClean();
      await until(() => c.read(cleanControllerProvider).phase == CleanPhase.created);
      expect(c.read(rawPathProvider('edit-1')), h.camera.lastFile);
    });
  });

  group('persistent progress bar', () {
    testWidgets('shows on Home while a cut is running and reopens it', (tester) async {
      final h = await Harness.create();
      h.backend.freezeProgress = true;
      h.backend.newEditForTest('Remove awkward pauses.');
      await pumpApp(tester, h);
      await settle(tester);

      expect(find.text('Cleaning your video'), findsOneWidget);
      await tester.tap(find.text('Cleaning your video'));
      await settle(tester);
      expect(find.text('Cleaning your recording'), findsOneWidget);
      await unmount(tester);
    });

    testWidgets('is absent when nothing is running', (tester) async {
      final h = await Harness.create();
      h.backend.assets['asset-1'] = {'id': 'asset-1', 'status': 'uploaded'};
      h.backend.newEditForTest('Remove awkward pauses.');
      h.backend.edits['edit-1']!['status'] = 'completed';
      await pumpApp(tester, h);
      await settle(tester);
      expect(find.text('Cleaning your video'), findsNothing);
      expect(find.text('Uploading your video'), findsNothing);
      await unmount(tester);
    });
  });
}
