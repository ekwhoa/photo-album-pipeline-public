import { useQuery } from '@tanstack/react-query';
import { booksApi, type DuplicateGroupDebug } from '@/lib/api';

export function useBookPhotoDuplicates(bookId: string | undefined) {
  return useQuery<DuplicateGroupDebug[], Error>({
    queryKey: ['book-photo-duplicates', bookId],
    queryFn: () => booksApi.getBookPhotoDuplicates(bookId ?? ''),
    enabled: !!bookId,
  });
}
