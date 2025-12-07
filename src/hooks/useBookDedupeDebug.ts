import { useEffect, useState } from 'react';
import { booksApi, type BookDedupeDebug } from '@/lib/api';

export function useBookDedupeDebug(bookId: string | undefined) {
  const [data, setData] = useState<BookDedupeDebug | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!bookId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    booksApi
      .getDedupeDebug(bookId)
      .then((res) => {
        if (!cancelled) {
          setData(res);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message || 'Failed to load curation info');
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

