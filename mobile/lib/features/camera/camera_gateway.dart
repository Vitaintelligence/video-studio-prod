import 'dart:io';

import 'package:camera/camera.dart';
import 'package:flutter/widgets.dart';
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

  @override
  bool canFlip = false;

  @override
  bool hasTorch = false;

  @override
  Future<void> open({required bool front}) async {
    await close();
    try {
      _cameras = await availableCameras();
      if (_cameras.isEmpty) throw const CameraFailure(CameraFailureKind.unavailable);
      final wanted = front ? CameraLensDirection.front : CameraLensDirection.back;
      final description = _cameras.firstWhere((c) => c.lensDirection == wanted, orElse: () => _cameras.first);
      canFlip =
          _cameras.any((c) => c.lensDirection == CameraLensDirection.front) &&
          _cameras.any((c) => c.lensDirection == CameraLensDirection.back);
      final controller = CameraController(
        description,
        ResolutionPreset.high,
        enableAudio: true,
        imageFormatGroup: ImageFormatGroup.yuv420,
      );
      _controller = controller;
      await controller.initialize();
      await controller.prepareForVideoRecording();
      hasTorch = description.lensDirection == CameraLensDirection.back;
    } on CameraException catch (e) {
      _controller = null;
      final denied = e.code.contains('AccessDenied') || e.code.contains('AccessRestricted');
      throw CameraFailure(denied ? CameraFailureKind.permissionDenied : CameraFailureKind.failed);
    }
  }

  @override
  Widget preview() {
    final controller = _controller;
    final previewSize = controller?.value.previewSize;
    if (controller == null || previewSize == null || !controller.value.isInitialized) {
      return const SizedBox.expand();
    }
    return LayoutBuilder(
      builder: (context, constraints) {
        final portrait = constraints.maxHeight >= constraints.maxWidth;
        final width = portrait ? previewSize.height : previewSize.width;
        final height = portrait ? previewSize.width : previewSize.height;
        return ClipRect(
          child: SizedBox.expand(
            child: FittedBox(
              fit: BoxFit.cover,
              child: SizedBox(width: width, height: height, child: CameraPreview(controller)),
            ),
          ),
        );
      },
    );
  }

  @override
  Future<void> startRecording() async {
    final controller = _controller;
    if (controller == null || !controller.value.isInitialized || controller.value.isRecordingVideo) {
      throw const CameraFailure(CameraFailureKind.failed);
    }
    try {
      await controller.startVideoRecording();
    } on CameraException {
      throw const CameraFailure(CameraFailureKind.failed);
    }
  }

  @override
  Future<RecordedVideo> stopRecording() async {
    final controller = _controller;
    if (controller == null || !controller.value.isRecordingVideo) {
      throw const CameraFailure(CameraFailureKind.failed);
    }
    try {
      final file = await controller.stopVideoRecording();
      return RecordedVideo(path: file.path, sizeBytes: await File(file.path).length());
    } on CameraException {
      throw const CameraFailure(CameraFailureKind.failed);
    }
  }

  @override
  Future<void> setTorch(bool on) async {
    try {
      await _controller?.setFlashMode(on ? FlashMode.torch : FlashMode.off);
    } on CameraException {
      throw const CameraFailure(CameraFailureKind.failed);
    }
  }

  @override
  Future<void> close() async {
    final c = _controller;
    _controller = null;
    hasTorch = false;
    await c?.dispose();
  }
}

final cameraGatewayProvider = Provider.autoDispose<CameraGateway>((ref) {
  final gateway = PluginCameraGateway();
  ref.onDispose(gateway.close);
  return gateway;
});
