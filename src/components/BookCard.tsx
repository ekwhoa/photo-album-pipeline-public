import { useNavigate } from 'react-router-dom';
import { useState } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Book, Calendar, Image, Trash2 } from 'lucide-react';
import type { Book as BookType } from '@/lib/api';

interface BookCardProps {
  book: BookType;
  onDelete: (book: BookType) => Promise<void>;
  isDeleting?: boolean;
}

export function BookCard({ book, onDelete, isDeleting }: BookCardProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const navigate = useNavigate();
  const formattedDate = new Date(book.created_at).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });

  return (
    <Card
      className="hover:shadow-md transition-shadow cursor-pointer group"
      onClick={() => navigate(`/books/${book.id}`)}
    >
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
            <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
              <AlertDialogTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="text-muted-foreground hover:text-destructive"
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setConfirmOpen(true);
                  }}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Delete book?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Are you sure you want to delete this book? This will remove all its photos and pages.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction
                      onClick={async (e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        await onDelete(book);
                        setConfirmOpen(false);
                      }}
                      disabled={isDeleting}
                    >
                      {isDeleting ? 'Deleting...' : 'Delete'}
                    </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
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
  );
}
