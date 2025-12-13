import { useEffect, useState } from 'react';
import { booksApi, type PhotoQualityMetrics } from '@/lib/api';

const QUALITY_SUGGESTION_LIMIT = 18;

export function useBookPhotoQualitySummary(bookId: string | undefined, limit = QUALITY_SUGGESTION_LIMIT) {
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
        if (cancelled) return;
        const sorted = (res || []).slice().sort((a, b) => b.quality_score - a.quality_score);
        setData(sorted.slice(0, limit));
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message || 'Failed to load photo quality summary');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [bookId, limit]);

  return { data, loading, error };
}
