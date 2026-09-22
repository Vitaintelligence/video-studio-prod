import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_pump.dart';
import '../support/harness.dart';

/// Design-review screenshots. They also fail on any layout overflow at these phone sizes / text scales.
/// Regenerate with: flutter test --update-goldens test/goldens
Future<void> settle(WidgetTester tester, {int steps = 8}) async {
  for (var i = 0; i < steps; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<Harness> seeded({bool frozen = false, Map<String, Object> prefs = const {}}) async {
  final h = await Harness.create(prefs: prefs);
  h.backend.assets['asset-1'] = {'id': 'asset-1', 'status': 'uploaded'};
  final e = h.backend.newEditForTest('Remove awkward pauses and dead air. Keep the pacing tight.');
  h.backend.edits[e['id'] as String]!['status'] = frozen ? 'running' : 'completed';
  h.backend.freezeProgress = frozen;
  return h;
}

Future<void> shot(WidgetTester tester, String name) =>
    expectLater(find.byType(MaterialApp), matchesGoldenFile('$name.png'));

/// Screens with a running spinner differ by a few pixels between runs; anything above 0.2% is a real change.
class _TolerantComparator extends LocalFileComparator {
  _TolerantComparator(super.testFile);

  @override
  Future<bool> compare(Uint8List imageBytes, Uri golden) async {
    final result = await GoldenFileComparator.compareLists(imageBytes, await getGoldenBytes(golden));
    return result.passed || result.diffPercent <= 0.002;
  }
}

void main() {
  setUpAll(() async {
    await loadTestFonts();
    goldenFileComparator = _TolerantComparator(
      Uri.parse('${(goldenFileComparator as LocalFileComparator).basedir}x.dart'),
    );
  });

  for (final phone in Phone.values) {
    testWidgets('home · empty · ${phone.name}', (tester) async {
      final h = await Harness.create();
      await pumpApp(tester, h, phone: phone);
      await settle(tester);
      await shot(tester, 'home_empty_${phone.name}');
      await unmount(tester);
    });
  }

  testWidgets('home · recents · compact · text x1.5', (tester) async {
    final h = await seeded(prefs: {'onboarding.persona': 'agency'});
    await pumpApp(tester, h, phone: Phone.compact, textScale: 1.5);
    await settle(tester);
    await shot(tester, 'home_recents_compact_x1_5');
    await unmount(tester);
  });

  testWidgets('camera · standard', (tester) async {
    final h = await Harness.create();
    await pumpApp(tester, h, location: '/camera');
    await settle(tester);
    await shot(tester, 'camera_standard');
    await unmount(tester);
  });

  testWidgets('onboarding · intro · standard', (tester) async {
    final h = await Harness.create(prefs: {'onboarding.done': false});
    await pumpApp(tester, h);
    await settle(tester);
    await shot(tester, 'onboarding_intro_standard');
    await unmount(tester);
  });

  testWidgets('onboarding · question · compact', (tester) async {
    final h = await Harness.create(prefs: {'onboarding.done': false});
    await pumpApp(tester, h, phone: Phone.compact);
    await settle(tester);
    await tester.tap(find.text('Show me my time savings'));
    await settle(tester);
    await shot(tester, 'onboarding_question_compact');
    await unmount(tester);
  });

  testWidgets('onboarding · estimate · standard', (tester) async {
    final h = await Harness.create(
      prefs: {
        'onboarding.done': false,
        'onboarding.persona': 'ugcCreator',
        'onboarding.niche': 'beauty',
        'onboarding.weekly_volume': 'upTo15',
        'onboarding.editing_time': 'm30to60',
      },
    );
    await pumpApp(tester, h);
    await settle(tester);
    await tester.tap(find.text('Show me my time savings'));
    await settle(tester);
    for (final answer in ['UGC creator', 'Beauty', '6–15', '30–60 min']) {
      await tester.tap(find.text(answer));
      await settle(tester, steps: 4);
    }
    await shot(tester, 'onboarding_estimate_standard');
    await unmount(tester);
  });

  testWidgets('processing · standard', (tester) async {
    final h = await seeded(frozen: true);
    await pumpApp(tester, h, location: '/edits/edit-1');
    await settle(tester);
    await shot(tester, 'processing_standard');
    await unmount(tester);
  });

  testWidgets('result · standard', (tester) async {
    final h = await seeded(prefs: {'raw_seconds.edit-1': 77.0});
    await pumpApp(tester, h, location: '/edits/edit-1');
    await settle(tester, steps: 10);
    await shot(tester, 'result_standard');
    await unmount(tester);
  });

  testWidgets('result · compact · text x1.5', (tester) async {
    final h = await seeded(prefs: {'raw_seconds.edit-1': 77.0});
    await pumpApp(tester, h, location: '/edits/edit-1', phone: Phone.compact, textScale: 1.5);
    await settle(tester, steps: 10);
    await shot(tester, 'result_compact_x1_5');
    await unmount(tester);
  });

  testWidgets('adjust · standard', (tester) async {
    final h = await seeded();
    await pumpApp(tester, h, location: '/edits/edit-1');
    await settle(tester, steps: 10);
    await tester.tap(find.text('Adjust'));
    await settle(tester);
    expect(find.text('Add captions'), findsNothing); // the backend did not report the captions capability
    await shot(tester, 'adjust_standard');
    await unmount(tester);
  });

  testWidgets('adjust: the "Add captions" suggestion only appears when the backend reports the capability', (
    tester,
  ) async {
    final h = await seeded();
    h.backend.captionsEnabled = true;
    await pumpApp(tester, h, location: '/edits/edit-1');
    await settle(tester, steps: 10);
    await tester.tap(find.text('Adjust'));
    await settle(tester);
    expect(find.text('Add captions'), findsOneWidget);
    await tester.tap(find.text('Add captions'));
    await settle(tester);
    expect(find.textContaining('Add bold captions.'), findsOneWidget); // tapping it fills the composer
    await unmount(tester);
  });

  testWidgets('projects · standard', (tester) async {
    final h = await seeded();
    await pumpApp(tester, h, location: '/projects');
    await settle(tester);
    await shot(tester, 'projects_standard');
    await unmount(tester);
  });

  testWidgets('variants · standard', (tester) async {
    final h = await seeded();
    await pumpApp(tester, h, location: '/edits/edit-1/variants');
    await settle(tester);
    await tester.tap(find.text('Create variants'));
    await settle(tester, steps: 40);
    await shot(tester, 'variants_standard');
    await unmount(tester);
  });

  testWidgets('account · standard', (tester) async {
    final h = await Harness.create(
      prefs: {
        'onboarding.persona': 'ugcCreator',
        'onboarding.weekly_volume': 'upTo15',
        'onboarding.editing_time': 'm30to60',
      },
    );
    await pumpApp(tester, h, location: '/account');
    await settle(tester);
    await shot(tester, 'account_standard');
    await unmount(tester);
  });
}
