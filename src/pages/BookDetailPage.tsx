import { useState, useEffect, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Header } from '@/components/Header';
import { UploadZone } from '@/components/UploadZone';
import { AssetGrid } from '@/components/AssetGrid';
import { PagePreviewCard } from '@/components/PagePreviewCard';
import { PageDetailModal } from '@/components/PageDetailModal';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  ArrowLeft,
  Upload,
  Filter,
  Sparkles,
  Layout,
  Download,
  Loader2,
  Check,
  X,
  Image,
  CheckCheck,
  Eye,
  EyeOff,
} from 'lucide-react';
import {
  booksApi,
  assetsApi,
  pipelineApi,
  getAssetUrl,
  getThumbnailUrl,
  type Book,
  type Asset,
  type PagePreview,
  type AutoHiddenDuplicateCluster,
  type BookSegmentDebugResponse,
  type PhotoQualityMetrics,
} from '@/lib/api';
import { useBookDedupeDebug } from '@/hooks/useBookDedupeDebug';
import { useBookSegmentDebug } from '@/hooks/useBookSegmentDebug';
import { useBookPlacesDebug } from '@/hooks/useBookPlacesDebug';
import { useBookPhotoQuality } from '@/hooks/useBookPhotoQuality';
import { useBookItinerary } from '@/hooks/useBookItinerary';
import { toast } from 'sonner';

