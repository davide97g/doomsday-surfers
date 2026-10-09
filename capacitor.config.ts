import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.davideghiotto.scrollcoaster',
  appName: 'Scrollcoaster',
  webDir: 'dist',
  // Perf builds (VITE_PERF=1, scripts/device.sh --perf) forward the JS console
  // to the device log so the frame stats can be read; normal builds stay quiet.
  loggingBehavior: process.env.VITE_PERF === '1' ? 'production' : 'debug',
  ios: {
    contentInset: 'never',
    backgroundColor: '#07040f',
    scrollEnabled: false,
  },
};

export default config;
