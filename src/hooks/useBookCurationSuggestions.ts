import { useQuery } from '@tanstack/react-query';
import { booksApi, type CurationSuggestions } from '@/lib/api';

type Options = {
  enabled?: boolean;
};

export function useBookCurationSuggestions(bookId: string | undefined, options: Options = { enabled: !!bookId }) {
  const enabled = options.enabled ?? !!bookId;
  return useQuery<CurationSuggestions, Error>({
    queryKey: ['book-curation-suggestions', bookId],
    queryFn: () => booksApi.getCurationSuggestions(bookId ?? ''),
    enabled: enabled && !!bookId,
    staleTime: 1000 * 60 * 5, // 5 minutes default staleness to avoid frequent refetches
    cacheTime: 1000 * 60 * 10,
  });
}
