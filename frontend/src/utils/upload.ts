/**
 * 文件上传工具（P1-2/P1-3，design §2.5.4 OBS直传 + spec §5.2.1规则5 图片压缩）：
 * - presign 获取上传凭证 → OBS 模式直传 PUT / 本地回退模式 multipart 代存
 * - 图片上传前 Canvas 压缩（长边上限 + JPEG 质量），用户无感知（spec §5.2.1规则5）
 */
import { obsApi } from '@/api'

export const IMAGE_MAX_EDGE = 2000
export const IMAGE_QUALITY = 0.85
export const IMAGE_MAX_BYTES = 10 * 1024 * 1024
export const DOCUMENT_MAX_BYTES = 20 * 1024 * 1024

/** 图片压缩：长边超过上限时缩放 + 转 JPEG；无需压缩时原样返回（spec §5.2.1规则5） */
export async function compressImage(file: File, maxEdge = IMAGE_MAX_EDGE): Promise<File> {
  if (!file.type.startsWith('image/')) return file
  try {
    const bitmap = await createImageBitmap(file)
    const scale = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height))
    if (scale >= 1 && file.size <= 2 * 1024 * 1024) {
      return file // 小图不压缩，保留原格式
    }
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(bitmap.width * scale)
    canvas.height = Math.round(bitmap.height * scale)
    const ctx = canvas.getContext('2d')
    if (!ctx) return file
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, 'image/jpeg', IMAGE_QUALITY),
    )
    if (!blob) return file
    const name = file.name.replace(/\.(png|jpe?g)$/i, '') + '.jpg'
    const compressed = new File([blob], name, { type: 'image/jpeg' })
    return compressed.size < file.size ? compressed : file
  } catch {
    return file // 解码失败按原图处理，由后端校验兜底
  }
}

/** 上传文件：presign → OBS直传 / 本地代存，返回 obs_key */
export async function uploadFile(file: File, kind: 'document' | 'image'): Promise<string> {
  const ticket = await obsApi.presign(file.name, file.type || 'application/octet-stream', kind)
  if (ticket.mode === 'obs') {
    const resp = await fetch(ticket.upload_url, {
      method: 'PUT',
      headers: ticket.headers,
      body: file,
    })
    if (!resp.ok) throw new Error(`OBS直传失败: ${resp.status}`)
  } else {
    await obsApi.localUpload(ticket.obs_key, file)
  }
  return ticket.obs_key
}
