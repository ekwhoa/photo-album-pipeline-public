import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
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

  const assetLookup = new Map(assets.map((a) => [a.id, a]));
  const pageAssets =
    page.page_type === 'photo_grid'
      ? (page.asset_ids || []).map((id) => assetLookup.get(id)).filter(Boolean) as Asset[]
      : [];
  const heroAsset =
    page.page_type === 'front_cover' && page.hero_asset_id
      ? assetLookup.get(page.hero_asset_id)
      : undefined;

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
          {page.page_type === 'photo_grid' ? (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">{page.summary}</p>
              {pageAssets.length > 0 ? (
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                  {pageAssets.map((asset) => (
                    <div 
                      key={asset.id} 
                      className="aspect-square rounded-lg overflow-hidden bg-muted"
                    >
                      <img
                        src={getThumbnailUrl(asset)}
                        alt=""
                        className="w-full h-full object-cover"
                      />
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground text-center py-8">
                  No photos to display
                </p>
              )}
            </div>
          ) : page.page_type === 'front_cover' ? (
            <div className="text-center py-12 space-y-4 bg-muted/30 rounded-lg">
              {heroAsset ? (
                <div className="mx-auto max-w-xl">
                  <div className="aspect-[3/4] rounded-lg overflow-hidden relative bg-muted">
                    <img
                      src={getThumbnailUrl(heroAsset)}
                      alt=""
                      className="w-full h-full object-cover"
                    />
                    <div className="absolute inset-0 bg-gradient-to-b from-black/30 to-black/60" />
                    <div className="absolute bottom-4 left-4 right-4 text-left text-white drop-shadow">
                      <h2 className="text-3xl font-bold">{bookTitle || 'Untitled'}</h2>
                      <p className="text-sm opacity-80">{page.summary}</p>
                    </div>
                  </div>
                </div>
              ) : (
                <>
                  <BookOpen className="h-16 w-16 mx-auto text-muted-foreground" />
                  <h2 className="text-3xl font-bold text-foreground">{bookTitle || 'Untitled'}</h2>
                  <p className="text-muted-foreground">{page.summary}</p>
                </>
              )}
            </div>
          ) : page.page_type === 'back_cover' ? (
            <div className="text-center py-12 space-y-4 bg-muted/30 rounded-lg">
              <BookOpen className="h-16 w-16 mx-auto text-muted-foreground" />
              <p className="text-lg text-foreground">{page.summary}</p>
            </div>
          ) : page.page_type === 'trip_summary' ? (
            <div className="text-center py-12 space-y-6 bg-muted/30 rounded-lg">
              <FileText className="h-16 w-16 mx-auto text-muted-foreground" />
              <div>
                <h2 className="text-2xl font-bold text-foreground mb-2">{bookTitle || 'Untitled'}</h2>
                <p className="text-lg text-muted-foreground">{page.summary}</p>
              </div>
              {/* Parse stats from summary if available */}
              {page.summary.includes('days') && (
                <div className="flex justify-center gap-8 text-sm">
                  {page.summary.split('•').map((stat, idx) => (
                    <Badge key={idx} variant="secondary" className="text-sm px-3 py-1">
                      {stat.trim()}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="text-center py-12 space-y-4 bg-muted/30 rounded-lg">
              {icon}
              <p className="text-muted-foreground">{page.summary}</p>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
