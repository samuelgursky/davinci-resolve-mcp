/**
 * media-blobs — decode/encode the simple fixed-size 16-byte Media Pool / timeline metadata blobs.
 * Mapped + verified against real Resolve 21 exports (see knowledge/blob-map.md).
 *
 *   Resolution      = [u32 0][u32 width][u32 0][u32 height]  (big-endian)
 *   FrameRate       = [double fps][double 0]                 (little-endian) — timeline fps
 *   MediaFrameRate  = [double fps][double 0]                 (little-endian) — clip source fps
 *   MediaExtents    = [double startSeconds][double durationSeconds] (little-endian)
 *
 * @module drp-format/media-blobs
 */

function decodeResolutionBlob(hex) {
  const b = Buffer.from(hex, 'hex');
  if (b.length !== 16) return null;
  return { width: b.readUInt32BE(4), height: b.readUInt32BE(12) };
}
function encodeResolutionBlob({ width, height }) {
  const b = Buffer.alloc(16);
  b.writeUInt32BE(width >>> 0, 4);
  b.writeUInt32BE(height >>> 0, 12);
  return b.toString('hex');
}

// FrameRate / MediaFrameRate share the same [double fps][double 0] shape.
function decodeRateBlob(hex) {
  const b = Buffer.from(hex, 'hex');
  if (b.length !== 16) return null;
  return b.readDoubleLE(0);
}
function encodeRateBlob(fps) {
  const b = Buffer.alloc(16);
  b.writeDoubleLE(fps, 0);
  return b.toString('hex');
}

function decodeMediaExtentsBlob(hex) {
  const b = Buffer.from(hex, 'hex');
  if (b.length !== 16) return null;
  return { startSeconds: b.readDoubleLE(0), durationSeconds: b.readDoubleLE(8) };
}
function encodeMediaExtentsBlob({ startSeconds, durationSeconds }) {
  const b = Buffer.alloc(16);
  b.writeDoubleLE(startSeconds, 0);
  b.writeDoubleLE(durationSeconds, 8);
  return b.toString('hex');
}

module.exports = {
  decodeResolutionBlob, encodeResolutionBlob,
  decodeRateBlob, encodeRateBlob,
  decodeMediaExtentsBlob, encodeMediaExtentsBlob,
};
