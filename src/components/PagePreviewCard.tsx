import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  BookOpen,
  FileText,
  Grid3X3,
  Image,
  MapPin,
  Star,
  Calendar,
} from 'lucide-react';
import { type Asset, type PagePreview, getThumbnailUrl } from '@/lib/api';

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
  front_cover: <BookOpen className="h-4 w-4" />,
  back_cover: <BookOpen className="h-4 w-4" />,
  photo_grid: <Grid3X3 className="h-4 w-4" />,
  trip_summary: <FileText className="h-4 w-4" />,
  map_route: <MapPin className="h-4 w-4" />,
  spotlight: <Star className="h-4 w-4" />,
  itinerary: <Calendar className="h-4 w-4" />,
};

interface PagePreviewCardProps {
  page: PagePreview;
  assets: Asset[];
  bookTitle?: string;
  onClick?: () => void;
}

export function PagePreviewCard({ page, assets, bookTitle, onClick }: PagePreviewCardProps) {
  const approvedAssets = assets.filter(a => a.status === 'approved');
  const icon = PAGE_ICONS[page.page_type] || <Image className="h-4 w-4" />;
  const label = PAGE_TYPE_LABELS[page.page_type] || page.page_type;

  // Get thumbnails for photo grid pages
  const getPageThumbnails = () => {
    if (page.page_type !== 'photo_grid') return [];
    // Extract photo count from summary (e.g., "4 photos")
    const match = page.summary.match(/(\d+)\s*photos?/i);
    const photoCount = match ? parseInt(match[1], 10) : 4;
    
    // Calculate which assets belong to this page based on page index
    // Pages before this one that are photo_grids would have consumed some assets
    const photoPagesBeforeThis = page.index - 2; // Subtract front_cover (0) and trip_summary (1)
    const assetsPerPage = 4; // Rough estimate
    const startIdx = Math.max(0, photoPagesBeforeThis * assetsPerPage);
    const endIdx = startIdx + photoCount;
    
    return approvedAssets.slice(startIdx, endIdx).slice(0, 6);
  };

  const thumbnails = getPageThumbnails();

  return (
    <Card 
      className="cursor-pointer hover:ring-2 hover:ring-primary/50 transition-all group overflow-hidden"
      onClick={onClick}
    >
      <CardContent className="p-0">
        {/* Visual Preview Area */}
        <div className="aspect-square bg-muted relative overflow-hidden">
          {page.page_type === 'photo_grid' && thumbnails.length > 0 ? (
            <div className="grid grid-cols-2 gap-0.5 p-1 h-full">
              {thumbnails.slice(0, 4).map((asset, idx) => (
                <div key={asset.id} className="relative overflow-hidden bg-background/50">
                  <img
                    src={getThumbnailUrl(asset)}
                    alt=""
                    className="w-full h-full object-cover"
                  />
                </div>
              ))}
              {thumbnails.length < 4 && Array.from({ length: 4 - thumbnails.length }).map((_, idx) => (
                <div key={`empty-${idx}`} className="bg-background/30" />
              ))}
            </div>
          ) : page.page_type === 'front_cover' || page.page_type === 'back_cover' ? (
            <div className="flex flex-col items-center justify-center h-full p-4 text-center">
              <BookOpen className="h-8 w-8 text-muted-foreground mb-2" />
              <p className="text-sm font-medium text-foreground line-clamp-2">
                {bookTitle || 'Untitled'}
              </p>
              {page.page_type === 'back_cover' && (
                <p className="text-xs text-muted-foreground mt-1">© {bookTitle}</p>
              )}
            </div>
          ) : page.page_type === 'trip_summary' ? (
            <div className="flex flex-col items-center justify-center h-full p-4 text-center">
              <FileText className="h-8 w-8 text-muted-foreground mb-2" />
              <p className="text-xs text-muted-foreground line-clamp-3">
                {page.summary}
              </p>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full p-4">
              {icon}
              <p className="text-xs text-muted-foreground mt-2 text-center">
                {page.summary}
              </p>
            </div>
          )}
          
          {/* Page number badge */}
          <Badge 
            variant="secondary" 
            className="absolute top-2 left-2 text-xs"
          >
            {page.index + 1}
          </Badge>
        </div>

        {/* Label */}
        <div className="p-3 border-t">
          <div className="flex items-center gap-2">
            {icon}
            <span className="text-sm font-medium">{label}</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
