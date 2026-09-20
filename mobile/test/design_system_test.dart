import 'dart:ui' show Tristate;
import 'package:adcut_mobile/core/design/app_theme.dart';
import 'package:adcut_mobile/core/widgets/app_selector.dart';
import 'package:adcut_mobile/core/widgets/buttons.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

Widget host(Widget child) => MaterialApp(
  theme: AppTheme.dark,
  home: Scaffold(body: Center(child: child)),
);

void main() {
  group('buttons', () {
    testWidgets('primary button fires once per tap and not while loading or disabled', (tester) async {
      var taps = 0;
      await tester.pumpWidget(host(PrimaryButton(label: 'Edit with AI', onPressed: () => taps++)));
      await tester.tap(find.text('Edit with AI'));
      expect(taps, 1);

      await tester.pumpWidget(host(PrimaryButton(label: 'Edit with AI', onPressed: () => taps++, isLoading: true)));
      await tester.tap(find.byType(PrimaryButton));
      expect(taps, 1, reason: 'loading blocks taps (no double submit)');

      await tester.pumpWidget(host(const PrimaryButton(label: 'Edit with AI', onPressed: null)));
      await tester.tap(find.byType(PrimaryButton));
      expect(taps, 1);
    });

    testWidgets('loading keeps the button size and hides no accessibility label', (tester) async {
      await tester.pumpWidget(host(PrimaryButton(label: 'Edit with AI', onPressed: () {})));
      final idle = tester.getSize(find.byType(PrimaryButton));
      await tester.pumpWidget(host(PrimaryButton(label: 'Edit with AI', onPressed: () {}, isLoading: true)));
      expect(tester.getSize(find.byType(PrimaryButton)), idle);
      expect(find.bySemanticsLabel('Edit with AI, in progress'), findsOneWidget);
    });

    testWidgets('every button kind has a tap target of at least 44pt', (tester) async {
      await tester.pumpWidget(
        host(
          Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              PrimaryButton(label: 'P', onPressed: () {}, expand: false),
              SecondaryButton(label: 'S', onPressed: () {}, expand: false),
              DangerButton(label: 'D', onPressed: () {}, expand: false),
              TertiaryButton(label: 'T', onPressed: () {}),
              AppIconButton(icon: Icons.close, label: 'Close', onPressed: () {}),
            ],
          ),
        ),
      );
      for (final type in [PrimaryButton, SecondaryButton, DangerButton, TertiaryButton, AppIconButton]) {
        final size = tester.getSize(find.byType(type));
        expect(size.height, greaterThanOrEqualTo(44), reason: '$type height');
        expect(size.width, greaterThanOrEqualTo(44), reason: '$type width');
      }
    });
  });

  group('selectors', () {
    testWidgets('AppSelector shows the current value, opens a sheet, marks the selection, and reports the pick', (
      tester,
    ) async {
      String? picked;
      await tester.pumpWidget(
        host(
          AppSelector<String>(
            label: 'Platform',
            value: 'tiktok',
            choices: const [
              Choice(value: 'tiktok', label: 'TikTok'),
              Choice(value: 'reels', label: 'Instagram Reels'),
            ],
            onChanged: (v) => picked = v,
          ),
        ),
      );
      expect(find.text('TikTok'), findsOneWidget);

      await tester.tap(find.byType(AppSelector<String>));
      await tester.pumpAndSettle();
      expect(find.text('Instagram Reels'), findsOneWidget);

      await tester.tap(find.text('Instagram Reels'));
      await tester.pumpAndSettle();
      expect(picked, 'reels');
      expect(find.text('Instagram Reels'), findsNothing, reason: 'sheet closes after a pick');
    });

    testWidgets('choosing the already selected option does not fire onChanged', (tester) async {
      var calls = 0;
      await tester.pumpWidget(
        host(
          AppSelector<int?>(
            label: 'Length',
            value: null,
            choices: const [
              Choice(value: null, label: 'Auto'),
              Choice(value: 15, label: '15 sec'),
            ],
            onChanged: (_) => calls++,
          ),
        ),
      );
      await tester.tap(find.byType(AppSelector<int?>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Auto').last);
      await tester.pumpAndSettle();
      expect(calls, 0);
    });

    testWidgets('SegmentedChoice selects segments and exposes selected state to accessibility', (tester) async {
      var value = '9:16';
      await tester.pumpWidget(
        host(
          StatefulBuilder(
            builder: (context, setState) => SegmentedChoice<String>(
              label: 'Format',
              value: value,
              choices: const [
                Choice(value: '9:16', label: '9:16'),
                Choice(value: '1:1', label: '1:1'),
                Choice(value: '16:9', label: '16:9'),
              ],
              onChanged: (v) => setState(() => value = v),
            ),
          ),
        ),
      );
      await tester.tap(find.text('1:1'));
      await tester.pump();
      expect(value, '1:1');
      expect(tester.getSemantics(find.text('1:1')).getSemanticsData().flagsCollection.isSelected, Tristate.isTrue);
      expect(tester.getSemantics(find.text('9:16')).getSemanticsData().flagsCollection.isSelected, Tristate.isFalse);
    });
  });
}
