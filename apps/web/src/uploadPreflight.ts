import { ApiError } from './api';
import type { components } from './api.generated';
export type UploadPolicy = components['schemas']['UploadPolicy'];

export async function preflight(file: File, policy: UploadPolicy): Promise<void> {
  if (!file.size) throw new ApiError('视频为空，请重新选择');
  if (file.size > policy.max_upload_bytes)
    throw new ApiError(`视频须小于 ${Math.floor(policy.max_upload_bytes / 1_000_000)} MB`);
  // Read metadata from local slices, independent of browser HEVC decoding support.
  const { Input, BlobSource, MP4, QTFF } = await import('mediabunny');
  const input = new Input({
    formats: [MP4, QTFF],
    source: new BlobSource(file, { maxCacheSize: 2 * 1024 * 1024, useStreamReader: false }),
  });
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([
      (async () => {
        const videos = await input.getVideoTracks();
        const audio = await input.getAudioTracks();
        if (videos.length !== 1) throw new ApiError('请选择单画面的 MP4 或 MOV 视频');
        const track = videos[0];
        const codec = await track.getCodec();
        if (!codec || !policy.video_codecs.includes(codec))
          throw new ApiError('支持 MP4 / MOV 的 H.264 或 HEVC 视频');
        if (audio.length > 1) throw new ApiError('暂不支持多音轨视频');
        for (const sound of audio) {
          const codec = await sound.getCodec();
          if (!codec || !policy.audio_codecs.includes(codec))
            throw new ApiError('暂不支持此视频的音轨格式');
        }
        const duration = (await input.getDurationFromMetadata()) ?? (await input.computeDuration());
        if (!duration || !Number.isFinite(duration) || duration > policy.max_duration_seconds)
          throw new ApiError(
            `视频时长须在 ${Math.floor(policy.max_duration_seconds / 60)} 分钟以内`,
          );
        const width = await track.getDisplayWidth(),
          height = await track.getDisplayHeight();
        if (
          Math.min(width, height) <= 0 ||
          Math.max(width, height) > 4096 ||
          width * height > policy.max_pixels
        )
          throw new ApiError('视频分辨率须在 4K 以内');
      })(),
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new ApiError('无法读取视频，请重新选择完整文件')), 10000);
      }),
    ]);
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError('无法读取视频，请选择完整的 MP4 或 MOV 文件');
  } finally {
    clearTimeout(timer);
    input.dispose();
  }
}
