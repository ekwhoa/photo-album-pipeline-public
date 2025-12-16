import { useQuery } from '@tanstack/react-query';
import { booksApi, type CurationSuggestions } from '@/lib/api';

export function useBookCurationSuggestions(bookId: string | undefined) {
  return useQuery<CurationSuggestions, Error>({
    queryKey: ['book-curation-suggestions', bookId],
    queryFn: () => booksApi.getCurationSuggestions(bookId ?? ''),
    enabled: !!bookId,
  });
}
