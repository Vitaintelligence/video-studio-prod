/// Target platform. `id` is the exact value the backend accepts.
enum AdPlatform {
  tiktok('tiktok', 'TikTok'),
  reels('reels', 'Instagram Reels'),
  meta('meta', 'Meta'),
  shorts('shorts', 'YouTube Shorts');

  const AdPlatform(this.id, this.label);
  final String id;
  final String label;

  static AdPlatform fromId(String? id) => values.firstWhere((p) => p.id == id, orElse: () => AdPlatform.tiktok);
}

/// Output aspect ratio. `id` is the exact value the backend accepts.
enum AdFormat {
  vertical('9:16', 'Vertical', '9:16'),
  square('1:1', 'Square', '1:1'),
  landscape('16:9', 'Landscape', '16:9');

  const AdFormat(this.id, this.label, this.ratio);
  final String id;
  final String label;
  final String ratio;

  static AdFormat fromId(String? id) => values.firstWhere((f) => f.id == id, orElse: () => AdFormat.vertical);
}
