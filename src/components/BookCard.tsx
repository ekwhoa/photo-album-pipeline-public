import { Link } from 'react-router-dom';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Book, Calendar, Image } from 'lucide-react';
import type { Book as BookType } from '@/lib/api';

interface BookCardProps {
  book: BookType;
}

export function BookCard({ book }: BookCardProps) {
  const formattedDate = new Date(book.created_at).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });

  return (
    <Link to={`/books/${book.id}`}>
      <Card className="hover:shadow-md transition-shadow cursor-pointer group">
        <CardContent className="p-5">
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0">
              <h3 className="font-medium text-foreground group-hover:text-primary transition-colors truncate">
                {book.title}
              </h3>
              <div className="flex items-center gap-3 mt-2 text-sm text-muted-foreground">
                <span className="flex items-center gap-1">
                  <Book className="h-3.5 w-3.5" />
                  {book.size}
                </span>
                <span className="flex items-center gap-1">
                  <Image className="h-3.5 w-3.5" />
                  {book.asset_count} photos
                </span>
              </div>
              <div className="flex items-center gap-1 mt-1 text-xs text-muted-foreground">
                <Calendar className="h-3 w-3" />
                {formattedDate}
              </div>
            </div>
            <div className="flex flex-col items-end gap-2">
              {book.approved_count > 0 && (
                <Badge variant="approved">
                  {book.approved_count} approved
                </Badge>
              )}
              {book.pdf_path && (
                <Badge variant="success">PDF Ready</Badge>
              )}
            </div>
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}
