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
  
  create: (data: { title: string; size: string }) =>
    apiRequest<Book>('/books', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  
  delete: (id: string) =>
    apiRequest<void>(`/books/${id}`, { method: 'DELETE' }),
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
