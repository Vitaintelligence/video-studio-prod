import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';
import 'onboarding_model.dart';

class OnboardingState {
  const OnboardingState({this.persona, this.niche, this.volume, this.time, this.completed = false});

  final Persona? persona;
  final Niche? niche;
  final WeeklyVolume? volume;
  final EditingTime? time;
  final bool completed;

  TimeEstimate? get estimate => volume != null && time != null ? TimeEstimate.from(volume!, time!) : null;

  OnboardingState copyWith({
    Persona? persona,
    Niche? niche,
    WeeklyVolume? volume,
    EditingTime? time,
    bool? completed,
  }) => OnboardingState(
    persona: persona ?? this.persona,
    niche: niche ?? this.niche,
    volume: volume ?? this.volume,
    time: time ?? this.time,
    completed: completed ?? this.completed,
  );
}

const onboardingDoneKey = 'onboarding.done';
const _personaKey = 'onboarding.persona';
const _nicheKey = 'onboarding.niche';
const _volumeKey = 'onboarding.weekly_volume';
const _timeKey = 'onboarding.editing_time';

T? _byName<T extends Enum>(List<T> values, String? name) {
  for (final v in values) {
    if (v.name == name) return v;
  }
  return null;
}

/// Persists only the four answers that personalise the app; nothing else is collected.
class OnboardingController extends Notifier<OnboardingState> {
  @override
  OnboardingState build() {
    final prefs = ref.watch(preferencesProvider);
    return OnboardingState(
      persona: _byName(Persona.values, prefs.getString(_personaKey)),
      niche: _byName(Niche.values, prefs.getString(_nicheKey)),
      volume: _byName(WeeklyVolume.values, prefs.getString(_volumeKey)),
      time: _byName(EditingTime.values, prefs.getString(_timeKey)),
      completed: prefs.getBool(onboardingDoneKey) ?? false,
    );
  }

  void _save(String key, Enum value) => unawaited(ref.read(preferencesProvider).setString(key, value.name));

  void setPersona(Persona v) {
    state = state.copyWith(persona: v);
    _save(_personaKey, v);
  }

  void setNiche(Niche v) {
    state = state.copyWith(niche: v);
    _save(_nicheKey, v);
  }

  void setVolume(WeeklyVolume v) {
    state = state.copyWith(volume: v);
    _save(_volumeKey, v);
  }

  void setTime(EditingTime v) {
    state = state.copyWith(time: v);
    _save(_timeKey, v);
  }

  void complete() {
    state = state.copyWith(completed: true);
    unawaited(ref.read(preferencesProvider).setBool(onboardingDoneKey, true));
  }
}

final onboardingProvider = NotifierProvider<OnboardingController, OnboardingState>(OnboardingController.new);
