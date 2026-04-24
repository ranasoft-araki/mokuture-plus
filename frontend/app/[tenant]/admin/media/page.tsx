"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, type MediaItem, type MediaUploadUrlResponse } from "@/lib/api";
import { clearTokens, getAccessToken } from "@/lib/auth";

export default function AdminMediaPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();

  const [media, setMedia] = useState<MediaItem[]>([]);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const loadMedia = useCallback(async (token: string) => {
    setLoading(true);
    setError("");
    try {
      const items = await api.listMedia(token);
      setMedia(items);
    } catch {
      clearTokens();
      router.push("/login");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      router.push("/login");
      return;
    }

    void loadMedia(token);
  }, [loadMedia, router]);

  const stats = useMemo(() => {
    const images = media.filter((item) => item.mime_type.startsWith("image/")).length;
    const videos = media.filter((item) => item.mime_type.startsWith("video/")).length;
    const totalBytes = media.reduce((sum, item) => sum + item.size_bytes, 0);
    return { images, videos, totalBytes };
  }, [media]);

  async function handleUpload() {
    const token = getAccessToken();
    if (!token) {
      router.push("/login");
      return;
    }
    if (!selectedFile) {
      setError("アップロードするファイルを選択してください");
      return;
    }

    setUploading(true);
    setError("");
    setSuccess("");

    try {
      const uploadInfo = await api.getMediaUploadUrl(token, selectedFile.name, selectedFile.type);
      await uploadToStorage(uploadInfo, selectedFile);

      const created = await api.registerMedia(token, {
        media_id: uploadInfo.media_id,
        filename: selectedFile.name,
        mime_type: selectedFile.type,
        url: uploadInfo.public_url,
        size_bytes: selectedFile.size,
        duration_sec: null,
      });

      setMedia((current) => [created, ...current]);
      setSelectedFile(null);
      setSuccess("メディアをアップロードしました");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "アップロードに失敗しました");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#f5f2ed]">
      <div className="bg-white border-b border-[#e2ddd6] px-6 py-4 flex items-center gap-3">
        <button onClick={() => router.push(`/${params.tenant}/admin`)} className="text-[#8a8070] hover:text-[#1d1a15]">
          ← ダッシュボード
        </button>
        <span className="text-[#c8c0b0]">/</span>
        <span className="text-[#5a5347] font-medium">メディア管理</span>
      </div>

      <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <StatCard label="登録メディア" value={`${media.length}件`} />
          <StatCard label="画像" value={`${stats.images}件`} />
          <StatCard label="合計サイズ" value={formatBytes(stats.totalBytes)} />
        </div>

        <div className="bg-white rounded-xl border border-[#e2ddd6] p-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="font-medium text-[#1d1a15]">アップロード</h1>
              <p className="text-sm text-[#8a8070] mt-1">画像・動画を追加して、キオスク表示に利用できます。</p>
            </div>
            <div className="shrink-0 px-3 py-1 rounded-full bg-[#e8f0e9] text-[#4a7c4e] text-sm">
              動画 {stats.videos}件
            </div>
          </div>

          <div className="mt-6 grid grid-cols-1 md:grid-cols-[1fr_auto] gap-4 items-end">
            <div className="space-y-2">
              <label className="text-sm font-medium text-[#1d1a15]">ファイルを選択</label>
              <input
                key={selectedFile?.name ?? "empty"}
                type="file"
                accept="image/*,video/*"
                onChange={(event) => {
                  setSelectedFile(event.target.files?.[0] ?? null);
                  setError("");
                  setSuccess("");
                }}
                className="block w-full text-sm text-[#5a5347] file:mr-4 file:rounded-lg file:border-0 file:bg-[#f0ece6] file:px-4 file:py-2 file:text-sm file:font-medium file:text-[#5a5347] hover:file:bg-[#e6e0d8]"
              />
              <p className="text-xs text-[#8a8070]">
                対応形式: JPEG / PNG / SVG / MP4
                {selectedFile ? ` ・ 選択中: ${selectedFile.name} (${formatBytes(selectedFile.size)})` : ""}
              </p>
            </div>

            <button
              onClick={handleUpload}
              disabled={uploading || !selectedFile}
              className="bg-[#4a7c4e] text-white px-5 py-3 rounded-lg font-medium disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {uploading ? "アップロード中…" : "アップロード"}
            </button>
          </div>

          {error ? <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}
          {success ? <div className="mt-4 rounded-lg border border-[#cfe0d0] bg-[#f4faf4] px-4 py-3 text-sm text-[#4a7c4e]">{success}</div> : null}
        </div>

        <div className="bg-white rounded-xl border border-[#e2ddd6] overflow-hidden">
          <div className="px-6 py-4 border-b border-[#e2ddd6] flex items-center justify-between">
            <h2 className="font-medium text-[#1d1a15]">メディア一覧</h2>
            <span className="text-sm text-[#8a8070]">{media.length}件</span>
          </div>

          {loading ? (
            <div className="px-6 py-8 text-center text-[#8a8070]">読み込み中…</div>
          ) : media.length === 0 ? (
            <div className="px-6 py-8 text-center text-[#8a8070]">まだメディアが登録されていません</div>
          ) : (
            <div className="divide-y divide-[#f0ece6]">
              {media.map((item) => (
                <div key={item.id} className="px-6 py-4 flex flex-col md:flex-row md:items-center gap-4">
                  <MediaPreview item={item} />
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-[#1d1a15] truncate">{item.filename}</p>
                    <div className="flex flex-wrap items-center gap-2 mt-2 text-xs">
                      <span className={`px-2 py-1 rounded-full ${item.mime_type.startsWith("video/") ? "bg-[#e8f0f5] text-[#2e6b8e]" : "bg-[#e8f0e9] text-[#4a7c4e]"}`}>
                        {item.mime_type.startsWith("video/") ? "動画" : "画像"}
                      </span>
                      <span className="px-2 py-1 rounded-full bg-[#f0ece6] text-[#5a5347]">{item.mime_type}</span>
                    </div>
                  </div>
                  <div className="text-sm text-[#8a8070] md:text-right shrink-0">
                    <p>{formatBytes(item.size_bytes)}</p>
                    <p className="mt-1">{formatDate(item.uploaded_at)}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white rounded-xl border border-[#e2ddd6] px-5 py-4">
      <p className="text-sm text-[#8a8070]">{label}</p>
      <p className="text-2xl font-semibold mt-1 text-[#4a7c4e]">{value}</p>
    </div>
  );
}

function MediaPreview({ item }: { item: MediaItem }) {
  if (item.mime_type.startsWith("video/")) {
    return (
      <div className="w-full md:w-40 aspect-video rounded-lg overflow-hidden bg-[#1d1a15] shrink-0">
        <video src={item.url} className="w-full h-full object-cover" muted playsInline />
      </div>
    );
  }

  return (
    <div className="w-full md:w-40 aspect-video rounded-lg overflow-hidden bg-[#f0ece6] shrink-0">
      <img src={item.url} alt={item.filename} className="w-full h-full object-cover" />
    </div>
  );
}

async function uploadToStorage(uploadInfo: MediaUploadUrlResponse, file: File) {
  if (Object.keys(uploadInfo.upload.fields).length > 0) {
    const formData = new FormData();
    for (const [key, value] of Object.entries(uploadInfo.upload.fields)) {
      formData.append(key, value);
    }
    formData.append("file", file);

    const response = await fetch(uploadInfo.upload.url, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      throw new Error("ストレージへのアップロードに失敗しました");
    }
    return;
  }

  const response = await fetch(uploadInfo.upload.url, {
    method: "PUT",
    headers: {
      "Content-Type": file.type,
    },
    body: file,
  });

  if (!response.ok) {
    throw new Error("ストレージへのアップロードに失敗しました");
  }
}

function formatBytes(bytes: number) {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** index;
  return `${value >= 100 ? Math.round(value) : value.toFixed(value >= 10 ? 1 : 2)} ${units[index]}`;
}

function formatDate(value: string) {
  if (!value) return "日時不明";
  return new Date(value).toLocaleString("ja-JP", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
