import 'dart:io';

import 'package:adcut_mobile/app/providers.dart';
import 'package:adcut_mobile/features/camera/camera_controller.dart';
import 'package:adcut_mobile/features/camera/camera_gateway.dart';
import 'package:adcut_mobile/features/clean/footage_picker.dart';
import 'package:flutter/widgets.dart';
import 'package:adcut_mobile/features/edit/export_service.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:shared_preferences/shared_preferences.dart';

import 'fake_backend.dart';

class FakePicker implements FootagePicker {
  PickedFootage? next;
  double? seconds;

  @override
  Future<PickedFootage?> pickFromPhotos() async => next;

  @override
  Future<PickedFootage?> pickFromFiles() async => next;

  @override
  Future<double?> durationOf(String path) async => seconds;
}

/// A camera that "records" a real small file, so the whole record → upload path runs for real.
class FakeCamera implements CameraGateway {
  CameraFailure? openFailure;
  bool torchOn = false;
  bool closed = false;
  int openCount = 0;
  int startCount = 0;
  String? lastFile;

  @override
  bool canFlip = true;

  @override
  bool hasTorch = true;

  @override
  Future<void> open({required bool front}) async {
    openCount++;
    closed = false;
    if (openFailure != null) throw openFailure!;
  }

  @override
  Widget preview() => const SizedBox(width: 90, height: 160);

  @override
  Future<void> startRecording() async => startCount++;

  @override
  Future<RecordedVideo> stopRecording() async {
    lastFile = await tempVideo('REC_test.mp4', bytes: 50000);
    return RecordedVideo(path: lastFile!, sizeBytes: 50000);
  }

  @override
  Future<void> setTorch(bool on) async => torchOn = on;

  @override
  Future<void> close() async => closed = true;
}

class FakeExporter implements ExportService {
  final List<String> exported = [];
  final List<ExportTarget> targets = [];
  Object? failWith;

  @override
  Future<void> export({
    required String url,
    required String fileName,
    required ExportTarget target,
    void Function(double progress)? onProgress,
  }) async {
    if (failWith != null) throw failWith!;
    exported.add(url);
    targets.add(target);
  }
}

/// Everything a controller/screen test needs: a fake backend, prefs, picker and exporter.
class Harness {
  Harness._(this.backend, this.prefs);

  final FakeBackend backend;
  final SharedPreferences prefs;
  final FakePicker picker = FakePicker();
  final FakeExporter exporter = FakeExporter();
  final FakeCamera camera = FakeCamera();

  static Future<Harness> create({FakeBackend? backend, Map<String, Object> prefs = const {}}) async {
    SharedPreferences.setMockInitialValues({'onboarding.done': true, ...prefs});
    return Harness._(backend ?? FakeBackend(), await SharedPreferences.getInstance());
  }

  List<Override> overridesWith({int countdown = 0}) => [
    preferencesProvider.overrideWithValue(prefs),
    apiProvider.overrideWithValue(backend.api()),
    footagePickerProvider.overrideWithValue(picker),
    exportServiceProvider.overrideWithValue(exporter),
    cameraGatewayProvider.overrideWithValue(camera),
    pollIntervalProvider.overrideWithValue(const Duration(milliseconds: 10)),
    recordingCountdownProvider.overrideWithValue(countdown),
  ];

  List<Override> get overrides => overridesWith();

  ProviderContainer container({int countdown = 0}) =>
      ProviderContainer(retry: (_, _) => null, overrides: overridesWith(countdown: countdown));
}

/// Writes a small file that stands in for a video, and returns its path.
Future<String> tempVideo(String name, {int bytes = 4096}) async {
  final dir = await Directory.systemTemp.createTemp('adcut_test');
  final file = File('${dir.path}${Platform.pathSeparator}$name');
  await file.writeAsBytes(List.filled(bytes, 7));
  return file.path;
}

/// Polls [check] until it is true or [timeout] passes.
Future<void> until(bool Function() check, {Duration timeout = const Duration(seconds: 5)}) async {
  final end = DateTime.now().add(timeout);
  while (!check()) {
    if (DateTime.now().isAfter(end)) throw StateError('condition not met within $timeout');
    await Future<void>.delayed(const Duration(milliseconds: 5));
  }
}
