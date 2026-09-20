import 'package:adcut_mobile/core/intents/edit_intent.dart';
import 'package:adcut_mobile/features/onboarding/onboarding_controller.dart';
import 'package:adcut_mobile/features/onboarding/onboarding_model.dart';
import 'package:adcut_mobile/features/settings/ad_options.dart';
import 'package:adcut_mobile/features/settings/settings_controller.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/harness.dart';

void main() {
  test('time estimate is deterministic from the answers', () {
    // 10 videos/week x 45 min x 52/12 weeks / 60 = 32.5 h
    final e = TimeEstimate.from(WeeklyVolume.upTo15, EditingTime.m30to60);
    expect(e.hoursPerMonth, closeTo(32.5, 0.01));
    expect(e.roundedHours, 33);
    expect(e.workingDays, closeTo(4.06, 0.01));

    final small = TimeEstimate.from(WeeklyVolume.upTo5, EditingTime.under15);
    expect(small.hoursPerMonth, closeTo(2.17, 0.01));
    expect(TimeEstimate.from(WeeklyVolume.over30, EditingTime.over2h).roundedHours, 433);
  });

  test('persona reorders Home intents without changing the set', () {
    expect(intentOrderFor(Persona.ugcCreator).first, EditIntent.recordClean);
    expect(intentOrderFor(null).first, EditIntent.recordClean);
    expect(intentOrderFor(Persona.tiktokShopSeller).take(2), [EditIntent.recordClean, EditIntent.adVariants]);
    expect(intentOrderFor(Persona.agency).first, EditIntent.uploadClean);
    for (final p in Persona.values) {
      expect(intentOrderFor(p).toSet(), intentOrderFor(null).toSet());
    }
  });

  test('answers persist and are restored; only the four answers plus a done flag are stored', () async {
    final h = await Harness.create(prefs: {'onboarding.done': false});
    final first = h.container();
    first.read(onboardingProvider.notifier)
      ..setPersona(Persona.agency)
      ..setNiche(Niche.beauty)
      ..setVolume(WeeklyVolume.upTo30)
      ..setTime(EditingTime.h1to2)
      ..complete();
    await Future<void>.delayed(Duration.zero);
    first.dispose();

    final second = h.container();
    addTearDown(second.dispose);
    final s = second.read(onboardingProvider);
    expect(s.persona, Persona.agency);
    expect(s.niche, Niche.beauty);
    expect(s.volume, WeeklyVolume.upTo30);
    expect(s.time, EditingTime.h1to2);
    expect(s.completed, isTrue);
    expect(s.estimate!.roundedHours, 150);
    expect(h.prefs.getKeys().where((k) => k.startsWith('onboarding.')), hasLength(5));
  });

  test('default platform and format persist', () async {
    final h = await Harness.create();
    final a = h.container();
    a.read(settingsProvider.notifier)
      ..setPlatform(AdPlatform.shorts)
      ..setFormat(AdFormat.landscape);
    await Future<void>.delayed(Duration.zero);
    a.dispose();
    final b = h.container();
    addTearDown(b.dispose);
    expect(b.read(settingsProvider).platform, AdPlatform.shorts);
    expect(b.read(settingsProvider).format, AdFormat.landscape);
  });
}
