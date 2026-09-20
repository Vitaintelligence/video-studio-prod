/// What the user is trying to do. Widgets speak in intents; only this layer knows how the backend
/// is asked to fulfil one (no pipeline names, provider models or engine terms leak into the UI).
enum EditIntent {
  recordClean,
  uploadClean,
  adVariants,
  videoToClips,
  promptRevision;

  /// Instruction sent to the backend edit planner for the intents that create a new edit.
  /// The planner reads these words as: keep the best take of every repeated line, drop mistakes and
  /// off-script talk, and remove dead air. It deliberately does not ask for a speed-up or a target length.
  String? get cleanInstruction => switch (this) {
    EditIntent.recordClean || EditIntent.uploadClean =>
      'Clean this up. Remove retakes and mistakes, keep only the best take of each line, and remove dead air and awkward pauses.',
    _ => null,
  };
}
