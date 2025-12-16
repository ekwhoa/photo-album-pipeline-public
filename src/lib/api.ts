// API client for communicating with the Python backend
// Default to localhost:8000 for local development
import type { BookItinerary } from '@/types/book';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface Book {
  id: string;
  title: string;
  size: string;
  created_at: string;
  updated_at: string;
  asset_count: number;
  approved_count: number;
  last_generated?: string;
  pdf_path?: string;
}

export interface Asset {
  id: string;
  book_id: string;
  status: 'imported' | 'approved' | 'rejected';
  type: string;
  file_path: string;
  thumbnail_path?: string;
  metadata: {
    width?: number;
    height?: number;
    orientation?: string;
    taken_at?: string;
  };
}

export interface PagePreview {
  index: number;
  page_type: string;
  summary: string;
  asset_ids?: string[];
  hero_asset_id?: string | null;
  layout_variant?: 'default' | 'grid_3_hero' | 'grid_4_simple' | 'grid_2up' | 'grid_3up_hero' | 'grid_6_dense' | null;
  segment_id?: string | null;
  segment_kind?: 'local' | 'travel' | string | null;
  segment_label?: string | null;
  segment_distance_km?: number | null;
  segment_duration_hours?: number | null;
  segment_photo_count?: number | null;
  segment_count?: number;
  segments_total_distance_km?: number;
  segments_total_duration_hours?: number;
  segments?: {
    index: number;
    distance_km: number;
    duration_hours: number;
    start_label?: string | null;
    end_label?: string | null;
    polyline?: [number, number][];
  }[];
}

export interface GenerateResult {
  success: boolean;
  page_count: number;
  pdf_path: string;
  warnings: string[];
}

export interface UploadStats {
  uploaded: number;
  skipped_unsupported: number;
}

export interface UploadResponse {
  assets: Asset[];
  stats: UploadStats;
}

export interface AutoHiddenDuplicateCluster {
  cluster_id: string;
  kept_asset_id: string;
  hidden_asset_ids: string[];
}

export interface BookDedupeDebug {
  book_id: string;
  approved_count: number;
  considered_count: number;
  used_count: number;
  auto_hidden_clusters_count: number;
  auto_hidden_hidden_assets_count: number;
  auto_hidden_duplicate_clusters: AutoHiddenDuplicateCluster[];
}

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

export interface PlaceCandidateDebug {
  centerLat: number;
  centerLon: number;
  totalDurationHours: number;
  totalPhotos: number;
  totalDistanceKm: number;
  visitCount: number;
  dayIndices: number[];
  thumbnails: { id: string; thumbUrl: string | null }[];
  bestPlaceName?: string;
  rawName?: string;
  displayName?: string;
  stableId: string;
  overrideName?: string | null;
  hidden: boolean;
}

export interface PhotoQualityMetrics {
  photo_id: string;
  thumbnail_url?: string | null;
  file_path: string;
  blur_score: number;
  brightness: number;
  contrast: number;
  edge_density: number;
  quality_score: number;
  face_count?: number | null;
  flags: string[];
}

export interface DuplicateGroupDebug {
  photoIds: string[];
  representativeId: string;
  scores?: Record<string, number>;
  thumbnails: { photoId: string; thumbnailUrl: string | null }[];
}

export interface LikelyReject {
  photo_id: string;
  thumbnail_url?: string | null;
  file_path?: string | null;
  quality_score: number;
  flags: string[];
  reasons: string[];
  current_status?: string | null;
}

export interface DuplicateSuggestionMember {
  photo_id: string;
  similarity: number;
  quality_score?: number | null;
  flags: string[];
  thumbnail_url?: string | null;
}

export interface DuplicateSuggestionGroup {
  representative_id: string;
  keep_photo_id: string;
  reject_photo_ids: string[];
  members: DuplicateSuggestionMember[];
  reasons: string[];
}

export interface CurationSuggestions {
  generated_at: string;
  params: Record<string, any>;
  likely_rejects: LikelyReject[];
  duplicate_groups: DuplicateSuggestionGroup[];
}

export interface UpdatePlaceOverridePayload {
  customName?: string | null;
  hidden?: boolean;
}

export interface BookItineraryResponse extends BookItinerary {}

async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;
  
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Request failed' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}

