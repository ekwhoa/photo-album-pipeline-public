export function formatDaySegmentSummary(args: {
  segment_count?: number;
  total_hours?: number;
  total_km?: number;
}): string {
  const count = args.segment_count ?? 0;
  if (count <= 0) return '';

  const parts: string[] = [];
  parts.push(`${count} ${count === 1 ? 'segment' : 'segments'}`);

  const hours = args.total_hours ?? 0;
  if (hours > 0) {
    parts.push(`${hours.toFixed(1)} h`);
  }

  const km = args.total_km ?? 0;
  if (km > 0) {
    parts.push(`~${km.toFixed(1)} km`);
  }

  return parts.join(' • ');
}

export interface SegmentSummaryMini {
  index: number;
  distance_km?: number;
  duration_hours?: number;
  start_label?: string | null;
  end_label?: string | null;
}

export function formatSegmentBlurb(
  segment: SegmentSummaryMini,
  indexOverride?: number
): string {
  const idx = indexOverride ?? segment.index;
  const parts: string[] = [];

  const label =
    segment.start_label || segment.end_label
      ? `${segment.start_label ?? ''}${segment.start_label && segment.end_label ? ' → ' : ''}${segment.end_label ?? ''}`
      : `Segment ${idx}`;
  parts.push(label.trim());

  const hours = segment.duration_hours;
  if (typeof hours === 'number' && hours > 0) {
    parts.push(`${hours.toFixed(1)} h`);
  }

  const km = segment.distance_km;
  if (typeof km === 'number' && km > 0) {
    parts.push(`${km.toFixed(1)} km`);
  }

  return parts.join(' • ');
}

export function formatSegmentLegendItem(
  segment: SegmentSummaryMini,
  indexOverride?: number
): string {
  const idx = indexOverride ?? segment.index;
  const parts: string[] = [];
  parts.push(`Segment ${idx}`);
  const hours = segment.duration_hours;
  if (typeof hours === 'number' && hours > 0) {
    parts.push(`${hours.toFixed(1)} h`);
  }
  const km = segment.distance_km;
  if (typeof km === 'number' && km > 0) {
    parts.push(`${km.toFixed(1)} km`);
  }
  return parts.join(' • ');
}
