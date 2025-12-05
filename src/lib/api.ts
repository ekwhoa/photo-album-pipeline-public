// API client for communicating with the Python backend
// Default to localhost:8000 for local development

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
}

export interface GenerateResult {
  success: boolean;
  page_count: number;
  pdf_path: string;
  warnings: string[];
}

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
  
  upload: async (bookId: string, files: FileList): Promise<Asset[]> => {
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
};

// Get thumbnail/image URL
export const getAssetUrl = (asset: Asset) => 
  `${API_BASE_URL}/media/${asset.file_path}`;

export const getThumbnailUrl = (asset: Asset) =>
  asset.thumbnail_path 
    ? `${API_BASE_URL}/media/${asset.thumbnail_path}`
    : getAssetUrl(asset);
