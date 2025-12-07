import { useMemo } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { BookOpen, FileText, Grid3X3, Image, MapPin, Star, Calendar } from 'lucide-react';
import type { Asset, PagePreview } from '@/lib/api';
import { getAssetUrl, getThumbnailUrl } from '@/lib/api';

interface PagePreviewCardProps {
  page: PagePreview;
  assets: Asset[]; // unused, kept for prop compatibility
  bookTitle?: string;
  onClick?: () => void;
}

const PAGE_TYPE_LABELS: Record<string, string> = {
  front_cover: 'Front Cover',
  back_cover: 'Back Cover',
  photo_grid: 'Photo Grid',
  day_intro: 'Day Intro',
  photo_spread: 'Photo Spread',
  full_page_photo: 'Full Page Photo',
  photo_full: 'Full Page Photo',
  trip_summary: 'Trip Summary',
  map_route: 'Map Route',
  spotlight: 'Spotlight',
  itinerary: 'Itinerary',
};

const PAGE_ICONS: Record<string, React.ReactNode> = {
  front_cover: <BookOpen className="h-4 w-4" />,
  back_cover: <BookOpen className="h-4 w-4" />,
  photo_grid: <Grid3X3 className="h-4 w-4" />,
  day_intro: <Calendar className="h-4 w-4" />,
  photo_spread: <Image className="h-4 w-4" />,
  full_page_photo: <Image className="h-4 w-4" />,
  photo_full: <Image className="h-4 w-4" />,
  trip_summary: <FileText className="h-4 w-4" />,
  map_route: <MapPin className="h-4 w-4" />,
  spotlight: <Star className="h-4 w-4" />,
  itinerary: <Calendar className="h-4 w-4" />,
};

export function PagePreviewCard({ page, assets, bookTitle, onClick }: PagePreviewCardProps) {
  const label = PAGE_TYPE_LABELS[page.page_type] || page.page_type;
  const icon = PAGE_ICONS[page.page_type] || <Image className="h-4 w-4" />;
  const assetMap = useMemo(() => {
    const map: Record<string, Asset> = {};
    assets.forEach((a) => (map[a.id] = a));
    return map;
  }, [assets]);

  const heroId = page.asset_ids?.[0] || page.hero_asset_id || null;
  const heroAsset = heroId ? assetMap[heroId] : undefined;
  const heroSrc = heroAsset ? (heroAsset.thumbnail_path ? getThumbnailUrl(heroAsset) : getAssetUrl(heroAsset)) : '';
  const spreadSlot = (page as any).spread_slot || (page as any).spreadSlot;

  return (
    <Card
      className="cursor-pointer hover:ring-2 hover:ring-primary/50 transition-all group overflow-hidden"
      onClick={onClick}
    >
      <CardContent className="p-0">
        <div className="aspect-[3/4] bg-muted relative overflow-hidden flex items-center justify-center">
          {(page.page_type === 'photo_spread' && heroSrc && spreadSlot) ? (
            <SpreadImage src={heroSrc} slot={spreadSlot} />
          ) : (page.page_type === 'photo_full' || page.page_type === 'full_page_photo') && heroSrc ? (
            <div className="photo-full-inner w-full h-full flex items-center justify-center p-2">
              <img src={heroSrc} alt="" className="photo-full-image" />
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

function SpreadImage({ src, slot }: { src: string; slot: 'left' | 'right' }) {
  const cls = slot === 'left' ? 'spread-img spread-img-left' : 'spread-img spread-img-right';
  return (
    <div className="spread-frame">
      <img src={src} alt="" className={cls} />
    </div>
  );
}
