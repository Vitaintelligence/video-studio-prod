import 'package:flutter/cupertino.dart';

import '../design/app_colors.dart';
import '../design/app_radius.dart';

/// Network thumbnail decoded at display size (never full resolution), with a neutral placeholder.
class RemoteThumbnail extends StatelessWidget {
  const RemoteThumbnail({super.key, required this.url, this.width, this.height});

  final String? url;
  final double? width;
  final double? height;

  @override
  Widget build(BuildContext context) {
    final dpr = MediaQuery.devicePixelRatioOf(context);
    const placeholder = ColoredBox(
      color: AppColors.surfaceRaised,
      child: Center(child: Icon(CupertinoIcons.film, color: AppColors.textMuted, size: 24)),
    );
    final child = url == null
        ? placeholder
        : Image.network(
            url!,
            fit: BoxFit.cover,
            cacheWidth: width == null ? null : (width! * dpr).round(),
            gaplessPlayback: true,
            errorBuilder: (_, _, _) => placeholder,
            loadingBuilder: (_, image, progress) => progress == null ? image : placeholder,
          );
    return ExcludeSemantics(
      child: ClipRRect(
        borderRadius: AppRadius.smallAll,
        child: SizedBox(width: width, height: height, child: child),
      ),
    );
  }
}
