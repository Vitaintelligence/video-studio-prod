/// What the user is trying to do. Widgets speak in intents; only this layer knows how the backend
/// is asked to fulfil one (no pipeline names, provider models or engine terms leak into the UI).
enum EditIntent {
  recordClean,
  uploadClean,
  adVariants,
  videoToClips,
  promptRevision;

  /// Instruction sent to the backend edit planner for the intents that create a new edit.
  /// The planner removes dead air and silence and tightens pacing from these words.
  String? get cleanInstruction => switch (this) {
    EditIntent.recordClean || EditIntent.uploadClean => 'Remove awkward pauses and dead air. Keep the pacing tight.',
    _ => null,
  };
}
