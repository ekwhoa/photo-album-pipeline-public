import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { BookOpen, FileText, Grid3X3, Image, MapPin, Star, Calendar } from 'lucide-react';
import { type Asset, type PagePreview, getThumbnailUrl } from '@/lib/api';

interface PagePreviewCardProps {
  page: PagePreview;
  assets: Asset[];
  bookTitle?: string;
  onClick?: () => void;
}

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

export function PagePreviewCard({ page, assets, bookTitle, onClick }: PagePreviewCardProps) {
  const label = PAGE_TYPE_LABELS[page.page_type] || page.page_type;
  const icon = PAGE_ICONS[page.page_type] || <Image className="h-4 w-4" />;

  const assetLookup = new Map(assets.map((a) => [a.id, a]));
  const pageAssets = (page.asset_ids || []).map((id) => assetLookup.get(id)).filter(Boolean) as Asset[];
  const heroAsset = page.hero_asset_id ? assetLookup.get(page.hero_asset_id) : undefined;

  return (
    <Card
      className="cursor-pointer hover:ring-2 hover:ring-primary/50 transition-all group overflow-hidden"
      onClick={onClick}
    >
      <CardContent className="p-0">
        <div className="aspect-[3/4] bg-muted relative overflow-hidden flex items-center justify-center">
          {page.page_type === 'photo_grid' && pageAssets.length > 0 ? (
            <div className="grid grid-cols-2 grid-rows-2 w-full h-full">
              {pageAssets.slice(0, 4).map((asset) => (
                <div key={asset.id} className="relative overflow-hidden">
                  <img
                    src={getThumbnailUrl(asset)}
                    alt=""
                    className="w-full h-full object-cover"
                  />
                </div>
              ))}
              {Array.from({ length: Math.max(0, 4 - pageAssets.length) }).map((_, idx) => (
                <div key={`empty-${idx}`} className="bg-muted/60" />
              ))}
            </div>
          ) : page.page_type === 'front_cover' && heroAsset ? (
            <div className="w-full h-full relative">
              <img
                src={getThumbnailUrl(heroAsset)}
                alt=""
                className="w-full h-full object-cover"
              />
              <div className="absolute inset-0 bg-gradient-to-b from-black/30 to-black/50" />
              <div className="absolute bottom-3 left-3 right-3 text-white drop-shadow">
                <p className="text-sm font-semibold line-clamp-2">{bookTitle || 'Untitled'}</p>
                <p className="text-xs opacity-80">{page.summary}</p>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center gap-2 text-xs text-muted-foreground px-4 text-center">
              {icon}
              <span className="font-medium text-foreground">{label}</span>
              <p className="line-clamp-3 text-muted-foreground">{page.summary}</p>
            </div>
          )}

          <div className="absolute top-2 left-2">
            <span className="text-xs px-2 py-1 rounded bg-background/90 border text-foreground">
              {page.index + 1}
            </span>
          </div>
        </div>
        <div className="p-3 border-t">
          <div className="flex items-center gap-2">
            {icon}
            <span className="text-sm font-medium truncate">{label}</span>
          </div>
          <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
            {page.summary}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
