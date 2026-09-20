import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:gal/gal.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import '../../core/api/api_exception.dart';

enum ExportTarget { photos, share }

/// Downloads a finished video, then saves it to Photos or hands it to the system share sheet.
abstract interface class ExportService {
  Future<void> export({
    required String url,
    required String fileName,
    required ExportTarget target,
    void Function(double progress)? onProgress,
  });
}

class ShareSheetExportService implements ExportService {
  const ShareSheetExportService();

  @override
  Future<void> export({
    required String url,
    required String fileName,
    required ExportTarget target,
    void Function(double progress)? onProgress,
  }) async {
    final client = http.Client();
    IOSink? sink;
    File? file;
    try {
      final response = await client.send(http.Request('GET', Uri.parse(url)));
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw const ApiException(code: 'EXPORT_FAILED', message: 'Export failed.');
      }
      final dir = await getTemporaryDirectory();
      file = File('${dir.path}${Platform.pathSeparator}$fileName');
      sink = file.openWrite();
      final total = response.contentLength ?? 0;
      var received = 0;
      await for (final chunk in response.stream) {
        sink.add(chunk);
        received += chunk.length;
        if (total > 0) onProgress?.call(received / total);
      }
      await sink.close();
      sink = null;
      switch (target) {
        case ExportTarget.photos:
          await Gal.putVideo(file.path);
        case ExportTarget.share:
          await SharePlus.instance.share(ShareParams(files: [XFile(file.path, mimeType: 'video/mp4')]));
      }
      await file.delete();
    } on http.ClientException {
      throw const ApiException.network();
    } on SocketException {
      throw const ApiException.network();
    } on GalException catch (e) {
      throw ApiException(
        code: e.type == GalExceptionType.accessDenied ? 'PHOTOS_DENIED' : 'EXPORT_FAILED',
        message: 'Could not save the video.',
      );
    } finally {
      await sink?.close();
      client.close();
    }
  }
}

final exportServiceProvider = Provider<ExportService>((ref) => const ShareSheetExportService());
