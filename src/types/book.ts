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
  | 'grid_4_simple'
  | 'grid_2up'
  | 'grid_3up_hero'
  | 'grid_6_dense';

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
  layout_variant?: GridLayoutVariant;
}

export const BOOK_SIZES = [
  { value: '8x8', label: '8" × 8" Square' },
  { value: '10x10', label: '10" × 10" Square' },
  { value: '8x10', label: '8" × 10" Portrait' },
  { value: '10x8', label: '10" × 8" Landscape' },
  { value: '11x14', label: '11" × 14" Large' },
];
