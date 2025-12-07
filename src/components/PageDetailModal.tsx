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
import type { Asset } from '@/lib/api';
import type { BookPage, GridLayoutVariant } from '@/types/book';
import { getAssetUrl, getThumbnailUrl } from '@/lib/api';
import clsx from 'clsx';

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
  front_cover: <BookOpen className="h-5 w-5" />,
  back_cover: <BookOpen className="h-5 w-5" />,
  photo_grid: <Grid3X3 className="h-5 w-5" />,
  day_intro: <Calendar className="h-5 w-5" />,
  photo_spread: <Image className="h-5 w-5" />,
  full_page_photo: <Image className="h-5 w-5" />,
  photo_full: <Image className="h-5 w-5" />,
  trip_summary: <FileText className="h-5 w-5" />,
  map_route: <MapPin className="h-5 w-5" />,
  spotlight: <Star className="h-5 w-5" />,
  itinerary: <Calendar className="h-5 w-5" />,
};

type DayNarrativeSummary = {
  label: string;
  durationLabel: string;
  distanceLabel: string;
};

interface PageDetailModalProps {
  page: BookPage | null;
  pages: BookPage[];
  assets: Asset[];
  bookTitle?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  narrativeSummary?: DayNarrativeSummary;
}

export function PageDetailModal({ 
  page, 
  pages,
  assets, 
  bookTitle, 
  open, 
  onOpenChange,
  narrativeSummary,
}: PageDetailModalProps) {
  if (!page) return null;

  const icon = PAGE_ICONS[page.page_type] || <Image className="h-5 w-5" />;
  const label = PAGE_TYPE_LABELS[page.page_type] || page.page_type;
  const heroId = page.asset_ids?.[0] || page.hero_asset_id || null;
  const heroAsset = heroId ? assets.find((a) => a.id === heroId) : undefined;
  const heroSrc = heroAsset ? (heroAsset.thumbnail_path ? getThumbnailUrl(heroAsset) : getAssetUrl(heroAsset)) : '';
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
          {page.page_type === 'photo_spread' && heroSrc ? (
            <div className="photo-full-inner w-full h-full flex items-center justify-center bg-muted/30 rounded-lg p-4">
              <img src={heroSrc} alt={page.summary || 'Photo spread'} className="photo-full-image max-h-[70vh]" />
            </div>
          ) : page.page_type === 'photo_grid' ? (
            <PhotoGridDetail page={page} assets={assets} />
          ) : (page.page_type === 'photo_full' || page.page_type === 'full_page_photo') && heroSrc ? (
            <div className="photo-full-inner w-full h-full flex items-center justify-center bg-muted/30 rounded-lg p-4">
              <img src={heroSrc} alt="" className="photo-full-image max-h-[70vh]" />
            </div>
          ) : page.page_type === 'day_intro' ? (
            <div className="text-center py-8 space-y-3 bg-muted/30 rounded-lg">
              <div className="flex items-center justify-center gap-3 text-foreground">
                {icon}
                <h2 className="text-2xl font-bold">Page {page.index + 1} – {label}</h2>
              </div>
              <p className="text-muted-foreground text-sm max-w-2xl mx-auto">
                {page.summary}
              </p>
              {narrativeSummary && (
                <p className="text-sm text-slate-700">
                  {narrativeSummary.label}
                  <span className="ml-2 text-xs text-slate-500">
                    {narrativeSummary.durationLabel} · {narrativeSummary.distanceLabel}
                  </span>
                </p>
              )}
            </div>
          ) : (
            <div className="text-center py-12 space-y-4 bg-muted/30 rounded-lg">
              <div className="flex items-center justify-center gap-3 text-foreground">
                {icon}
                <h2 className="text-2xl font-bold">Page {page.index + 1} – {label}</h2>
              </div>
              <p className="text-muted-foreground text-sm max-w-2xl mx-auto">
                {page.summary}
              </p>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function getLayoutVariant(page: BookPage | null): GridLayoutVariant | null {
  return page?.layout_variant ?? null;
}

function PhotoGridDetail({ page, assets }: { page: BookPage; assets: Asset[] }) {
  const rawVariant = getLayoutVariant(page);
  const variant: GridLayoutVariant = rawVariant ?? 'default';
  const gridAssets = (page.asset_ids || [])
    .map((id) => assets.find((a) => a.id === id))
    .filter(Boolean) as Asset[];

  const renderImage = (asset: Asset, extraClass = '') => {
    const src = asset.thumbnail_path ? getThumbnailUrl(asset) : getAssetUrl(asset);
    return (
      <div className={clsx('w-full h-full overflow-hidden rounded-lg bg-muted', extraClass)}>
        <img src={src} alt={asset.metadata?.taken_at || ''} className="w-full h-full object-cover" />
      </div>
    );
  };

  if (gridAssets.length === 0) {
    return (
      <div className="text-center py-12 space-y-4 bg-muted/30 rounded-lg">
        <p className="text-muted-foreground">No photos to display for this grid.</p>
      </div>
    );
  }

  if (variant === 'grid_2up' && gridAssets.length >= 2) {
    return (
      <div className="grid grid-cols-2 gap-2 bg-muted/30 p-3 rounded-lg">
        {gridAssets.slice(0, 2).map((asset) => renderImage(asset))}
      </div>
    );
  }

  if (variant === 'grid_3up_hero' && gridAssets.length >= 3) {
    return (
      <div className="grid grid-cols-2 grid-rows-2 gap-2 bg-muted/30 p-3 rounded-lg min-h-[360px]">
        <div className="row-span-2">{renderImage(gridAssets[0])}</div>
        {renderImage(gridAssets[1])}
        {renderImage(gridAssets[2])}
      </div>
    );
  }

  if (variant === 'grid_6_dense' && gridAssets.length >= 5) {
    const slice = gridAssets.slice(0, 6);
    return (
      <div className="grid grid-cols-3 grid-rows-2 gap-1 bg-muted/30 p-3 rounded-lg">
        {slice.map((asset) => renderImage(asset))}
      </div>
    );
  }

  if (variant === 'grid_4_simple' && gridAssets.length >= 4) {
    return (
      <div className="grid grid-cols-3 grid-rows-2 gap-2 bg-muted/30 p-3 rounded-lg">
        {gridAssets.slice(0, 3).map((asset) => renderImage(asset))}
        <div className="col-span-3">{renderImage(gridAssets[3])}</div>
      </div>
    );
  }

  // Default 4-up (original layout / fallback)
  return (
    <div className="grid grid-cols-2 grid-rows-2 gap-2 bg-muted/30 p-3 rounded-lg min-h-[360px]">
      {gridAssets.slice(0, 4).map((asset) => renderImage(asset))}
    </div>
  );
}

function SpreadDetail({ src, alt }: { src: string; alt?: string }) {
  return null;
}
