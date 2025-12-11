import { useEffect, useState } from 'react';
import { booksApi, type PlaceCandidateDebug } from '@/lib/api';

export function useBookPlacesDebug(bookId: string | undefined) {
  const [data, setData] = useState<PlaceCandidateDebug[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!bookId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    booksApi
      .getPlacesDebug(bookId)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message || 'Failed to load places debug');
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
