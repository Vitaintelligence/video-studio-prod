import '../../core/intents/edit_intent.dart';

enum Persona {
  tiktokShopSeller('TikTok Shop seller'),
  shopAffiliate('Shop affiliate'),
  ugcCreator('UGC creator'),
  brandTeam('Brand / ecommerce team'),
  performanceMarketer('Performance marketer'),
  agency('Agency'),
  other('Other');

  const Persona(this.label);
  final String label;
}

enum Niche {
  beauty('Beauty'),
  fashion('Fashion'),
  supplements('Supplements'),
  home('Home'),
  food('Food & beverage'),
  technology('Technology'),
  apps('Apps / software'),
  other('Other');

  const Niche(this.label);
  final String label;
}

/// Videos made per week. `typical` is the deterministic midpoint used for the estimate.
enum WeeklyVolume {
  upTo5('1–5', 3),
  upTo15('6–15', 10),
  upTo30('16–30', 23),
  over30('30+', 40);

  const WeeklyVolume(this.label, this.typical);
  final String label;
  final int typical;
}

/// Editing time for one video. `minutes` is the deterministic midpoint used for the estimate.
enum EditingTime {
  under15('Under 15 min', 10),
  m15to30('15–30 min', 22.5),
  m30to60('30–60 min', 45),
  h1to2('1–2 hours', 90),
  over2h('2+ hours', 150);

  const EditingTime(this.label, this.minutes);
  final String label;
  final double minutes;
}

/// Transparent estimate of monthly editing time, computed only from the user's own answers.
class TimeEstimate {
  const TimeEstimate({required this.hoursPerMonth});

  factory TimeEstimate.from(WeeklyVolume volume, EditingTime time) {
    // volume x minutes x 52 weeks / 12 months / 60 minutes, ordered to stay exact for whole-minute inputs.
    return TimeEstimate(hoursPerMonth: volume.typical * time.minutes * 52 / (12 * 60));
  }

  static const double workdayHours = 8;

  final double hoursPerMonth;

  int get roundedHours => hoursPerMonth.round();
  double get workingDays => hoursPerMonth / workdayHours;
}

/// The intents shown on Home, in the order that fits this persona.
List<EditIntent> intentOrderFor(Persona? persona) => switch (persona) {
  Persona.agency => [EditIntent.uploadClean, EditIntent.adVariants, EditIntent.videoToClips, EditIntent.recordClean],
  Persona.tiktokShopSeller || Persona.shopAffiliate => [
    EditIntent.recordClean,
    EditIntent.adVariants,
    EditIntent.uploadClean,
    EditIntent.videoToClips,
  ],
  Persona.performanceMarketer ||
  Persona.brandTeam => [EditIntent.uploadClean, EditIntent.adVariants, EditIntent.recordClean, EditIntent.videoToClips],
  _ => [EditIntent.recordClean, EditIntent.uploadClean, EditIntent.adVariants, EditIntent.videoToClips],
};
