import { useState, useEffect } from 'react';
import { Header } from '@/components/Header';
import { BookCard } from '@/components/BookCard';
import { CreateBookDialog } from '@/components/CreateBookDialog';
import { Book, Loader2 } from 'lucide-react';
import { booksApi, type Book as BookType } from '@/lib/api';
import { toast } from 'sonner';

export default function BooksPage() {
  const [books, setBooks] = useState<BookType[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);

  const loadBooks = async () => {
    try {
      const data = await booksApi.list();
      setBooks(data);
    } catch (error) {
      console.error('Failed to load books:', error);
      toast.error('Failed to load books. Make sure the backend is running.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadBooks();
  }, []);

  const handleCreateBook = async (title: string, size: string) => {
    setIsCreating(true);
    try {
      const newBook = await booksApi.create({ title, size });
      setBooks((prev) => [newBook, ...prev]);
      toast.success('Book created successfully');
    } catch (error) {
      console.error('Failed to create book:', error);
      toast.error('Failed to create book');
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <Header />
      
      <main className="container mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-semibold text-foreground">My Photo Books</h1>
            <p className="text-muted-foreground mt-1">
              Create and manage your photo book projects
            </p>
          </div>
          <CreateBookDialog onCreateBook={handleCreateBook} isLoading={isCreating} />
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : books.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center mb-4">
              <Book className="h-8 w-8 text-muted-foreground" />
            </div>
            <h2 className="text-lg font-medium text-foreground mb-2">No books yet</h2>
            <p className="text-muted-foreground max-w-sm">
              Create your first photo book to start organizing your trip memories.
            </p>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {books.map((book) => (
              <BookCard key={book.id} book={book} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
