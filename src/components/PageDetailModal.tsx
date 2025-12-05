import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  BookOpen,
  FileText,
  Grid3X3,
  Image,
  MapPin,
  Star,
  Calendar,
} from 'lucide-react';
import type { Asset, PagePreview } from '@/lib/api';

const PAGE_TYPE_LABELS: Record<string, string> = {
  front_cover: 'Front Cover',
  back_cover: 'Back Cover',
  photo_grid: 'Photo Grid',
  trip_summary: 'Trip Summary',
  map_route: 'Map Route',
  spotlight: 'Spotlight',
  itinerary: 'Itinerary',
};

const PAGE_ICONS: Record<string, React.ReactNode> = {
  front_cover: <BookOpen className="h-5 w-5" />,
  back_cover: <BookOpen className="h-5 w-5" />,
  photo_grid: <Grid3X3 className="h-5 w-5" />,
  trip_summary: <FileText className="h-5 w-5" />,
  map_route: <MapPin className="h-5 w-5" />,
  spotlight: <Star className="h-5 w-5" />,
  itinerary: <Calendar className="h-5 w-5" />,
};

interface PageDetailModalProps {
  page: PagePreview | null;
  pages: PagePreview[];
  assets: Asset[];
  bookTitle?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function PageDetailModal({ 
  page, 
  pages,
  assets, 
  bookTitle, 
  open, 
  onOpenChange 
}: PageDetailModalProps) {
  if (!page) return null;

  const icon = PAGE_ICONS[page.page_type] || <Image className="h-5 w-5" />;
  const label = PAGE_TYPE_LABELS[page.page_type] || page.page_type;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {icon}
            Page {page.index + 1} – {label}
          </DialogTitle>
        </DialogHeader>

        <div className="mt-4">
          <div className="text-center py-12 space-y-4 bg-muted/30 rounded-lg">
            <div className="flex items-center justify-center gap-3 text-foreground">
              {icon}
              <h2 className="text-2xl font-bold">Page {page.index + 1} – {label}</h2>
            </div>
            <p className="text-muted-foreground text-sm max-w-2xl mx-auto">
              {page.summary}
            </p>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