// Books API
export const booksApi = {
  list: () => apiRequest<Book[]>('/books'),
  
  get: (id: string) => apiRequest<Book>(`/books/${id}`),
  getDedupeDebug: (id: string) => apiRequest<BookDedupeDebug>(`/books/${id}/dedupe_debug`),
  getSegmentDebug: (id: string) => apiRequest<BookSegmentDebugResponse>(`/books/${id}/segment_debug`),
  getItinerary: (id: string) => apiRequest<BookItinerary>(`/books/${id}/itinerary`),
  getPlacesDebug: (id: string): Promise<PlaceCandidateDebug[]> =>
    apiRequest<unknown[]>(`/books/${id}/places-debug`).then((data) =>
      (data || []).map((item) => ({
        centerLat: Number((item as any).center_lat ?? 0),
        centerLon: Number((item as any).center_lon ?? 0),
        totalDurationHours: Number((item as any).total_duration_hours ?? 0),
        totalPhotos: Number((item as any).total_photos ?? 0),
        totalDistanceKm: Number((item as any).total_distance_km ?? 0),
        visitCount: Number((item as any).visit_count ?? 0),
        dayIndices: ((item as any).day_indices as number[] | undefined) ?? [],
        thumbnails: ((item as any).thumbnails as any[] | undefined)?.map((t) => {
          const path = (t as any).thumbnail_path ?? (t as any).file_path ?? null;
          return {
            id: String((t as any).id ?? ''),
            thumbUrl: path ? `${API_BASE_URL}/media/${path}` : null,
          };
        }) ?? [],
        bestPlaceName: (item as any).best_place_name,
        rawName: (item as any).raw_name,
        displayName: (item as any).display_name,
        stableId: String((item as any).stable_id ?? ''),
        overrideName: (item as any).override_name,
        hidden: Boolean((item as any).hidden ?? false),
      }))
    ),
  getBookPhotoQuality: (id: string): Promise<PhotoQualityMetrics[]> =>
    apiRequest<any[]>(`/books/${id}/photo-quality-debug`).then((data) =>
      (data || []).map((item) => ({
        photo_id: String(item.photo_id ?? ''),
        thumbnail_url: item.thumbnail_url ? (String(item.thumbnail_url).startsWith('http') ? String(item.thumbnail_url) : `${API_BASE_URL}${String(item.thumbnail_url)}`) : null,
        file_path: String(item.file_path ?? ''),
        blur_score: Number(item.blur_score ?? 0),
        brightness: Number(item.brightness ?? 0),
        contrast: Number(item.contrast ?? 0),
        edge_density: Number(item.edge_density ?? 0),
        quality_score: Number(item.quality_score ?? 0),
        face_count: item.face_count ?? null,
        flags: (item.flags as string[] | undefined) ?? [],
      }))
    ),
  getBookPhotoDuplicates: (id: string): Promise<DuplicateGroupDebug[]> =>
    apiRequest<any[]>(`/books/${id}/photo-duplicates-debug`).then((res) =>
      (res || []).map((group) => {
        const rawThumbs = (group as any).thumbnails ?? [];
        return {
          photoIds: (group.photo_ids ?? group.photoIds ?? []) as string[],
          representativeId: String(group.representative_id ?? group.representativeId ?? ''),
          scores: (group.scores as Record<string, number> | undefined) ?? undefined,
          thumbnails: (rawThumbs || []).map((t: any) => ({
            photoId: String(t.photo_id ?? t.photoId ?? ''),
            thumbnailUrl: (t.thumbnail_url ?? t.thumbnailUrl ?? null) ? (String(t.thumbnail_url ?? t.thumbnailUrl).startsWith('http') ? String(t.thumbnail_url ?? t.thumbnailUrl) : `${API_BASE_URL}${String(t.thumbnail_url ?? t.thumbnailUrl)}`) : null,
          })),
        } as DuplicateGroupDebug;
      })
    ),
  getCurationSuggestions: (id: string): Promise<CurationSuggestions> =>
    apiRequest<any>(`/books/${id}/curation-suggestions`).then((raw) => {
      const data: CurationSuggestions = {
        generated_at: String(raw.generated_at ?? ''),
        params: raw.params ?? {},
        likely_rejects: (raw.likely_rejects || []).map((r: any) => ({
          photo_id: String(r.photo_id ?? ''),
          thumbnail_url: r.thumbnail_url ? (String(r.thumbnail_url).startsWith('http') ? String(r.thumbnail_url) : `${API_BASE_URL}${String(r.thumbnail_url)}`) : null,
          file_path: r.file_path ?? null,
          quality_score: Number(r.quality_score ?? 0),
          flags: (r.flags as string[] | undefined) ?? [],
          reasons: (r.reasons as string[] | undefined) ?? [],
          current_status: r.current_status ?? null,
        })),
        duplicate_groups: (raw.duplicate_groups || []).map((g: any) => ({
          representative_id: String(g.representative_id ?? ''),
          keep_photo_id: String(g.keep_photo_id ?? ''),
          reject_photo_ids: (g.reject_photo_ids || []).map((x: any) => String(x)),
          members: (g.members || []).map((m: any) => ({
            photo_id: String(m.photo_id ?? ''),
            similarity: Number(m.similarity ?? 0),
            quality_score: m.quality_score == null ? null : Number(m.quality_score),
            flags: (m.flags as string[] | undefined) ?? [],
            thumbnail_url: m.thumbnail_url ? (String(m.thumbnail_url).startsWith('http') ? String(m.thumbnail_url) : `${API_BASE_URL}${String(m.thumbnail_url)}`) : null,
          })),
          reasons: (g.reasons as string[] | undefined) ?? [],
        })),
      };
      return data;
    }),
  
  create: (data: { title: string; size: string }) =>
    apiRequest<Book>('/books', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  
  delete: (id: string) =>
    apiRequest<void>(`/books/${id}`, { method: 'DELETE' }),

  updatePlaceOverride: (bookId: string, stableId: string, payload: UpdatePlaceOverridePayload) =>
    // Convert camelCase payload keys to snake_case expected by the backend
    (async () => {
      const bodyPayload: any = {};
      if ((payload as any).customName !== undefined) bodyPayload.custom_name = (payload as any).customName;
      if ((payload as any).custom_name !== undefined) bodyPayload.custom_name = (payload as any).custom_name;
      if ((payload as any).hidden !== undefined) bodyPayload.hidden = (payload as any).hidden;

      const raw = await apiRequest<any>(
        `/books/${bookId}/places/${encodeURIComponent(stableId)}/override`,
        {
          method: 'POST',
          body: JSON.stringify(bodyPayload),
        }
      );

      // Map snake_case response to camelCase PlaceCandidateDebug
      const mapped: PlaceCandidateDebug = {
        centerLat: Number(raw.center_lat ?? 0),
        centerLon: Number(raw.center_lon ?? 0),
        totalDurationHours: Number(raw.total_duration_hours ?? 0),
        totalPhotos: Number(raw.total_photos ?? 0),
        totalDistanceKm: Number(raw.total_distance_km ?? 0),
        visitCount: Number(raw.visit_count ?? 0),
        dayIndices: (raw.day_indices as number[] | undefined) ?? [],
        thumbnails: ((raw.thumbnails as any[] | undefined) ?? []).map((t) => {
          const path = t.thumbnail_path ?? t.file_path ?? null;
          return { id: String(t.id ?? ''), thumbUrl: path ? `${API_BASE_URL}/media/${path}` : null };
        }),
        bestPlaceName: raw.best_place_name,
        rawName: raw.raw_name,
        displayName: raw.display_name,
        stableId: String(raw.stable_id ?? ''),
        overrideName: raw.override_name ?? null,
        hidden: Boolean(raw.hidden ?? false),
      };
      return mapped;
    })(),
};

// Assets API
export const assetsApi = {
  list: (bookId: string, status?: string) => {
    const params = status ? `?status=${status}` : '';
    return apiRequest<Asset[]>(`/books/${bookId}/assets${params}`);
  },
  
  upload: async (bookId: string, files: FileList): Promise<UploadResponse> => {
    const formData = new FormData();
    Array.from(files).forEach((file) => {
      formData.append('files', file);
    });

    const response = await fetch(`${API_BASE_URL}/books/${bookId}/assets/upload`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Upload failed' }));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }

    return response.json();
  },
  
  updateStatus: (bookId: string, assetId: string, status: 'approved' | 'rejected') =>
    apiRequest<Asset>(`/books/${bookId}/assets/${assetId}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    }),
  
  bulkUpdateStatus: (bookId: string, assetIds: string[], status: 'approved' | 'rejected') =>
    apiRequest<Asset[]>(`/books/${bookId}/assets/bulk-status`, {
      method: 'PATCH',
      body: JSON.stringify({ asset_ids: assetIds, status }),
    }),
};

// Pipeline API
export const pipelineApi = {
  generate: (bookId: string) =>
    apiRequest<GenerateResult>(`/books/${bookId}/generate`, { method: 'POST' }),
  
  getPages: (bookId: string) =>
    apiRequest<PagePreview[]>(`/books/${bookId}/pages`),
  
  getPdfUrl: (bookId: string) => `${API_BASE_URL}/books/${bookId}/pdf`,

  getPreviewHtml: (bookId: string) =>
    apiRequest<{ html: string }>(`/books/${bookId}/preview-html`),

  getPagePreviewHtml: (bookId: string, pageIndex: number) =>
    apiRequest<{ html: string }>(`/books/${bookId}/preview/pages/${pageIndex}/html`),
};

// Get thumbnail/image URL
export const getAssetUrl = (asset: Asset) => 
  `${API_BASE_URL}/media/${asset.file_path}`;

export const getThumbnailUrl = (asset: Asset) =>
  asset.thumbnail_path 
    ? `${API_BASE_URL}/media/${asset.thumbnail_path}`
    : getAssetUrl(asset);
