import { useCallback, useState } from 'react';
import { Upload, Image } from 'lucide-react';
import { cn } from '@/lib/utils';

interface UploadZoneProps {
  onUpload: (files: FileList) => Promise<void>;
  isUploading?: boolean;
}

export function UploadZone({ onUpload, isUploading }: UploadZoneProps) {
  const [isDragging, setIsDragging] = useState(false);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      if (e.dataTransfer.files.length > 0) {
        await onUpload(e.dataTransfer.files);
      }
    },
    [onUpload]
  );

  const handleFileSelect = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files && e.target.files.length > 0) {
        await onUpload(e.target.files);
        e.target.value = '';
      }
    },
    [onUpload]
  );

  return (
    <label
      className={cn(
        'flex flex-col items-center justify-center w-full h-48 border-2 border-dashed rounded-lg cursor-pointer transition-colors',
        isDragging
          ? 'border-primary bg-primary/5'
          : 'border-border hover:border-primary/50 hover:bg-muted/50',
        isUploading && 'opacity-50 cursor-not-allowed'
      )}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <div className="flex flex-col items-center justify-center pt-5 pb-6">
        {isUploading ? (
          <>
            <div className="h-10 w-10 border-2 border-primary border-t-transparent rounded-full animate-spin mb-3" />
            <p className="text-sm text-muted-foreground">Uploading photos...</p>
          </>
        ) : (
          <>
            <Upload className="h-10 w-10 text-muted-foreground mb-3" />
            <p className="mb-2 text-sm text-foreground">
              <span className="font-medium">Click to upload</span> or drag and drop
            </p>
            <p className="text-xs text-muted-foreground flex items-center gap-1">
              <Image className="h-3 w-3" />
              JPG, PNG, HEIC (max 20MB each)
            </p>
          </>
        )}
      </div>
      <input
        type="file"
        className="hidden"
        accept="image/*"
        multiple
        onChange={handleFileSelect}
        disabled={isUploading}
      />
    </label>
  );
}
