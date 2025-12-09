import { useEffect, useState } from 'react';
import { booksApi } from '@/lib/api';
import type { BookItinerary } from '@/types/book';

export function useBookItinerary(bookId: string | undefined) {
  const [data, setData] = useState<BookItinerary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!bookId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    booksApi
      .getItinerary(bookId)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err: Error) => {
        console.error('Failed to load itinerary', err);
        if (!cancelled) setError(err.message || 'Failed to load itinerary');
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
