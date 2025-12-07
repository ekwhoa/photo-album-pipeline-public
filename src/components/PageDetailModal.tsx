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
import { getAssetUrl, getThumbnailUrl } from '@/lib/api';

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
  const heroId = page.asset_ids?.[0] || page.hero_asset_id || null;
  const heroAsset = heroId ? assets.find((a) => a.id === heroId) : undefined;
  const heroSrc = heroAsset ? (heroAsset.thumbnail_path ? getThumbnailUrl(heroAsset) : getAssetUrl(heroAsset)) : '';
  const spreadSlot = (page as any).spread_slot || (page as any).spreadSlot;

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
          {page.page_type === 'photo_spread' && heroSrc && spreadSlot ? (
            <div className="spread-frame w-full">
              <img src={heroSrc} alt="" className={spreadSlot === 'left' ? 'spread-img spread-img-left' : 'spread-img spread-img-right'} />
            </div>
          ) : (page.page_type === 'photo_full' || page.page_type === 'full_page_photo') && heroSrc ? (
            <div className="photo-full-inner w-full h-full flex items-center justify-center bg-muted/30 rounded-lg p-4">
              <img src={heroSrc} alt="" className="photo-full-image max-h-[70vh]" />
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
