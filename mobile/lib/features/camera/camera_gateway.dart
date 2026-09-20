import 'dart:io';

import 'package:camera/camera.dart';
import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

enum CameraFailureKind { permissionDenied, unavailable, failed }

class CameraFailure implements Exception {
  const CameraFailure(this.kind);
  final CameraFailureKind kind;
}

class RecordedVideo {
  const RecordedVideo({required this.path, required this.sizeBytes});
  final String path;
  final int sizeBytes;
}

/// The camera hardware, behind an interface so the recording flow can be tested without a device.
abstract interface class CameraGateway {
  /// Opens the front or back camera with audio. Throws [CameraFailure].
  Future<void> open({required bool front});
  bool get hasTorch;
  bool get canFlip;
  Widget preview();
  Future<void> startRecording();
  Future<RecordedVideo> stopRecording();
  Future<void> setTorch(bool on);
  Future<void> close();
}

class PluginCameraGateway implements CameraGateway {
  CameraController? _controller;
  List<CameraDescription> _cameras = const [];
  bool _isOpening = false;

  @override
  bool canFlip = false;

  @override
  bool hasTorch = false;

  @override
  Future<void> open({required bool front}) async {
    if (_isOpening) return;
    _isOpening = true;
    await close();
    try {
      _cameras = await availableCameras();
      if (_cameras.isEmpty) throw const CameraFailure(CameraFailureKind.unavailable);
      final wanted = front ? CameraLensDirection.front : CameraLensDirection.back;
      final description = _cameras.firstWhere(
        (c) => c.lensDirection == wanted,
        orElse: () => _cameras.first,
      );
      canFlip =
          _cameras.any((c) => c.lensDirection == CameraLensDirection.front) &&
          _cameras.any((c) => c.lensDirection == CameraLensDirection.back);
      final controller = CameraController(
        description,
        ResolutionPreset.high,
        enableAudio: true,
      );
      await controller.initialize();
      _controller = controller;
      hasTorch = description.lensDirection == CameraLensDirection.back;
    } on CameraException catch (e) {
      _controller = null;
      final code = e.code.toLowerCase();
      final denied = code.contains('denied') ||
          code.contains('restricted') ||
          code.contains('permission');
      throw CameraFailure(denied ? CameraFailureKind.permissionDenied : CameraFailureKind.failed);
    } catch (_) {
      _controller = null;
      throw const CameraFailure(CameraFailureKind.failed);
    } finally {
      _isOpening = false;
    }
  }

  @override
  Widget preview() {
    final controller = _controller;
    if (controller == null || !controller.value.isInitialized) {
      return const ColoredBox(
        color: Color(0xFF10101C),
        child: Center(
          child: CupertinoActivityIndicator(color: Color(0xFFFFFFFF)),
        ),
      );
    }
    return ClipRect(
      child: CameraPreview(controller),
    );
  }

  @override
  Future<void> startRecording() async {
    final c = _controller;
    if (c == null || !c.value.isInitialized) {
      throw const CameraFailure(CameraFailureKind.failed);
    }
    try {
      await c.startVideoRecording();
    } on CameraException {
      throw const CameraFailure(CameraFailureKind.failed);
    } catch (_) {
      throw const CameraFailure(CameraFailureKind.failed);
    }
  }

  @override
  Future<RecordedVideo> stopRecording() async {
    final c = _controller;
    if (c == null || !c.value.isRecordingVideo) {
      throw const CameraFailure(CameraFailureKind.failed);
    }
    try {
      final file = await c.stopVideoRecording();
      return RecordedVideo(path: file.path, sizeBytes: await File(file.path).length());
    } on CameraException {
      throw const CameraFailure(CameraFailureKind.failed);
    } catch (_) {
      throw const CameraFailure(CameraFailureKind.failed);
    }
  }

  @override
  Future<void> setTorch(bool on) async {
    final c = _controller;
    if (c == null || !c.value.isInitialized) return;
    try {
      await c.setFlashMode(on ? FlashMode.torch : FlashMode.off);
    } on CameraException {
      throw const CameraFailure(CameraFailureKind.failed);
    } catch (_) {
      throw const CameraFailure(CameraFailureKind.failed);
    }
  }

  @override
  Future<void> close() async {
    final c = _controller;
    _controller = null;
    if (c != null) {
      try {
        await c.dispose();
      } catch (_) {}
    }
  }
}

final cameraGatewayProvider = Provider<CameraGateway>((ref) {
  final gateway = PluginCameraGateway();
  ref.onDispose(gateway.close);
  return gateway;
});
