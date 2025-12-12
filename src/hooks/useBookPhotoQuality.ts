import { useEffect, useState } from 'react';
import { booksApi, type PhotoQualityMetrics } from '@/lib/api';

export function useBookPhotoQuality(bookId: string | undefined) {
  const [data, setData] = useState<PhotoQualityMetrics[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!bookId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    booksApi
      .getBookPhotoQuality(bookId)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message || 'Failed to load photo quality metrics');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [bookId]);

  return { data, loading, error };
}
