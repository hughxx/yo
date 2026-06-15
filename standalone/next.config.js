/** @type {import('next').NextConfig} */
const nextConfig = {
  // Tauri 加载静态导出产物（src-tauri/tauri.conf.json -> frontendDist: ../out）
  output: 'export',
  // Tauri WebView 不需要 Next 的图片优化服务
  images: { unoptimized: true },
  // 资源用相对路径，便于在 file:// 下加载
  assetPrefix: '',
  trailingSlash: true,
};

module.exports = nextConfig;