export default function BookDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [book, setBook] = useState<Book | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [pages, setPages] = useState<PagePreview[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isUploading, setIsUploading] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [selectedAssets, setSelectedAssets] = useState<Set<string>>(new Set());
  const [selectedPage, setSelectedPage] = useState<PagePreview | null>(null);
  const [isApprovingAll, setIsApprovingAll] = useState(false);
  const [activeTab, setActiveTab] = useState('upload');
  const [previewHtml, setPreviewHtml] = useState<string | null>(null);
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [showClusters, setShowClusters] = useState(false);
  const dedupe = useBookDedupeDebug(id);
  const segments = useBookSegmentDebug(id);
  const {
    data: placesDebug,
    loading: placesLoading,
    error: placesError,
  } = useBookPlacesDebug(id);
  const [placesLocal, setPlacesLocal] = useState<typeof placesDebug | null>(null);
  const [editingStableId, setEditingStableId] = useState<string | null>(null);
  const [editingText, setEditingText] = useState<string>('');
  const itinerary = useBookItinerary(id);
  const [expandedSegmentDays, setExpandedSegmentDays] = useState<Set<number>>(new Set());

  const dayIndexByPageIndex = useMemo(() => {
    const map: Record<number, number> = {};
    let dayCounter = 0;
    pages.forEach((p) => {
      if (p.page_type === 'day_intro') {
        map[p.index] = dayCounter;
        dayCounter += 1;
      }
    });
    return map;
  }, [pages]);

  const daySegmentSummaryByIndex = useMemo(() => {
    if (!segments.data?.days) return {};
    const result: Record<number, { segmentsCount: number; totalDurationMinutes: number; totalDistanceKm: number }> = {};
    for (const day of segments.data.days) {
      const segmentsList = day.segments || [];
      const segmentsCount = segmentsList.length;
      let totalDurationMinutes = 0;
      let totalDistanceKm = 0;
      for (const seg of segmentsList) {
        if (typeof seg.duration_minutes === 'number') {
          totalDurationMinutes += seg.duration_minutes;
        }
        if (typeof seg.approx_distance_km === 'number') {
          totalDistanceKm += seg.approx_distance_km;
        }
      }
      result[day.day_index] = {
        segmentsCount,
        totalDurationMinutes,
        totalDistanceKm,
      };
    }
    return result;
  }, [segments.data]);

  const dayNarrativeByIndex = useMemo(() => {
    if (!segments.data?.days) return {};
    const result: Record<number, DayNarrativeSummary> = {};
    for (const day of segments.data.days) {
      const summary = daySegmentSummaryByIndex[day.day_index];
      if (!summary) continue;
      const photoCount = day.asset_ids?.length ?? 0;
      result[day.day_index] = buildDayNarrative({
        segmentsCount: summary.segmentsCount,
        totalDurationMinutes: summary.totalDurationMinutes,
        totalDistanceKm: summary.totalDistanceKm,
        photoCount,
      });
    }
    return result;
  }, [segments.data, daySegmentSummaryByIndex]);
  const assetsById = useMemo(() => {
    const map: Record<string, Asset> = {};
    assets.forEach((a) => {
      map[a.id] = a;
    });
    return map;
  }, [assets]);

  const buildLocationLines = useMemo(
    () =>
      (day: {
        locations?: { location_short: string | null; location_full: string | null }[];
        stops: { location_short: string | null; location_full: string | null }[];
      }) => {
        const lines: string[] = [];
        const seen = new Set<string>();

        const truncateLabel = (label: string) => {
          const parts = label
            .split(',')
            .map((p) => p.trim())
            .filter(Boolean);
          if (parts.length <= 2) return parts.join(', ');
          return parts.slice(0, 2).join(', ');
        };

        const addLabel = (raw?: string | null) => {
          if (!raw) return;
          const truncated = truncateLabel(raw);
          if (seen.has(truncated)) return;
          seen.add(truncated);
          lines.push(truncated);
        };

        if (day.locations && day.locations.length > 0) {
          day.locations.forEach((loc) => addLabel(loc.location_short || loc.location_full));
          return lines.slice(0, 3);
        }

        (day.stops || []).forEach((stop) => addLabel(stop.location_short || stop.location_full));
        return lines.slice(0, 3);
      },
    []
  );

  const loadBook = async () => {
    if (!id) return;
    try {
      const [bookData, assetsData, pagesData] = await Promise.all([
        booksApi.get(id),
        assetsApi.list(id),
        pipelineApi.getPages(id).catch(() => []),
      ]);
      setBook(bookData);
      setAssets(assetsData);
      setPages(pagesData);
    } catch (error) {
      console.error('Failed to load book:', error);
      toast.error('Failed to load book details');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadBook();
  }, [id]);

  useEffect(() => {
    // Keep a local mutable copy so we can refresh after edits without changing the hook
    setPlacesLocal(placesDebug);
  }, [placesDebug]);

  const refreshPlaces = async () => {
    if (!id) return;
    try {
      const fresh = await booksApi.getPlacesDebug(id);
      setPlacesLocal(fresh);
    } catch (err) {
      console.error('Failed to refresh places', err);
      toast.error('Failed to refresh places');
    }
  };

  const handleSaveOverride = async (stableId: string, customName: string | null, hidden?: boolean) => {
    if (!id) return;
    try {
      const updated = await booksApi.updatePlaceOverride(id, stableId, { customName, hidden });
      // Optimistically update local places list if present
      setPlacesLocal((prev) => {
        if (!prev) return prev;
        return prev.map((p) => (p.stableId === updated.stableId ? updated : p));
      });
      toast.success('Place override saved');
      setEditingStableId(null);
    } catch (err) {
      console.error('Failed to save override', err);
      toast.error('Failed to save place override');
    }
  };

  const handleToggleHidden = async (stableId: string, currentlyHidden: boolean) => {
    // When toggling hidden, don't send a customName (undefined) so we don't accidentally clear it
    await handleSaveOverride(stableId, undefined as unknown as string | null, !currentlyHidden);
  };

  useEffect(() => {
    setPreviewHtml(null);
    setPreviewError(null);
  }, [id]);

  useEffect(() => {
    if (activeTab === 'preview') {
      loadPreviewHtml();
    }
  }, [activeTab, id]);

  const handleUpload = async (files: FileList) => {
    if (!id) return;
    setIsUploading(true);
    try {
      const result = await assetsApi.upload(id, files);
      const newAssets = result.assets;
      setAssets((prev) => [...newAssets, ...prev]);
      if (result.stats.skipped_unsupported > 0) {
        toast.success(
          `Uploaded ${result.stats.uploaded} photo(s). Skipped ${result.stats.skipped_unsupported} GIF/video file(s) (not supported yet).`
        );
      } else {
        toast.success(`Uploaded ${result.stats.uploaded} photo(s)`);
      }
    } catch (error) {
      console.error('Upload failed:', error);
      toast.error('Failed to upload photos');
    } finally {
      setIsUploading(false);
    }
  };

  const handleUpdateStatus = async (assetId: string, status: 'approved' | 'rejected') => {
    if (!id) return;
    try {
      const updated = await assetsApi.updateStatus(id, assetId, status);
      setAssets((prev) => prev.map((a) => (a.id === assetId ? updated : a)));
    } catch (error) {
      console.error('Failed to update status:', error);
      toast.error('Failed to update photo status');
    }
  };

  const handleBulkApprove = async () => {
    if (!id || selectedAssets.size === 0) return;
    try {
      const updated = await assetsApi.bulkUpdateStatus(id, Array.from(selectedAssets), 'approved');
      setAssets((prev) =>
        prev.map((a) => updated.find((u) => u.id === a.id) || a)
      );
      setSelectedAssets(new Set());
      toast.success(`Approved ${updated.length} photo(s)`);
    } catch (error) {
      toast.error('Failed to approve photos');
    }
  };

  const handleBulkReject = async () => {
    if (!id || selectedAssets.size === 0) return;
    try {
      const updated = await assetsApi.bulkUpdateStatus(id, Array.from(selectedAssets), 'rejected');
      setAssets((prev) =>
        prev.map((a) => updated.find((u) => u.id === a.id) || a)
      );
      setSelectedAssets(new Set());
      toast.success(`Rejected ${updated.length} photo(s)`);
    } catch (error) {
      toast.error('Failed to reject photos');
    }
  };

  const handleApproveAllImported = async () => {
    if (!id) return;
    const importedIds = assets
      .filter((a) => a.status === 'imported')
      .map((a) => a.id);
    
    if (importedIds.length === 0) {
      toast.info('No imported photos to approve');
      return;
    }
    
    setIsApprovingAll(true);
    try {
      const updated = await assetsApi.bulkUpdateStatus(id, importedIds, 'approved');
      setAssets((prev) =>
        prev.map((a) => updated.find((u) => u.id === a.id) || a)
      );
      setSelectedAssets(new Set());
      toast.success(`Approved ${updated.length} photo(s)`);
    } catch (error) {
      toast.error('Failed to approve photos');
    } finally {
      setIsApprovingAll(false);
    }
  };

  const handleGenerate = async () => {
    if (!id) return;
    setIsGenerating(true);
    try {
      const result = await pipelineApi.generate(id);
      if (result.success) {
        toast.success(`Book generated! ${result.page_count} pages created.`);
        const pagesData = await pipelineApi.getPages(id);
        setPages(pagesData);
        const bookData = await booksApi.get(id);
        setBook(bookData);
      } else {
        toast.error('Generation failed');
      }
    } catch (error) {
      console.error('Generation failed:', error);
      toast.error('Failed to generate book');
    } finally {
      setIsGenerating(false);
    }
  };

  const handleDownloadPdf = () => {
    if (!id) return;
    window.open(pipelineApi.getPdfUrl(id), '_blank');
  };

  const loadPreviewHtml = async () => {
    if (!id) return;
    setIsPreviewLoading(true);
    setPreviewError(null);
    try {
      const data = await pipelineApi.getPreviewHtml(id);
      setPreviewHtml(data.html);
    } catch (error) {
      console.error('Failed to load preview HTML', error);
      setPreviewError('Failed to load book preview');
    } finally {
      setIsPreviewLoading(false);
    }
  };

  const filteredAssets =
    statusFilter === 'all'
      ? assets
      : assets.filter((a) => a.status === statusFilter);

  const approvedCount = assets.filter((a) => a.status === 'approved').length;
  const importedCount = assets.filter((a) => a.status === 'imported').length;

  if (isLoading) {
    return (
      <div className="min-h-screen bg-background">
        <Header />
        <div className="flex items-center justify-center py-32">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  if (!book) {
    return (
      <div className="min-h-screen bg-background">
        <Header />
        <div className="container mx-auto px-4 py-16 text-center">
          <p className="text-muted-foreground">Book not found</p>
          <Link to="/" className="text-primary hover:underline mt-4 inline-block">
            Back to books
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <Header />

      <main className="container mx-auto px-4 py-6">
        {/* Breadcrumb & Title */}
        <div className="mb-6">
          <Link
            to="/"
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors mb-3"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to books
          </Link>
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-semibold text-foreground">{book.title}</h1>
              <p className="text-muted-foreground mt-1">
                {book.size} • {assets.length} photos • {approvedCount} approved
              </p>
            </div>
          </div>
        </div>

        {/* Tabs */}
        <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
          <TabsList className="grid w-full grid-cols-5 max-w-lg">
            <TabsTrigger value="upload" className="gap-2">
              <Upload className="h-4 w-4" />
              Upload
            </TabsTrigger>
            <TabsTrigger value="curate" className="gap-2">
              <Filter className="h-4 w-4" />
              Curate
            </TabsTrigger>
            <TabsTrigger value="generate" className="gap-2">
              <Sparkles className="h-4 w-4" />
              Generate
            </TabsTrigger>
            <TabsTrigger value="preview" className="gap-2">
              <Layout className="h-4 w-4" />
              Preview
            </TabsTrigger>
            <TabsTrigger value="photos-quality" className="gap-2">
              <Image className="h-4 w-4" />
              Photos (quality debug)
            </TabsTrigger>
          </TabsList>

          {/* Upload Tab */}
          <TabsContent value="upload" className="space-y-6 animate-fade-in">
            <Card>
              <CardHeader>
                <CardTitle>Upload Photos</CardTitle>
                <CardDescription>
                  Add photos to your book. They'll start with "imported" status.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <UploadZone onUpload={handleUpload} isUploading={isUploading} />
              </CardContent>
            </Card>

            {assets.length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle>Recently Added</CardTitle>
                  <CardDescription>
                    {importedCount} photo(s) waiting for curation
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <AssetGrid
                    assets={assets.filter((a) => a.status === 'imported').slice(0, 12)}
                    onUpdateStatus={handleUpdateStatus}
                  />
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* Curate Tab */}
          <TabsContent value="curate" className="space-y-6 animate-fade-in">
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between flex-wrap gap-4">
                  <div>
                    <CardTitle>Curate Photos</CardTitle>
                    <CardDescription>
                      Approve or reject photos. Only approved photos will be included in the book.
                    </CardDescription>
                  </div>
                  <div className="flex items-center gap-2">
                    {importedCount > 0 && (
                      <Button
                        variant="default"
                        size="sm"
                        onClick={handleApproveAllImported}
                        disabled={isApprovingAll}
                      >
                        {isApprovingAll ? (
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        ) : (
                          <CheckCheck className="h-4 w-4 mr-2" />
                        )}
                        Approve all imported ({importedCount})
                      </Button>
                    )}
                    <select
                      value={statusFilter}
                      onChange={(e) => setStatusFilter(e.target.value)}
                      className="h-9 rounded-md border border-input bg-background px-3 text-sm"
                    >
                      <option value="all">All ({assets.length})</option>
                      <option value="imported">Imported ({importedCount})</option>
                      <option value="approved">Approved ({approvedCount})</option>
                      <option value="rejected">
                        Rejected ({assets.filter((a) => a.status === 'rejected').length})
                      </option>
                    </select>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                {selectedAssets.size > 0 && (
                  <div className="flex items-center gap-2 mb-4 p-3 bg-muted rounded-lg">
                    <span className="text-sm text-muted-foreground">
                      {selectedAssets.size} selected
                    </span>
                    <Button size="sm" variant="outline" onClick={handleBulkApprove}>
                      <Check className="h-3 w-3 mr-1" />
                      Approve
                    </Button>
                    <Button size="sm" variant="outline" onClick={handleBulkReject}>
                      <X className="h-3 w-3 mr-1" />
                      Reject
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setSelectedAssets(new Set())}
                    >
                      Clear
                    </Button>
                  </div>
                )}
                <AssetGrid
                  assets={filteredAssets}
                  onUpdateStatus={handleUpdateStatus}
                  selectedIds={selectedAssets}
                  onSelectionChange={setSelectedAssets}
                />
              </CardContent>
            </Card>
          </TabsContent>

          {/* Generate Tab */}
          <TabsContent value="generate" className="space-y-6 animate-fade-in">
            <Card>
              <CardHeader>
                <CardTitle>Generate Book</CardTitle>
                <CardDescription>
                  Run the pipeline to create your photo book from approved photos.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                <div className="grid gap-4 sm:grid-cols-3">
                  <div className="p-4 rounded-lg bg-muted">
                    <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
                      <Image className="h-4 w-4" />
                      Total Photos
                    </div>
                    <div className="text-2xl font-semibold">{assets.length}</div>
                  </div>
                  <div className="p-4 rounded-lg bg-success/10">
                    <div className="flex items-center gap-2 text-sm text-success mb-1">
                      <Check className="h-4 w-4" />
                      Approved
                    </div>
                    <div className="text-2xl font-semibold text-success">{approvedCount}</div>
                  </div>
                  <div className="p-4 rounded-lg bg-muted">
                    <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
                      <Layout className="h-4 w-4" />
                      Pages
                    </div>
                    <div className="text-2xl font-semibold">{pages.length || '—'}</div>
                  </div>
                </div>

                {approvedCount === 0 ? (
                  <div className="text-center py-8">
                    <p className="text-muted-foreground">
                      No approved photos yet. Go to the Curate tab to approve some photos first.
                    </p>
                  </div>
                ) : (
                  <div className="flex items-center gap-4">
                    <Button
                      size="lg"
                      onClick={handleGenerate}
                      disabled={isGenerating || approvedCount === 0}
                    >
                      {isGenerating ? (
                        <>
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          Generating...
                        </>
                      ) : (
                        <>
                          <Sparkles className="h-4 w-4 mr-2" />
                          Generate Book
                        </>
                      )}
                    </Button>
                    {book.last_generated && (
                      <span className="text-sm text-muted-foreground">
                        Last generated:{' '}
                        {new Date(book.last_generated).toLocaleString()}
                      </span>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-start justify-between">
                <div>
                  <CardTitle>Places (debug)</CardTitle>
                  <CardDescription>Aggregated local stop candidates.</CardDescription>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {placesLoading && <p className="text-sm text-muted-foreground">Loading places…</p>}
                {placesError && (
                  <p className="text-sm text-destructive">Failed to load places debug.</p>
                )}
                {!placesLoading && !placesError && placesDebug && placesDebug.length === 0 && (
                  <p className="text-sm text-muted-foreground">No place candidates.</p>
                )}
                {!placesLoading && !placesError && (placesLocal ?? placesDebug) && (placesLocal ?? placesDebug)!.length > 0 && (
                  (() => {
                    const places = (placesLocal ?? placesDebug) || [];
                    return (
                      <ul className="text-sm text-foreground space-y-1">
                        {places.map((p, idx) => {
                          const key = p.stableId || String(idx);
                          const placeName = p.overrideName ?? p.displayName ?? p.rawName ?? p.bestPlaceName;
                          const shortName = placeName && placeName.length > 50 ? `${placeName.slice(0, 47).trimEnd()}…` : placeName;
                          const isEditing = editingStableId === p.stableId;
                          return (
                            <li key={key} className="flex flex-col rounded border bg-muted/40 px-2 py-1">
                              <div className="flex items-start justify-between gap-2">
                                <div className="flex items-center gap-2">
                                  <span className="font-mono text-foreground">{idx + 1}.</span>
                                  {isEditing ? (
                                    <input
                                      value={editingText}
                                      onChange={(e) => setEditingText(e.target.value)}
                                      className="text-sm font-semibold text-foreground bg-background border rounded px-2 py-1"
                                      onKeyDown={(e) => {
                                        if (e.key === 'Enter') {
                                          e.preventDefault();
                                          handleSaveOverride(p.stableId, editingText || null);
                                        } else if (e.key === 'Escape') {
                                          setEditingStableId(null);
                                        }
                                      }}
                                    />
                                  ) : (
                                    <button
                                      type="button"
                                      onClick={() => {
                                        setEditingStableId(p.stableId);
                                        setEditingText(p.overrideName ?? p.displayName ?? p.rawName ?? '');
                                      }}
                                      className="text-sm font-semibold text-foreground text-left"
                                    >
                                      {shortName}
                                    </button>
                                  )}
                                  {p.overrideName ? (
                                    <Badge variant="secondary">Edited</Badge>
                                  ) : null}
                                  {p.hidden ? (
                                    <span className="text-xs text-muted-foreground ml-2">(hidden)</span>
                                  ) : null}
                                </div>
                                <div className="flex items-center gap-2">
                                  {isEditing ? (
                                    <>
                                      <Button size="xs" onClick={() => handleSaveOverride(p.stableId, editingText || null)}>
                                        Save
                                      </Button>
                                      <Button size="xs" variant="ghost" onClick={() => setEditingStableId(null)}>
                                        Cancel
                                      </Button>
                                    </>
                                  ) : (
                                    <>
                                      <button
                                        type="button"
                                        title={p.hidden ? 'Unhide place' : 'Hide place'}
                                        onClick={() => handleToggleHidden(p.stableId, p.hidden)}
                                        className="p-1 rounded hover:bg-muted/60"
                                      >
                                        {p.hidden ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                                      </button>
                                    </>
                                  )}
                                </div>
                              </div>

                              <div className="flex items-center justify-between text-xs text-muted-foreground mt-1">
                                <span>
                                  {p.visitCount} visits • {p.totalPhotos} photos • {p.totalDurationHours.toFixed(1)} h • {' '}
                                  {p.totalDistanceKm.toFixed(1)} km
                                </span>
                              </div>
                              <div className="text-xs text-muted-foreground">
                                days [{p.dayIndices.join(', ')}] • ({p.centerLat.toFixed(4)}, {p.centerLon.toFixed(4)})
                              </div>
                              {p.thumbnails && p.thumbnails.length > 0 && (
                                <div className="mt-1 flex flex-wrap gap-1">
                                  {p.thumbnails.map((t) =>
                                    t.thumbUrl ? (
                                      <img
                                        key={t.id}
                                        src={t.thumbUrl}
                                        alt=""
                                        className="h-12 w-12 object-cover rounded-sm border"
                                      />
                                    ) : null
                                  )}
                                </div>
                              )}
                            </li>
                          );
                        })}
                      </ul>
                    );
                  })()
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-start justify-between">
                <div>
                  <CardTitle>Curation report (beta)</CardTitle>
                  <CardDescription>Read-only dedupe/debug info from the planner.</CardDescription>
                </div>
              </CardHeader>
              <CardContent>
                {dedupe.loading && <p className="text-sm text-muted-foreground">Loading curation info…</p>}
                {dedupe.error && (
                  <p className="text-sm text-destructive">Curation info unavailable: {dedupe.error}</p>
                )}
                {!dedupe.loading && !dedupe.error && dedupe.data && (
                  <div className="space-y-4">
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                      <Stat label="Approved" value={dedupe.data.approved_count} />
                      <Stat label="Used in book" value={dedupe.data.used_count} />
                      <Stat label="Auto-hidden assets" value={dedupe.data.auto_hidden_hidden_assets_count} />
                      <Stat label="Clusters" value={dedupe.data.auto_hidden_clusters_count} />
                    </div>
                    <ClusterList
                      clusters={dedupe.data.auto_hidden_duplicate_clusters}
                      show={showClusters}
                      onToggle={() => setShowClusters((v) => !v)}
                      assetMap={assetsById}
                    />
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-start justify-between">
                <div>
                  <CardTitle>Segments (debug)</CardTitle>
                  <CardDescription>Read-only per-day segments (time/distance splits).</CardDescription>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {segments.loading && <p className="text-sm text-muted-foreground">Loading segments…</p>}
                {segments.error && (
                  <p className="text-sm text-destructive">Segments unavailable: {segments.error}</p>
                )}
                {!segments.loading && !segments.error && segments.data && (
                  <div className="space-y-3">
                    <div className="text-sm text-muted-foreground">
                      {segments.data.total_days} days · {segments.data.total_assets} assets
                    </div>
                    <div className="space-y-2">
                      {segments.data.days.map((day) => {
                        const expanded = expandedSegmentDays.has(day.day_index);
                        const toggle = () => {
                          setExpandedSegmentDays((prev) => {
                            const next = new Set(prev);
                            if (next.has(day.day_index)) {
                              next.delete(day.day_index);
                            } else {
                              next.add(day.day_index);
                            }
                            return next;
                          });
                        };
                        return (
                          <div key={day.day_index} className="border rounded-md p-3 bg-muted/40">
                            <button
                              type="button"
                              onClick={toggle}
                              className="w-full text-left flex items-center justify-between"
                            >
                              <div className="text-sm font-medium text-foreground">
                                Day {day.day_index} — {day.date || 'Unknown date'}
                              </div>
                              <div className="text-xs text-muted-foreground">
                                {day.asset_ids.length} assets · {day.segments.length} segments
                              </div>
                            </button>
                            {expanded && (
                              <div className="mt-2 space-y-2">
                                {day.segments.map((seg) => (
                                  <div
                                    key={seg.segment_index}
                                    className="border rounded-md p-2 bg-background text-sm flex flex-col gap-1"
                                  >
                                    <div className="flex items-center justify-between">
                                      <span className="font-medium">Segment {seg.segment_index}</span>
                                      <span className="text-xs text-muted-foreground">
                                        {seg.asset_ids.length} assets
                                      </span>
                                    </div>
                                    <div className="text-xs text-muted-foreground flex gap-2 flex-wrap">
                                      <span>
                                        {formatTimeRange(seg.start_taken_at, seg.end_taken_at)}
                                      </span>
                                      <span>· {formatDuration(seg.duration_minutes)}</span>
                                      <span>· {formatDistance(seg.approx_distance_km)}</span>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-start justify-between">
                <div>
                  <CardTitle>Itinerary (beta)</CardTitle>
                  <CardDescription>Simple day-by-day stops derived from segments.</CardDescription>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {itinerary.loading && <p className="text-sm text-muted-foreground">Loading itinerary…</p>}
                {itinerary.error && (
                  <p className="text-sm text-destructive">Couldn’t load itinerary right now.</p>
                )}
                {!itinerary.loading && !itinerary.error && itinerary.data && (
                  <>
                    {(!itinerary.data.days || itinerary.data.days.length === 0) && (
                      <p className="text-sm text-muted-foreground">No itinerary available for this book yet.</p>
                    )}
                    {itinerary.data.days && itinerary.data.days.length > 0 && (
                      <div className="space-y-2">
                        {itinerary.data.days.map((day) => (
                          <div key={day.day_index} className="rounded-md border bg-muted/40 p-3">
                            <div className="flex items-center justify-between">
                              <div className="text-sm font-medium text-foreground">
                                Day {day.day_index} —{' '}
                                {day.date_iso ? new Date(day.date_iso).toLocaleDateString() : 'Unknown date'}
                              </div>
                              <div className="text-xs text-muted-foreground">
                                {formatItinerarySummary(day)}
                              </div>
                            </div>
                            {(() => {
                              const lines = buildLocationLines(day);
                              if (!lines.length) return null;
                              return (
                                <div className="mt-2 text-sm text-muted-foreground space-y-0.5">
                                  {lines.map((line) => (
                                    <div key={line}>{line}</div>
                                  ))}
                                </div>
                              );
                            })()}

                            {day.stops && day.stops.length > 0 && (
                              <div className="mt-3 space-y-1">
                                {day.stops.map((stop) => {
                                  const label =
                                    stop.location_short || stop.location_full || `Segment ${stop.segment_index}`;
                                  const pillText =
                                    stop.kind === 'travel'
                                      ? 'Travel segment'
                                      : stop.kind === 'local'
                                      ? 'Local exploring'
                                      : null;
                                  return (
                                    <div
                                      key={`${day.day_index}-${stop.segment_index}`}
                                      className="flex flex-col gap-1 rounded-md border bg-background/70 px-2 py-1 text-xs text-muted-foreground"
                                    >
                                      <div className="flex items-center justify-between gap-2">
                                        <div className="flex items-center gap-2">
                                          <span className="text-foreground font-medium">{label}</span>
                                          {pillText && (
                                            <span className="rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                                              {pillText}
                                            </span>
                                          )}
                                        </div>
                                        <div className="flex items-center gap-2">
                                          {typeof stop.distance_km === 'number' && (
                                            <span>~{stop.distance_km.toFixed(1)} km</span>
                                          )}
                                          {typeof stop.duration_hours === 'number' && (
                                            <span>{stop.duration_hours.toFixed(1)} h</span>
                                          )}
                                        </div>
                                      </div>
                                    </div>
                                  );
                                })}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* Preview Tab */}
          <TabsContent value="preview" className="space-y-6 animate-fade-in">
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle>Live Preview</CardTitle>
                    <CardDescription>Rendered book HTML, same as the PDF output.</CardDescription>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button variant="outline" size="sm" onClick={loadPreviewHtml} disabled={isPreviewLoading}>
                      {isPreviewLoading ? (
                        <>
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                          Loading...
                        </>
                      ) : (
                        'Refresh'
                      )}
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                {isPreviewLoading ? (
                  <div className="flex items-center justify-center py-12 text-muted-foreground">
                    <Loader2 className="h-5 w-5 animate-spin mr-2" />
                    Loading preview...
                  </div>
                ) : previewError ? (
                  <div className="text-sm text-destructive">{previewError}</div>
                ) : previewHtml ? (
                  <div className="mt-2 rounded-md overflow-hidden bg-muted/60 p-4">
                    <div className="w-full h-[70vh] overflow-auto flex justify-center">
                      <div className="min-w-[60%] max-w-4xl w-full">
                        <iframe
                          title="Book preview"
                          srcDoc={previewHtml}
                          className="w-full h-full border rounded-lg bg-background shadow-lg"
                          style={{ minHeight: '100%' }}
                        />
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="text-sm text-muted-foreground">
                    Generate the book first to see a live preview.
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle>Book Preview</CardTitle>
                    <CardDescription>
                      Click a page to see details. Download the PDF for the final output.
                    </CardDescription>
                  </div>
                  {book.pdf_path && (
                    <Button onClick={handleDownloadPdf}>
                      <Download className="h-4 w-4 mr-2" />
                      Download PDF
                    </Button>
                  )}
                </div>
              </CardHeader>
              <CardContent>
                {pages.length === 0 ? (
                  <div className="text-center py-12">
                    <Layout className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
                    <p className="text-muted-foreground">
                      No pages generated yet. Go to the Generate tab to create your book.
                    </p>
                  </div>
                ) : (
                  <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
                    {pages.map((page) => (
                      <PagePreviewCard
                        key={page.index}
                        page={page}
                        assets={assets}
                        bookTitle={book.title}
                        onClick={() => setSelectedPage(page)}
                        segmentSummary={
                          page.page_type === 'day_intro'
                            ? daySegmentSummaryByIndex[dayIndexByPageIndex[page.index]]
                            : undefined
                        }
                        dayNarrativeSummary={
                          page.page_type === 'day_intro'
                            ? dayNarrativeByIndex[dayIndexByPageIndex[page.index]]
                            : undefined
                        }
                      />
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>
          <TabsContent value="photos-quality" className="space-y-6 animate-fade-in">
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>Photos (quality debug)</CardTitle>
                  <CardDescription>Per-photo heuristic quality metrics (debug-only).</CardDescription>
                </div>
              </CardHeader>
              <CardContent>
                <PhotosQualityDebugPanel bookId={id ?? ''} />
              </CardContent>
            </Card>
          </TabsContent>

          {/* Page Detail Modal */}
          <PageDetailModal
            page={selectedPage}
            pages={pages}
            assets={assets}
            bookTitle={book.title}
            open={!!selectedPage}
            onOpenChange={(open) => !open && setSelectedPage(null)}
            narrativeSummary={
              selectedPage && selectedPage.page_type === 'day_intro'
                ? dayNarrativeByIndex[dayIndexByPageIndex[selectedPage.index]]
                : undefined
            }
          />
        </Tabs>
      </main>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="p-3 rounded-md bg-muted/60">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="font-semibold text-foreground">{value}</div>
    </div>
  );
}

function ClusterList({
  clusters,
  show,
  onToggle,
  assetMap,
}: {
  clusters: AutoHiddenDuplicateCluster[];
  show: boolean;
  onToggle: () => void;
  assetMap: Record<string, Asset>;
}) {
  if (!clusters || clusters.length === 0) {
    return <p className="text-sm text-muted-foreground">No duplicate clusters detected.</p>;
  }
  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={onToggle}
        className="text-sm text-primary hover:underline"
      >
        {show ? 'Hide clusters' : `Show clusters (${clusters.length})`}
      </button>
      {show && (
        <div className="max-h-64 overflow-auto space-y-2 rounded-md border border-muted-foreground/10 p-2 bg-muted/40">
          {clusters.map((cluster) => (
            <div key={cluster.cluster_id} className="rounded-md border border-muted-foreground/20 bg-background p-2 space-y-2">
              <div className="text-xs font-semibold text-muted-foreground">Cluster: {cluster.cluster_id}</div>
              <div className="text-xs font-medium">Kept</div>
              <div className="flex flex-wrap gap-2">
                {assetMap[cluster.kept_asset_id] ? (
                  <AssetThumb asset={assetMap[cluster.kept_asset_id]} />
                ) : (
                  <div className="text-[10px] text-muted-foreground">Missing asset {cluster.kept_asset_id}</div>
                )}
              </div>
              <div className="text-xs font-medium">
                Hidden ({cluster.hidden_asset_ids.length})
              </div>
              <div className="flex flex-wrap gap-2">
                {cluster.hidden_asset_ids.map((hid) =>
                  assetMap[hid] ? (
                    <AssetThumb key={hid} asset={assetMap[hid]} />
                  ) : (
                    <div key={hid} className="text-[10px] text-muted-foreground">
                      Missing {hid}
                    </div>
                  )
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AssetThumb({ asset }: { asset: Asset }) {
  const src = asset.thumbnail_path ? getThumbnailUrl(asset) : getAssetUrl(asset);
  return (
    <img
      src={src}
      alt=""
      className="h-16 w-16 rounded-md object-cover border border-muted-foreground/20 bg-muted"
      loading="lazy"
    />
  );
}

function PhotosQualityDebugPanel({ bookId }: { bookId: string }) {
  const { data, loading, error } = useBookPhotoQuality(bookId || undefined);

  if (loading) return <div className="text-sm text-muted-foreground">Loading quality metrics…</div>;
  if (error) return <div className="text-sm text-destructive">Failed to load photo quality metrics.</div>;
  if (!data || data.length === 0) return <div className="text-sm text-muted-foreground">No photos found for this book.</div>;

  const sorted = [...data].sort((a, b) => a.quality_score - b.quality_score);

  return (
    <div className="space-y-2">
      <div className="text-xs text-muted-foreground">
        Debug-only view of per-photo quality metrics. Thresholds/flags are heuristic and not used for planning yet.
      </div>
      <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-3">
        {sorted.map((m) => (
          <div key={m.photo_id} className="flex gap-2 rounded border p-2 items-start">
            <img
              src={m.thumbnail_url ?? ''}
              alt=""
              className="h-16 w-16 flex-shrink-0 rounded object-cover bg-muted"
            />
            <div className="space-y-1 text-xs">
              <div className="font-medium truncate">{m.file_path}</div>
              <div className="flex flex-wrap gap-1">
                <span>Q: {m.quality_score.toFixed(3)}</span>
                <span>Blur: {m.blur_score.toFixed(2)}</span>
                <span>Bright: {m.brightness.toFixed(2)}</span>
                <span>Contr: {m.contrast.toFixed(2)}</span>
                <span>Edges: {m.edge_density.toFixed(2)}</span>
              </div>
              {m.flags && m.flags.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {m.flags.map((flag) => (
                    <span
                      key={flag}
                      className="rounded bg-amber-100 px-1 py-0.5 text-[10px] font-medium text-amber-900"
                    >
                      {flag}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function formatTimeRange(start?: string | null, end?: string | null) {
  if (!start && !end) return 'Time: —';
  const opts: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit' };
  const startStr = start ? new Date(start).toLocaleTimeString([], opts) : '—';
  const endStr = end ? new Date(end).toLocaleTimeString([], opts) : '—';
  return `${startStr}–${endStr}`;
}

function formatDuration(mins?: number | null) {
  if (mins === null || mins === undefined) return 'Duration: —';
  if (mins >= 60) {
    return `Duration: ${(mins / 60).toFixed(1)} h`;
  }
  return `Duration: ${Math.round(mins)} min`;
}

function formatDistance(km?: number | null) {
  if (km === null || km === undefined) return 'Distance: —';
  return `Distance: ~${km.toFixed(1)} km`;
}

function isReasonableDayDistanceKm(totalKm?: number | null, totalHours?: number | null) {
  if (!totalKm || totalKm <= 0) return false;
  if (totalKm <= 300) return true;
  const hours = totalHours && totalHours > 0 ? totalHours : 0;
  if (!hours) return false;
  const avgSpeed = totalKm / hours;
  return avgSpeed <= 150;
}

function formatItinerarySummary(day: {
  photos_count: number;
  stops: unknown[];
  segments_total_distance_km?: number;
  segments_total_duration_hours?: number;
}) {
  const parts: string[] = [];
  parts.push(`${day.photos_count} photo${day.photos_count === 1 ? '' : 's'}`);
  parts.push(`${day.stops?.length || 0} segment${(day.stops?.length || 0) === 1 ? '' : 's'}`);
  const km = typeof day.segments_total_distance_km === 'number' ? day.segments_total_distance_km : null;
  const hours =
    typeof day.segments_total_duration_hours === 'number' ? day.segments_total_duration_hours : null;
  if (km && isReasonableDayDistanceKm(km, hours)) {
    parts.push(`~${km.toFixed(1)} km`);
  }
  if (hours && hours > 0) {
    parts.push(`${hours.toFixed(1)} h`);
  }
  return parts.join(' • ');
}

type DayStats = {
  segmentsCount: number;
  totalDurationMinutes: number;
  totalDistanceKm: number;
  photoCount: number;
};

type DayNarrativeSummary = {
  label: string;
  durationLabel: string;
  distanceLabel: string;
};

function buildDayNarrative(stats: DayStats): DayNarrativeSummary {
  const hours = stats.totalDurationMinutes / 60;
  const far = stats.totalDistanceKm >= 100;
  const mediumDistance = stats.totalDistanceKm >= 10 && stats.totalDistanceKm < 100;
  const longDay = hours >= 8;
  const shortDay = hours < 3;

  let label = 'Easygoing day';
  if (far) {
    label = 'Big travel day';
  } else if (longDay && mediumDistance) {
    label = 'Full-day exploring';
  } else if (shortDay && stats.totalDistanceKm < 5) {
    label = 'Chill day nearby';
  } else if (longDay) {
    label = 'Long day out';
  } else if (mediumDistance) {
    label = 'Out and about';
  }

  const durationLabel = `${hours.toFixed(1)} h out and about`;
  const distanceLabel = `~${stats.totalDistanceKm.toFixed(1)} km traveled`;
  return { label, durationLabel, distanceLabel };
}

function formatSegmentsLine(summary?: { segmentsCount: number; totalDurationMinutes: number; totalDistanceKm: number | null }) {
  if (!summary || summary.segmentsCount <= 0) return '';
  const parts: string[] = [];
  parts.push(`${summary.segmentsCount} ${summary.segmentsCount === 1 ? 'segment' : 'segments'}`);
  if (summary.totalDurationMinutes > 0) {
    parts.push(formatDuration(summary.totalDurationMinutes).replace('Duration: ', ''));
  }
  if (summary.totalDistanceKm != null && summary.totalDistanceKm > 0.1) {
    parts.push(`~${summary.totalDistanceKm.toFixed(1)} km`);
  }
  return parts.join(' • ');
}
