import { useState } from 'react';
import { Check, X, ImageOff } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import type { Asset } from '@/lib/api';
import { getThumbnailUrl } from '@/lib/api';

interface AssetGridProps {
  assets: Asset[];
  onUpdateStatus: (assetId: string, status: 'approved' | 'rejected') => void;
  selectedIds?: Set<string>;
  onSelectionChange?: (ids: Set<string>) => void;
  showActions?: boolean;
}

export function AssetGrid({
  assets,
  onUpdateStatus,
  selectedIds = new Set(),
  onSelectionChange,
  showActions = true,
}: AssetGridProps) {
  const [imageErrors, setImageErrors] = useState<Set<string>>(new Set());

  const handleImageError = (assetId: string) => {
    setImageErrors((prev) => new Set(prev).add(assetId));
  };

  const toggleSelection = (assetId: string) => {
    if (!onSelectionChange) return;
    const newSelection = new Set(selectedIds);
    if (newSelection.has(assetId)) {
      newSelection.delete(assetId);
    } else {
      newSelection.add(assetId);
    }
    onSelectionChange(newSelection);
  };

  if (assets.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
        <ImageOff className="h-12 w-12 mb-4 opacity-50" />
        <p>No photos to display</p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
      {assets.map((asset) => {
        const hasError = imageErrors.has(asset.id);
        const isSelected = selectedIds.has(asset.id);

        return (
          <div
            key={asset.id}
            className={cn(
              'group relative aspect-square rounded-lg overflow-hidden bg-muted border-2 transition-all',
              isSelected ? 'border-primary ring-2 ring-primary/20' : 'border-transparent',
              onSelectionChange && 'cursor-pointer'
            )}
            onClick={() => toggleSelection(asset.id)}
          >
            {hasError ? (
              <div className="absolute inset-0 flex items-center justify-center bg-muted">
                <ImageOff className="h-8 w-8 text-muted-foreground" />
              </div>
            ) : (
              <img
                src={getThumbnailUrl(asset)}
                alt=""
                className="absolute inset-0 w-full h-full object-cover"
                onError={() => handleImageError(asset.id)}
                loading="lazy"
              />
            )}

            {/* Status badge */}
            <div className="absolute top-2 left-2">
              <Badge variant={asset.status as 'imported' | 'approved' | 'rejected'}>
                {asset.status}
              </Badge>
            </div>

            {/* Selection indicator */}
            {isSelected && (
              <div className="absolute top-2 right-2 w-6 h-6 rounded-full bg-primary flex items-center justify-center">
                <Check className="h-4 w-4 text-primary-foreground" />
              </div>
            )}

            {/* Action buttons */}
            {showActions && (
              <div className="absolute inset-x-0 bottom-0 p-2 bg-gradient-to-t from-black/70 to-transparent opacity-0 group-hover:opacity-100 transition-opacity">
                <div className="flex gap-1 justify-center">
                  <Button
                    size="sm"
                    variant={asset.status === 'approved' ? 'default' : 'secondary'}
                    className="h-7 px-2 text-xs"
                    onClick={(e) => {
                      e.stopPropagation();
                      onUpdateStatus(asset.id, 'approved');
                    }}
                  >
                    <Check className="h-3 w-3 mr-1" />
                    Approve
                  </Button>
                  <Button
                    size="sm"
                    variant={asset.status === 'rejected' ? 'destructive' : 'secondary'}
                    className="h-7 px-2 text-xs"
                    onClick={(e) => {
                      e.stopPropagation();
                      onUpdateStatus(asset.id, 'rejected');
                    }}
                  >
                    <X className="h-3 w-3 mr-1" />
                    Reject
                  </Button>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
