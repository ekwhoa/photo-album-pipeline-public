import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { BookOpen, Image, Layout, FileText } from 'lucide-react';
import type { PagePreview } from '@/lib/api';
import { PAGE_TYPE_LABELS, PageType } from '@/types/book';

interface PagePreviewListProps {
  pages: PagePreview[];
}

const PAGE_ICONS: Record<string, React.ReactNode> = {
  front_cover: <BookOpen className="h-4 w-4" />,
  back_cover: <BookOpen className="h-4 w-4" />,
  photo_grid: <Image className="h-4 w-4" />,
  trip_summary: <FileText className="h-4 w-4" />,
};

export function PagePreviewList({ pages }: PagePreviewListProps) {
  if (pages.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
        <Layout className="h-12 w-12 mb-4 opacity-50" />
        <p>No pages generated yet</p>
        <p className="text-sm mt-1">Generate the book to see page previews</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {pages.map((page) => (
        <Card key={page.index} className="overflow-hidden">
          <CardContent className="p-4">
            <div className="flex items-center gap-4">
              <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-muted text-muted-foreground">
                {PAGE_ICONS[page.page_type] || <Layout className="h-4 w-4" />}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm">
                    Page {page.index + 1}
                  </span>
                  <Badge variant="secondary">
                    {PAGE_TYPE_LABELS[page.page_type as PageType] || page.page_type}
                  </Badge>
                </div>
                <p className="text-sm text-muted-foreground truncate mt-0.5">
                  {page.summary}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
