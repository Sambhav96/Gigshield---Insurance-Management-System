import { MetadataRoute } from 'next';
 
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'GigShield Rider Telematics',
    short_name: 'GS Rider',
    description: 'GigShield Rider Operations Mobile Terminal',
    start_url: '/rider', // Native access point drops straight to dashboard
    display: 'standalone',
    background_color: '#0a0e14',
    theme_color: '#0a0e14',
    orientation: 'portrait-primary',
    icons: [
      {
        src: '/icons/icon-192x192.png',
        sizes: '192x192',
        type: 'image/png',
        purpose: 'maskable'
      },
      {
        src: '/icons/icon-512x512.png',
        sizes: '512x512',
        type: 'image/png',
        purpose: 'any'
      },
    ],
  }
}
