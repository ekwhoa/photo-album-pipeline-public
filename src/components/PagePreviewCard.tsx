import { useMemo } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { BookOpen, FileText, Grid3X3, Image, MapPin, Star, Calendar } from 'lucide-react';
import type { Asset } from '@/lib/api';
import { getAssetUrl, getThumbnailUrl } from '@/lib/api';
import type { BookPage, GridLayoutVariant } from '@/types/book';
import { formatDaySegmentSummary } from '@/lib/segmentFormat';

interface PagePreviewCardProps {
  page: BookPage;
  assets: Asset[]; // unused, kept for prop compatibility
  bookTitle?: string;
  onClick?: () => void;
  segmentSummary?: { segmentsCount: number; totalDurationMinutes: number; totalDistanceKm: number | null };
  dayNarrativeSummary?: { label: string; durationLabel: string; distanceLabel: string };
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

export function PagePreviewCard({ page, assets, bookTitle, onClick, segmentSummary, dayNarrativeSummary }: PagePreviewCardProps) {
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
  // For spreads, align with backend/PDF parity: first spread page is left, second is right.
  const spreadSlot: 'left' | 'right' = page.index % 2 === 0 ? 'left' : 'right';

  return (
    <Card
      className="cursor-pointer hover:ring-2 hover:ring-primary/50 transition-all group overflow-hidden"
      onClick={onClick}
    >
      <CardContent className="p-0">
        <div className="aspect-[3/4] bg-muted relative overflow-hidden flex items-center justify-center">
          {(page.page_type === 'photo_spread' && heroSrc) ? (
            <div className="photo-full-inner w-full h-full flex items-center justify-center p-2">
              <img
                src={heroSrc}
                alt="Photo spread hero"
                className="photo-full-image"
                style={{ objectPosition: spreadSlot === 'left' ? 'left center' : 'right center' }}
              />
            </div>
          ) : page.page_type === 'photo_grid' && (page.asset_ids?.length || 0) > 0 ? (
            <PhotoGridPreview page={page} assetMap={assetMap} />
          ) : (page.page_type === 'photo_full' || page.page_type === 'full_page_photo') && heroSrc ? (
            <div className="photo-full-inner w-full h-full flex items-center justify-center p-2">
              <img src={heroSrc} alt="" className="photo-full-image" />
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center gap-2 text-xs text-muted-foreground px-4 text-center">
              {icon}
              <span className="font-medium text-foreground">{label}</span>
              <p className="line-clamp-3 text-muted-foreground">{page.summary}</p>
              {page.page_type === 'day_intro' && (
                <>
                  {formatDaySegmentSummary({
                    segment_count: page.segment_count,
                    total_hours: page.segments_total_duration_hours,
                    total_km: page.segments_total_distance_km,
                  }) && (
                    <p className="text-[11px] text-muted-foreground">
                      {formatDaySegmentSummary({
                        segment_count: page.segment_count,
                        total_hours: page.segments_total_duration_hours,
                        total_km: page.segments_total_distance_km,
                      })}
                    </p>
                  )}
                  {dayNarrativeSummary && (
                    <p className="text-[11px] text-muted-foreground">
                      {dayNarrativeSummary.label}
                    </p>
                  )}
                </>
              )}
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

function getLayoutVariant(page: BookPage | null | undefined): GridLayoutVariant | null {
  return page?.layout_variant ?? null;
}

function PhotoGridPreview({ page, assetMap }: { page: BookPage; assetMap: Record<string, Asset> }) {
  const rawVariant = getLayoutVariant(page);
  const variant: GridLayoutVariant = rawVariant ?? 'default';
  const assets = (page.asset_ids || [])
    .map((id) => assetMap[id])
    .filter(Boolean) as Asset[];

  const renderImg = (asset: Asset, extraClass = '') => {
    const src = asset.thumbnail_path ? getThumbnailUrl(asset) : getAssetUrl(asset);
    return (
      <div className={`w-full h-full overflow-hidden rounded-md bg-muted ${extraClass}`}>
        <img src={src} alt="" className="w-full h-full object-cover" />
      </div>
    );
  };

  if (assets.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 text-xs text-muted-foreground px-4 text-center">
        <Grid3X3 className="h-4 w-4" />
        <span className="font-medium text-foreground">Photo Grid</span>
      </div>
    );
  }

  if (variant === 'grid_2up' && assets.length >= 2) {
    return (
      <div className="grid grid-cols-2 gap-1 w-full h-full p-1">
        {assets.slice(0, 2).map((asset) => renderImg(asset))}
      </div>
    );
  }

  if (variant === 'grid_3up_hero' && assets.length >= 3) {
    return (
      <div className="grid grid-cols-2 grid-rows-2 gap-1 w-full h-full p-1">
        <div className="row-span-2">{renderImg(assets[0])}</div>
        {renderImg(assets[1])}
        {renderImg(assets[2])}
      </div>
    );
  }

  if (variant === 'grid_3_hero' && assets.length >= 3) {
    return (
      <div className="grid grid-cols-2 grid-rows-[auto_auto] gap-1 w-full h-full p-1">
        <div className="col-span-2">{renderImg(assets[0])}</div>
        {assets.slice(1, 3).map((asset) => renderImg(asset))}
      </div>
    );
  }

  if (variant === 'grid_6_dense' && assets.length >= 5) {
    const slice = assets.slice(0, 6);
    return (
      <div className="grid grid-cols-3 grid-rows-2 gap-0.5 w-full h-full p-1">
        {slice.map((asset) => renderImg(asset))}
      </div>
    );
  }

  if (variant === 'grid_4_simple' && assets.length >= 4) {
    return (
      <div className="grid grid-cols-3 grid-rows-2 gap-1 w-full h-full p-1">
        {assets.slice(0, 3).map((asset) => renderImg(asset))}
        <div className="col-span-3">{renderImg(assets[3])}</div>
      </div>
    );
  }

  // Default 4-up (original layout / fallback)
  return (
    <div className="grid grid-cols-2 grid-rows-2 gap-1 w-full h-full p-1">
      {assets.slice(0, 4).map((asset) => renderImg(asset))}
    </div>
  );
}

function formatDurationShort(minutes: number) {
  if (!minutes || minutes <= 0) return '';
  const hours = minutes / 60;
  if (hours < 1) return '<1 h';
  if (hours >= 10) return `${Math.round(hours)} h`;
  return `${hours.toFixed(1)} h`;
}

function formatSegmentSummary(summary: { segmentsCount: number; totalDurationMinutes: number; totalDistanceKm: number | null }) {
  const parts: string[] = [];
  parts.push(`${summary.segmentsCount} ${summary.segmentsCount === 1 ? 'segment' : 'segments'}`);
  const dur = formatDurationShort(summary.totalDurationMinutes);
  if (dur) parts.push(dur);
  if (summary.totalDistanceKm != null && summary.totalDistanceKm > 0.1) {
    parts.push(`~${summary.totalDistanceKm.toFixed(1)} km`);
  }
  return parts.join(' • ');
}
