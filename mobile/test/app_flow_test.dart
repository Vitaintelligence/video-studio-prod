import 'package:adcut_mobile/features/clean/footage_picker.dart';
import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/app_pump.dart';
import 'support/fake_backend.dart';
import 'support/harness.dart';

/// Advances fake time in small steps so polling, navigation and animations all run.
Future<void> settle(WidgetTester tester, {int steps = 20}) async {
  for (var i = 0; i < steps; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

/// A backend that already holds one finished 17-second cut.
Future<Harness> harnessWithCompletedEdit({
  Map<String, Object> prefs = const {},
  void Function(FakeBackend)? configure,
}) async {
  final h = await Harness.create(prefs: prefs);
  h.backend.assets['asset-1'] = {'id': 'asset-1', 'status': 'uploaded'};
  final id = h.backend.newEditForTest('Remove awkward pauses and dead air.')['id'] as String;
  h.backend.edits[id]!['status'] = 'completed';
  configure?.call(h.backend);
  return h;
}

Finder semantic(String label) => find.bySemanticsLabel(label);

void main() {
  setUpAll(loadTestFonts);

  group('Home', () {
    testWidgets('is intent-first: no prompt box, primary Record & Clean, only supported extras', (tester) async {
      final h = await Harness.create();
      await pumpApp(tester, h);
      await settle(tester, steps: 3);

      expect(find.text('What are you making today?'), findsOneWidget);
      expect(find.text('Record & Clean'), findsOneWidget);
      expect(find.text('Upload & Clean'), findsOneWidget);
      expect(find.text('Do more'), findsOneWidget);
      expect(find.text('Make Ad Variants'), findsOneWidget);
      expect(find.text('Video to Clips'), findsNothing, reason: 'the backend has no clip extraction, so it is hidden');
      expect(find.byType(TextField), findsNothing, reason: 'no giant prompt on Home');
      expect(find.text('Your finished cuts will show up here.'), findsOneWidget);
      await unmount(tester);
    });

    testWidgets('variants are hidden when unsupported; an editing outage is explicit', (tester) async {
      final h = await Harness.create();
      h.backend.variantsEnabled = false;
      await pumpApp(tester, h);
      await settle(tester, steps: 3);
      expect(find.text('Make Ad Variants'), findsNothing);
      await unmount(tester);

      final down = await Harness.create();
      down.backend.editingEnabled = false;
      await pumpApp(tester, down);
      await settle(tester, steps: 3);
      expect(find.text('Editing is unavailable right now. Please try again shortly.'), findsOneWidget);
      expect(find.text('Record & Clean'), findsNothing);
      await unmount(tester);
    });

    testWidgets('persona reorders the intents', (tester) async {
      final h = await Harness.create(prefs: {'onboarding.persona': 'agency'});
      await pumpApp(tester, h);
      await settle(tester, steps: 3);
      final upload = tester.getTopLeft(find.text('Upload & Clean')).dy;
      final record = tester.getTopLeft(find.text('Record & Clean')).dy;
      expect(upload, lessThan(record));
      await unmount(tester);
    });

    testWidgets('navigation is Home, Record, Projects and every item works', (tester) async {
      final h = await Harness.create();
      await pumpApp(tester, h);
      await settle(tester, steps: 3);
      expect(semantic('Home'), findsOneWidget);
      expect(semantic('Record'), findsOneWidget);
      expect(semantic('Projects'), findsOneWidget);

      await tester.tap(semantic('Projects'));
      await settle(tester, steps: 3);
      expect(find.text('No projects yet'), findsOneWidget);

      await tester.tap(semantic('Record'));
      await settle(tester, steps: 5);
      expect(semantic('Start recording'), findsOneWidget);
      expect(h.camera.openCount, 1);
      await unmount(tester);
    });

    testWidgets('account opens from the avatar and defaults persist', (tester) async {
      final h = await Harness.create();
      await pumpApp(tester, h);
      await settle(tester, steps: 2);
      await tester.tap(find.byIcon(CupertinoIcons.person_crop_circle));
      await settle(tester, steps: 5);
      expect(find.text('Default platform'), findsOneWidget);
      await tester.tap(find.text('TikTok'));
      await settle(tester, steps: 5);
      await tester.tap(find.text('Meta'));
      await settle(tester, steps: 5);
      expect(h.prefs.getString('settings.platform'), 'meta');
      await unmount(tester);
    });
  });

  group('Onboarding', () {
    testWidgets('first launch: four questions, a real estimate, then the first recording', (tester) async {
      final h = await Harness.create(prefs: {'onboarding.done': false});
      await pumpApp(tester, h);
      await settle(tester, steps: 3);

      expect(find.text('What best describes you?'), findsOneWidget);
      await tester.tap(find.text('UGC creator'));
      await settle(tester, steps: 5);
      expect(find.text('What do you create?'), findsOneWidget);
      await tester.tap(find.text('Beauty'));
      await settle(tester, steps: 5);
      await tester.tap(find.text('6–15'));
      await settle(tester, steps: 5);
      await tester.tap(find.text('30–60 min'));
      await settle(tester, steps: 5);

      expect(find.text('You spend about 33 hours each month editing.'), findsOneWidget);
      expect(find.textContaining('about 4.1 working days'), findsOneWidget);
      await tester.tap(find.text('Claim your time'));
      await settle(tester, steps: 5);
      await tester.tap(find.text('Start first recording'));
      await settle(tester, steps: 8);

      expect(semantic('Start recording'), findsOneWidget);
      expect(h.prefs.getBool('onboarding.done'), isTrue);
      expect(h.prefs.getString('onboarding.persona'), 'ugcCreator');
      await unmount(tester);
    });
  });

  group('Record & Clean', () {
    testWidgets('record, stop, upload, cleaning, result: no questions in between', (tester) async {
      final h = await Harness.create();
      await pumpApp(tester, h, location: '/camera');
      await settle(tester, steps: 3);

      await tester.tap(semantic('Start recording'));
      await settle(tester, steps: 3);
      expect(semantic('Stop recording'), findsOneWidget);
      await tester.tap(semantic('Stop recording'));
      await tester.pump();
      await pumpUntil(tester, () => h.backend.editCreations == 1);
      await settle(tester, steps: 3);

      expect(h.backend.editBodies.single['instruction'], contains('pauses'));
      expect(find.textContaining('%'), findsNothing, reason: 'no invented percentages');
      await settle(tester, steps: 40);
      expect(find.text('Your cut is ready'), findsOneWidget);
      expect(find.text('0:17'), findsOneWidget);
      await unmount(tester);
    });

    testWidgets('a camera that opens shows Ready and the record control', (tester) async {
      final h = await Harness.create();
      await pumpApp(tester, h, location: '/camera');
      await settle(tester, steps: 3);
      expect(find.text('Ready'), findsOneWidget);
      expect(semantic('Start recording'), findsOneWidget);
      await unmount(tester);
    });

    testWidgets('progress shows backend stages as a checklist', (tester) async {
      final h = await Harness.create();
      h.backend.freezeProgress = true;
      h.backend.newEditForTest('Remove awkward pauses and dead air.');
      await pumpApp(tester, h, location: '/edits/edit-1');
      await settle(tester, steps: 4);

      expect(find.text('Cleaning your recording'), findsOneWidget);
      expect(semantic('Understanding footage, done'), findsOneWidget);
      expect(semantic('Finding strongest moments, done'), findsOneWidget);
      expect(semantic('Building your edit, in progress'), findsOneWidget);
      expect(semantic('Finalizing, waiting'), findsOneWidget);
      expect(find.text('You can leave. We will keep working.'), findsOneWidget);
      expect(find.textContaining('%'), findsNothing);
      await unmount(tester);
    });

    testWidgets('Cancel asks once, then really cancels', (tester) async {
      final h = await Harness.create();
      h.backend.stepsToComplete = 1000;
      h.backend.newEditForTest('Remove awkward pauses.');
      await pumpApp(tester, h, location: '/edits/edit-1');
      await settle(tester, steps: 3);

      await tester.tap(find.text('Cancel'));
      await settle(tester, steps: 5);
      expect(find.text('Cancel this cut?'), findsOneWidget);
      await tester.tap(find.text('Keep going'));
      await settle(tester, steps: 8);
      expect(h.backend.edits['edit-1']!['status'], isNot('cancelled'));

      await tester.tap(find.text('Cancel'));
      await settle(tester, steps: 5);
      await tester.tap(find.descendant(of: find.byType(CupertinoAlertDialog), matching: find.text('Cancel cut')));
      await settle(tester, steps: 5);
      expect(h.backend.edits['edit-1']!['status'], 'cancelled');
      expect(find.text('Cut cancelled'), findsOneWidget);
      await unmount(tester);
    });

    testWidgets('a failed cut is explained in plain language with a way forward', (tester) async {
      final h = await Harness.create();
      final id = h.backend.newEditForTest('Remove awkward pauses.')['id'] as String;
      h.backend.edits[id]!['status'] = 'failed';
      h.backend.edits[id]!['error'] = {'code': 'GENERATION_FAILED', 'message': "We couldn't finish this video."};
      await pumpApp(tester, h, location: '/edits/edit-1');
      await settle(tester, steps: 3);
      expect(find.text("We couldn't finish this cut"), findsOneWidget);
      expect(find.text('Record again'), findsOneWidget);
      await unmount(tester);
    });
  });

  group('Upload & Clean', () {
    testWidgets('Photos, upload, result: without asking for a prompt', (tester) async {
      final h = await Harness.create();
      final path = await tester.runAsync(() => tempVideo('lib_clip.mov', bytes: 120000));
      h.picker.next = PickedFootage(path: path!, name: 'lib_clip.mov', sizeBytes: 120000);
      h.picker.seconds = 77;
      await pumpApp(tester, h);
      await settle(tester, steps: 3);

      await tester.tap(find.text('Upload & Clean'));
      await settle(tester, steps: 5);
      await tester.tap(find.text('Photos'));
      await tester.pump();
      await pumpUntil(tester, () => h.backend.editCreations == 1);
      await settle(tester, steps: 60);

      expect(find.text('Your cut is ready'), findsOneWidget);
      expect(find.text('1:17'), findsOneWidget, reason: 'raw length comes from the picked file');
      expect(find.text('0:17'), findsOneWidget);
      expect(find.text('1m saved'), findsOneWidget);
      await unmount(tester);
    });
  });

  group('Result and Adjust', () {
    testWidgets('payoff: raw to ready, time saved from real data, one primary action', (tester) async {
      final h = await harnessWithCompletedEdit(prefs: {'raw_seconds.edit-1': 77.0});
      await pumpApp(tester, h, location: '/edits/edit-1');
      await settle(tester, steps: 4);

      expect(find.text('Your cut is ready'), findsOneWidget);
      expect(find.text('1:17'), findsOneWidget);
      expect(find.text('0:17'), findsOneWidget);
      expect(find.text('1m saved'), findsOneWidget);
      expect(find.text('Use this cut'), findsOneWidget);
      expect(find.text('Adjust'), findsOneWidget);
      expect(find.text('Create variants'), findsOneWidget);
      await tester.tap(find.text('Use this cut'));
      await settle(tester, steps: 3);
      expect(h.exporter.exported, [FakeBackend.outputUrl]);
      await unmount(tester);
    });

    testWidgets('time saved is never invented when the raw length is unknown', (tester) async {
      final h = await harnessWithCompletedEdit();
      await pumpApp(tester, h, location: '/edits/edit-1');
      await settle(tester, steps: 4);
      expect(find.text('0:17'), findsOneWidget);
      expect(find.textContaining('saved'), findsNothing);
      await unmount(tester);
    });

    testWidgets('Adjust introduces Prompt-to-Edit: Version 2 is created and Version 1 stays selectable', (
      tester,
    ) async {
      final h = await harnessWithCompletedEdit();
      await pumpApp(tester, h, location: '/edits/edit-1');
      await settle(tester, steps: 4);
      expect(find.text('Ask AI to change anything'), findsNothing, reason: 'the prompt only appears after Adjust');
      await tester.tap(find.text('Adjust'));
      await settle(tester, steps: 4);

      expect(find.text('Ask AI to change anything'), findsOneWidget);
      await tester.tap(find.text('Shorter'));
      await tester.pump();
      expect(tester.widget<TextField>(find.byType(TextField)).controller!.text, 'Make it shorter and tighter.');
      await tester.enterText(find.byType(TextField), 'Make the opening tighter and remove more pauses.');
      await tester.pump();
      await tester.tap(find.text('Update'));
      await tester.pump();
      await tester.tap(find.text('Update'), warnIfMissed: false);
      await settle(tester, steps: 40);

      expect(h.backend.instructionBodies, hasLength(1));
      expect(h.backend.instructionBodies.single['instruction'], 'Make the opening tighter and remove more pauses.');
      expect(find.text('Version 2 · latest'), findsOneWidget);
      await unmount(tester);
    });

    testWidgets('capability gating: revisions and variants controls disappear when unsupported', (tester) async {
      final h = await harnessWithCompletedEdit(
        configure: (b) {
          b.variantsEnabled = false;
          b.revisionsEnabled = false;
        },
      );
      await pumpApp(tester, h, location: '/edits/edit-1');
      await settle(tester, steps: 4);
      expect(find.text('Use this cut'), findsOneWidget);
      expect(find.text('Adjust'), findsNothing);
      expect(find.text('Create variants'), findsNothing);
      await unmount(tester);
    });

    testWidgets('B-roll suggestion appears only when the backend supports it', (tester) async {
      final withBroll = await harnessWithCompletedEdit(configure: (b) => b.brollEnabled = true);
      await pumpApp(tester, withBroll, location: '/edits/edit-1');
      await settle(tester, steps: 4);
      await tester.tap(find.text('Adjust'));
      await settle(tester, steps: 4);
      expect(find.text('Add B-roll'), findsOneWidget);
      await unmount(tester);

      final without = await harnessWithCompletedEdit();
      await pumpApp(tester, without, location: '/edits/edit-1');
      await settle(tester, steps: 4);
      await tester.tap(find.text('Adjust'));
      await settle(tester, steps: 4);
      expect(find.text('Add B-roll'), findsNothing);
      await unmount(tester);
    });
  });

  group('Variants', () {
    testWidgets('choose 3 or 5, create real hook variants, then preview/export', (tester) async {
      final h = await harnessWithCompletedEdit();
      await pumpApp(tester, h, location: '/edits/edit-1/variants');
      await settle(tester, steps: 4);

      expect(find.text('What do you want to test?'), findsOneWidget);
      await tester.tap(find.text('5 variants'));
      await tester.pump();
      await tester.tap(find.text('Create variants'));
      await settle(tester, steps: 60);
      expect(find.text('Problem Hook'), findsOneWidget);
      expect(find.text('Preview'), findsAtLeastNWidgets(3), reason: 'list is lazy; the rest scroll into view');
      expect(find.textContaining('%'), findsNothing, reason: 'no fabricated scores');
      await unmount(tester);
    });
  });

  group('Projects', () {
    testWidgets('groups real projects by state and opens them', (tester) async {
      final h = await harnessWithCompletedEdit();
      await pumpApp(tester, h, location: '/projects');
      await settle(tester, steps: 4);
      expect(find.text('Ready'), findsWidgets);
      expect(find.text('UGC Test'), findsOneWidget);
      await tester.tap(find.text('UGC Test'));
      await settle(tester, steps: 5);
      expect(find.text('Your cut is ready'), findsOneWidget);
      await unmount(tester);
    });

    testWidgets('empty state routes to Home', (tester) async {
      final h = await Harness.create();
      await pumpApp(tester, h, location: '/projects');
      await settle(tester, steps: 3);
      expect(find.text('No projects yet'), findsOneWidget);
      await tester.tap(find.text('Create an edit'));
      await settle(tester, steps: 4);
      expect(find.text('What are you making today?'), findsOneWidget);
      await unmount(tester);
    });

    testWidgets('a load failure is retryable and never shows raw server text', (tester) async {
      final h = await Harness.create();
      h.backend.failProjects = true;
      await pumpApp(tester, h, location: '/projects');
      await settle(tester, steps: 3);
      expect(find.text("Couldn't load projects"), findsOneWidget);
      expect(find.textContaining('503'), findsNothing);
      h.backend.failProjects = false;
      await tester.tap(find.text('Try again'));
      await settle(tester, steps: 3);
      expect(find.text("Couldn't load projects"), findsNothing);
      await unmount(tester);
    });
  });
}
