import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'package:video_player/video_player.dart';

/// A video ready to upload. Only the path is kept: the file is streamed from disk, never loaded whole.
class PickedFootage {
  const PickedFootage({required this.path, required this.name, required this.sizeBytes});

  final String path;
  final String name;
  final int sizeBytes;
}

abstract interface class FootagePicker {
  /// Video from the Photos library, or null if the user cancelled.
  Future<PickedFootage?> pickFromPhotos();

  /// Video from the Files app, or null if the user cancelled.
  Future<PickedFootage?> pickFromFiles();

  /// Duration in seconds of a local video, or null if it cannot be read.
  Future<double?> durationOf(String path);
}

class DeviceFootagePicker implements FootagePicker {
  const DeviceFootagePicker();

  @override
  Future<PickedFootage?> pickFromPhotos() async {
    final file = await ImagePicker().pickVideo(source: ImageSource.gallery);
    if (file == null) return null;
    return PickedFootage(path: file.path, name: file.name, sizeBytes: await file.length());
  }

  @override
  Future<PickedFootage?> pickFromFiles() async {
    final files = await FilePicker.pickFiles(type: FileType.video);
    if (files.isEmpty || files.first.path == null) return null;
    final f = files.first;
    return PickedFootage(path: f.path!, name: f.name, sizeBytes: await f.length() ?? 0);
  }

  @override
  Future<double?> durationOf(String path) async {
    final controller = VideoPlayerController.file(File(path));
    try {
      await controller.initialize();
      final ms = controller.value.duration.inMilliseconds;
      return ms > 0 ? ms / 1000 : null;
    } on Object {
      return null;
    } finally {
      await controller.dispose();
    }
  }
}

final footagePickerProvider = Provider<FootagePicker>((ref) => const DeviceFootagePicker());
