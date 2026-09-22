import 'dart:io';

import 'package:adcut_mobile/features/camera/camera_controller.dart';
import 'package:adcut_mobile/features/clean/clean_controller.dart';
import 'package:adcut_mobile/core/models/api_models.dart';
import 'package:adcut_mobile/features/edit/cut_timeline.dart';
import 'package:flutter/cupertino.dart';
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
    test('result claims are limited to explicit truthy insights', () {
      final job = EditJob.fromJson({
        'id': 'edit-1',
        'status': 'completed',
        'insights': {'retakes_removed': 2, 'off_script_removed': 1, 'unrelated_internal_metric': 99},
      });
      expect(verifiedEditChanges(job.insights).map((change) => change.label), [
        '2 retakes removed',
        '1 off-script moment removed',
      ]);
      expect(verifiedEditChanges({'retakes_removed': 0, 'off_script_removed': false}), isEmpty);
      expect(
        verifiedEditChanges({'captions_requested': true}),
        isEmpty,
        reason: 'a request is not proof that captions were added',
      );
    });

    test('cut timeline derives the real removed gaps from kept source ranges', () {
      final slices = buildCutSlices(20, const [
        CutRange(source: 0, start: 2, end: 7),
        CutRange(source: 0, start: 10, end: 18),
      ]);
      expect(slices.map((slice) => slice.kept), [false, true, false, true, false]);
      expect(slices.where((slice) => !slice.kept).map((slice) => slice.range.duration), [2, 3, 2]);
    });

    testWidgets('a removed range can be reviewed and restored as a new version', (tester) async {
      final h = await Harness.create(prefs: {'raw_seconds.edit-1': 30.0});
      h.backend.assets['asset-1'] = {'id': 'asset-1', 'status': 'uploaded'};
      h.backend.newEditForTest('Remove awkward pauses.');
      h.backend.edits['edit-1']!['status'] = 'completed';
      await pumpApp(tester, h, location: '/edits/edit-1');
      await settle(tester);

      expect(find.text('What AdCut changed'), findsOneWidget);
      final removedClip = find.bySemanticsLabel(RegExp('Preview removed clip')).first;
      await tester.ensureVisible(removedClip);
      await tester.drag(find.byType(ListView).first, const Offset(0, -240));
      await tester.pumpAndSettle();
      await tester.tap(removedClip);
      await settle(tester, steps: 3);
      expect(find.text('Restore this clip'), findsOneWidget);
      await tester.ensureVisible(find.text('Restore this clip'));
      await tester.drag(find.byType(ListView).first, const Offset(0, -320));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Restore this clip'));
      await settle(tester, steps: 8);

      expect(h.backend.restoreBodies, hasLength(1));
      expect(h.backend.restoreBodies.single['source'], 0);
      await unmount(tester);
    });

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
