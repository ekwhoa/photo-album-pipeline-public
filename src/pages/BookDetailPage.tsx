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
} from '@/lib/api';
import { useBookDedupeDebug } from '@/hooks/useBookDedupeDebug';
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
  const assetsById = useMemo(() => {
    const map: Record<string, Asset> = {};
    assets.forEach((a) => {
      map[a.id] = a;
    });
    return map;
  }, [assets]);

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
          <TabsList className="grid w-full grid-cols-4 max-w-lg">
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
                      />
                    ))}
                  </div>
                )}
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
