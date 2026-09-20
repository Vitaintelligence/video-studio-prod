import 'package:adcut_mobile/core/format.dart';
import 'package:adcut_mobile/features/camera/camera_controller.dart';
import 'package:adcut_mobile/features/camera/camera_gateway.dart';
import 'package:adcut_mobile/features/clean/clean_controller.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/harness.dart';

void main() {
  test('opens, records, stops, and starts a real clean of the recorded file', () async {
    final h = await Harness.create();
    final c = h.container();
    addTearDown(c.dispose);
    c.listen(cameraSessionProvider, (_, _) {});
    final session = c.read(cameraSessionProvider.notifier);

    await session.open();
    expect(c.read(cameraSessionProvider).phase, CameraPhase.ready);
    await session.startRecording();
    expect(c.read(cameraSessionProvider).isRecording, isTrue);
    await Future<void>.delayed(const Duration(milliseconds: 300));
    expect(await session.stopAndClean(), isTrue);

    await until(() => c.read(cleanControllerProvider).phase == CleanPhase.created);
    expect(h.camera.lastFile, isNotNull);
    expect(h.backend.assets.values.single['stored'], 50000, reason: 'the recorded file was streamed to storage');
    expect(h.backend.editBodies.single['instruction'], contains('pauses'));
    final raw = c.read(rawSecondsProvider('edit-1'))!;
    expect(raw, greaterThan(0.2));
    expect(raw, lessThan(5));
  });

  test('recording before the camera is ready does nothing', () async {
    final h = await Harness.create();
    final c = h.container();
    addTearDown(c.dispose);
    c.listen(cameraSessionProvider, (_, _) {});
    final s = c.read(cameraSessionProvider.notifier);
    await s.startRecording();
    expect(c.read(cameraSessionProvider).phase, CameraPhase.opening);
    expect(await s.stopAndClean(), isFalse);
  });

  test('permission denied, missing camera and hardware failure map to their own states', () async {
    for (final (kind, phase) in [
      (CameraFailureKind.permissionDenied, CameraPhase.permissionDenied),
      (CameraFailureKind.unavailable, CameraPhase.unavailable),
      (CameraFailureKind.failed, CameraPhase.failed),
    ]) {
      final h = await Harness.create();
      h.camera.openFailure = CameraFailure(kind);
      final c = h.container();
      c.listen(cameraSessionProvider, (_, _) {});
      await c.read(cameraSessionProvider.notifier).open();
      expect(c.read(cameraSessionProvider).phase, phase);
      c.dispose();
    }
  });

  test('going to the background mid-recording saves and cleans the take instead of losing it', () async {
    final h = await Harness.create();
    final c = h.container();
    addTearDown(c.dispose);
    c.listen(cameraSessionProvider, (_, _) {});
    final s = c.read(cameraSessionProvider.notifier);
    await s.open();
    await s.startRecording();
    expect(await s.handleInterruption(), isTrue);
    await until(() => c.read(cleanControllerProvider).phase == CleanPhase.created);
  });

  test('backgrounding while idle releases the camera', () async {
    final h = await Harness.create();
    final c = h.container();
    addTearDown(c.dispose);
    c.listen(cameraSessionProvider, (_, _) {});
    final s = c.read(cameraSessionProvider.notifier);
    await s.open();
    expect(await s.handleInterruption(), isFalse);
    expect(h.camera.closed, isTrue);
  });

  test('flip reopens the other camera; the light toggles', () async {
    final h = await Harness.create();
    final c = h.container();
    addTearDown(c.dispose);
    c.listen(cameraSessionProvider, (_, _) {});
    final s = c.read(cameraSessionProvider.notifier);
    await s.open();
    await s.flip();
    expect(c.read(cameraSessionProvider).front, isTrue);
    expect(h.camera.openCount, 2);
    await s.toggleTorch();
    expect(h.camera.torchOn, isTrue);
  });

  test('time saved is derived from real durations only', () {
    expect(Format.saved(77, 17), '1m saved');
    expect(Format.saved(40, 22), '18s saved');
    expect(Format.saved(300, 60), '4m saved');
    expect(Format.saved(20, 18), isNull, reason: 'trivial differences are not claimed');
    expect(Format.saved(10, 30), isNull);
    expect(Format.duration(77), '1:17');
  });
}
