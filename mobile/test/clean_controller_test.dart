import 'package:adcut_mobile/core/intents/edit_intent.dart';
import 'package:adcut_mobile/features/clean/clean_controller.dart';
import 'package:adcut_mobile/features/clean/footage_picker.dart';
import 'package:adcut_mobile/features/settings/ad_options.dart';
import 'package:adcut_mobile/features/settings/settings_controller.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/harness.dart';

Future<PickedFootage> clip(String name, {int bytes = 4096}) async => PickedFootage(
  path: await tempVideo(name, bytes: bytes),
  name: name,
  sizeBytes: bytes,
);

void main() {
  test('record & clean uploads the file, creates one clean job with no user prompt, and reports the job id', () async {
    final h = await Harness.create();
    final c = h.container();
    addTearDown(c.dispose);
    final progress = <double>[];
    c.listen(cleanControllerProvider, (_, s) => progress.add(s.progress));

    await c
        .read(cleanControllerProvider.notifier)
        .start(await clip('REC_1.mp4'), intent: EditIntent.recordClean, rawSeconds: 77);

    final s = c.read(cleanControllerProvider);
    expect(s.phase, CleanPhase.created);
    expect(s.editId, 'edit-1');
    expect(progress.any((p) => p > 0 && p <= 1), isTrue, reason: 'progress comes from bytes sent');
    expect(h.backend.uploadAuthHeaders, ['']);
    final body = h.backend.editBodies.single;
    expect(body['instruction'], EditIntent.recordClean.cleanInstruction);
    expect(body['platform'], 'tiktok');
    expect(body['aspect_ratio'], '9:16');
    expect(body.containsKey('duration_target_seconds'), isFalse);
    expect(c.read(rawSecondsProvider('edit-1')), 77, reason: 'raw length is stored for time saved');
  });

  test('account defaults (platform, format) feed the request', () async {
    final h = await Harness.create();
    final c = h.container();
    addTearDown(c.dispose);
    c.read(settingsProvider.notifier)
      ..setPlatform(AdPlatform.reels)
      ..setFormat(AdFormat.square);
    await c.read(cleanControllerProvider.notifier).start(await clip('a.mp4'), intent: EditIntent.uploadClean);
    expect(h.backend.editBodies.single['platform'], 'reels');
    expect(h.backend.editBodies.single['aspect_ratio'], '1:1');
    expect(c.read(rawSecondsProvider('edit-1')), isNull, reason: 'unknown raw length is never invented');
  });

  test('unsupported, empty and oversized files fail before any network call', () async {
    final h = await Harness.create();
    final c = h.container();
    addTearDown(c.dispose);
    final n = c.read(cleanControllerProvider.notifier);
    for (final bad in [
      PickedFootage(path: await tempVideo('a.pdf'), name: 'a.pdf', sizeBytes: 10),
      PickedFootage(path: await tempVideo('a.mp4'), name: 'a.mp4', sizeBytes: 0),
      PickedFootage(path: await tempVideo('a.mp4'), name: 'a.mp4', sizeBytes: 600 * 1024 * 1024),
    ]) {
      await n.start(bad, intent: EditIntent.uploadClean);
      expect(c.read(cleanControllerProvider).phase, CleanPhase.failed);
      expect(c.read(cleanControllerProvider).error!.code, 'INVALID_MEDIA');
      n.reset();
    }
    expect(h.backend.requests, isEmpty);
  });

  test('a failed upload can be retried', () async {
    final h = await Harness.create();
    final c = h.container();
    addTearDown(c.dispose);
    final n = c.read(cleanControllerProvider.notifier);
    h.backend.failNextStorage = true;
    await n.start(await clip('a.mp4'), intent: EditIntent.uploadClean);
    expect(c.read(cleanControllerProvider).phase, CleanPhase.failed);

    h.backend.failNextStorage = false;
    await n.retry();
    expect(c.read(cleanControllerProvider).phase, CleanPhase.created);
    expect(h.backend.editCreations, 1);
  });

  test('double start creates one job', () async {
    final h = await Harness.create();
    final c = h.container();
    addTearDown(c.dispose);
    final n = c.read(cleanControllerProvider.notifier);
    final f = await clip('a.mp4');
    await Future.wait([n.start(f, intent: EditIntent.uploadClean), n.start(f, intent: EditIntent.uploadClean)]);
    expect(h.backend.editCreations, 1);
  });

  test('a lost response then retry reuses the idempotency key: still one job', () async {
    final h = await Harness.create();
    final c = h.container();
    addTearDown(c.dispose);
    final n = c.read(cleanControllerProvider.notifier);
    h.backend.dropNextEditResponse = true;
    await n.start(await clip('a.mp4'), intent: EditIntent.uploadClean);
    expect(c.read(cleanControllerProvider).phase, CleanPhase.failed);
    expect(c.read(cleanControllerProvider).error!.isNetwork, isTrue);

    await n.retry();
    expect(c.read(cleanControllerProvider).editId, 'edit-1');
    expect(h.backend.editCreations, 1);
  });
}
