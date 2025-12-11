// Frontend type definitions matching the Python domain models

export type AssetStatus = 'imported' | 'approved' | 'rejected';
export type AssetType = 'photo' | 'ai_image' | 'map_image';

export type PageType = 
  | 'front_cover'
  | 'photo_grid'
  | 'day_intro'
  | 'photo_spread'
  | 'photo_full'
  | 'full_page_photo'
  | 'back_cover'
  // Future page types (not implemented yet)
  | 'map_route'
  | 'spotlight'
  | 'postcard_cover'
  | 'photobooth_strip'
  | 'trip_summary'
  | 'itinerary';

export const PAGE_TYPE_LABELS: Record<PageType, string> = {
  front_cover: 'Front Cover',
  photo_grid: 'Photo Grid',
  day_intro: 'Day Intro',
  photo_spread: 'Photo Spread',
  photo_full: 'Full Page Photo',
  full_page_photo: 'Full Page Photo',
  back_cover: 'Back Cover',
  map_route: 'Map Route',
  spotlight: 'Spotlight',
  postcard_cover: 'Postcard Cover',
  photobooth_strip: 'Photo Booth Strip',
  trip_summary: 'Trip Summary',
  itinerary: 'Itinerary',
};

export type GridLayoutVariant =
  | 'default'
  | 'grid_3_hero'
  | 'grid_4_simple'
  | 'grid_6_simple'
  | 'grid_2up'
  | 'grid_3up_hero'
  | 'grid_6_dense'
  | 'segment_local_highlight_v1';

export interface ItineraryLocation {
  location_short: string | null;
  location_full: string | null;
}

export interface SegmentSummary {
  index: number;
  distance_km: number;
  duration_hours: number;
  start_label?: string | null;
  end_label?: string | null;
  polyline?: [number, number][];
}

// Segment debug types
export interface SegmentDebugSegment {
  segment_index: number;
  asset_ids: string[];
  start_taken_at: string | null;
  end_taken_at: string | null;
  duration_minutes: number | null;
  approx_distance_km: number | null;
}

export interface SegmentDebugDay {
  day_index: number;
  date: string | null;
  asset_ids: string[];
  segments: SegmentDebugSegment[];
}

export interface BookSegmentDebugResponse {
  book_id: string;
  total_days: number;
  total_assets: number;
  days: SegmentDebugDay[];
}

export interface PhotoGridPage {
  page_type: 'photo_grid';
  asset_ids: string[];
  layout?: string;
  layout_variant?: GridLayoutVariant | null;
}

export interface DayIntroPage {
  page_type: 'day_intro';
  day_index: number;
  day_date?: string | null;
  display_date?: string | null;
  day_photo_count?: number;
  segment_count?: number;
  segments_total_distance_km?: number;
  segments_total_duration_hours?: number;
  segments?: SegmentSummary[];
  [key: string]: any;
}

export interface MapRoutePage {
  page_type: 'map_route';
  gps_photo_count?: number;
  distinct_locations?: number;
  route_image_path?: string;
  route_image_abs_path?: string;
  segments?: SegmentSummary[];
  [key: string]: any;
}

export interface ItineraryStop {
  segment_index: number;
  distance_km: number;
  duration_hours: number;
  location_short: string | null;
  location_full: string | null;
  polyline: [number, number][] | null;
  kind?: 'travel' | 'local' | 'other' | null;
  time_bucket?: string | null;
}

export interface ItineraryDay {
  day_index: number;
  date_iso: string;
  photos_count: number;
  segments_total_distance_km: number;
  segments_total_duration_hours: number;
  location_short: string | null;
  location_full: string | null;
  locations?: ItineraryLocation[];
  stops: ItineraryStop[];
}

export interface BookItinerary {
  book_id: string;
  days: ItineraryDay[];
}

export interface BookPage {
  index: number;
  page_type: PageType | string;
  summary?: string;
  asset_ids?: string[];
  hero_asset_id?: string | null;
  layout_variant?: GridLayoutVariant | string | null;
  segment_id?: string | null;
  segment_kind?: 'local' | 'travel' | string | null;
  segment_label?: string | null;
  segmentLabel?: string | null;
  segment_distance_km?: number | null;
  segment_duration_hours?: number | null;
  segment_photo_count?: number | null;
  segmentPhotoCount?: number | null;
  segment_count?: number | null;
  segments_total_distance_km?: number | null;
  segments_total_duration_hours?: number | null;
  segments?: SegmentSummary[] | any[];
  [key: string]: any;
}

export const BOOK_SIZES = [
  { value: '8x8', label: '8" × 8" Square' },
  { value: '10x10', label: '10" × 10" Square' },
  { value: '8x10', label: '8" × 10" Portrait' },
  { value: '10x8', label: '10" × 8" Landscape' },
  { value: '11x14', label: '11" × 14" Large' },
];
