import { useEffect, useState } from 'react';
import { booksApi, type BookSegmentDebugResponse } from '@/lib/api';

export function useBookSegmentDebug(bookId: string | undefined) {
  const [data, setData] = useState<BookSegmentDebugResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!bookId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    booksApi
      .getSegmentDebug(bookId)
      .then((res) => {
        if (!cancelled) {
          setData(res);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message || 'Failed to load segment info');
        }
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
